import logging
import os
import sys
import hashlib
import time
from typing import List
from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from http import HTTPStatus
import dashscope
from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever

# Monkey-patch chromadb to prevent ONNX embedding function initialization
import sys
import chromadb.utils.embedding_functions as ef_module
original_default = ef_module.DefaultEmbeddingFunction
ef_module.DefaultEmbeddingFunction = lambda: None

from langchain_chroma import Chroma

# Add parent directory to path to absolute imports work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.rag.data_loader import load_pdfs_from_dir, split_documents
from app.rag.qa_generator import QAGenerator


load_dotenv()
logger = logging.getLogger(__name__)

CONFIG = {
    "persist_dir": os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_db_unified"),
    "docs_dir": os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "documents"),
    "top_k_per_store": 4,
    "enable_qa_generation": True,
}


class DashScopeEmbeddings(Embeddings):
    def __init__(self, model: str = "text-embedding-v2"):
        self.model = model
        self.api_key = os.getenv("DASHSCOPE_API_KEY")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        result = []
        for i in range(0, len(texts), 25):
            batch = texts[i:i + 25]
            resp = dashscope.TextEmbedding.call(
                model=self.model,
                input=batch,
                api_key=self.api_key,
            )
            if resp.status_code == HTTPStatus.OK:
                for item in resp.output["embeddings"]:
                    result.append(item["embedding"])
            else:
                raise ValueError(f"DashScope embedding 失败: {resp.code} - {resp.message}")
        return result

    def embed_query(self, text: str) -> List[float]:
        resp = dashscope.TextEmbedding.call(
            model=self.model,
            input=text,
            api_key=self.api_key,
        )
        if resp.status_code == HTTPStatus.OK:
            return resp.output["embeddings"][0]["embedding"]
        else:
            raise ValueError(f"DashScope embedding 失败: {resp.code} - {resp.message}")


class BGEReranker:
    def __init__(self, top_k: int = 5):
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            logger.warning("⚠️ 未找到 DASHSCOPE_API_KEY，Rerank 可能失效")
        self.top_k = top_k
        self.model = "gte-rerank"

    def rerank(self, query: str, docs: List[Document], top_k: int = None) -> List[Document]:
        if not docs:
            return []
        
        actual_top_k = top_k if top_k is not None else self.top_k
        try:
            doc_contents = [doc.page_content for doc in docs]
            resp = dashscope.TextReRank.call(
                model=self.model,
                query=query,
                documents=doc_contents,
                top_n=actual_top_k,
                return_documents=True,
                api_key=self.api_key,
            )
            if resp.status_code == HTTPStatus.OK:
                reranked = []
                for item in resp.output.results:
                    original_doc = docs[item.index]
                    original_doc.metadata["relevance_score"] = item.relevance_score
                    reranked.append(original_doc)
                logger.info(f"✅ Rerank 完成，{len(docs)} → {len(reranked)} 条")
                return reranked
            else:
                logger.error(f"❌ Rerank API 失败: {resp.code} - {resp.message}")
                return docs[:actual_top_k]
        except Exception as e:
            logger.error(f"❌ Rerank 异常: {e}")
            return docs[:actual_top_k]


def build_or_load_vectorstore(chunks, persist_dir: str, enable_qa: bool = False):
    logger.info(f"🔌 [VectorStore] 连接: {persist_dir}")
    embeddings = DashScopeEmbeddings(model="text-embedding-v2")
    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )
    try:
        count = vectordb._collection.count()
        if count == 0 and chunks:
            docs_to_insert = chunks
            if enable_qa:
                logger.info(f"⚠️ 向量库为空，准备为 {len(chunks)} 条切片生成扩展QA对...")
                qa_gen = QAGenerator()
                qa_docs = qa_gen.generate_qa_for_chunks(chunks)
                docs_to_insert = chunks + qa_docs
                logger.info(f"入库总计：{len(chunks)}条原文 + {len(qa_docs)}条QA对 = {len(docs_to_insert)}条")
            else:
                logger.info(f"⚠️ 向量库为空，写入 {len(chunks)} 条...")

            batch_size = 32
            total_docs = len(docs_to_insert)
            for i in range(0, total_docs, batch_size):
                batch = docs_to_insert[i:i + batch_size]
                try:
                    vectordb.add_documents(documents=batch)
                    current_processed = min(i + batch_size, total_docs)
                    # 每 5 个批次或是最后一批时打印进度
                    if (i // batch_size + 1) % 5 == 0 or current_processed == total_docs:
                        logger.info(f"  ⏳ 正在写入向量库... 已完成: {current_processed} / {total_docs} 条")
                except Exception as e:
                    logger.error(f"❌ 批次写入失败 (起始索引 {i}): {e}")
            logger.info("✅ 向量库写入完成")
        else:
            logger.info(f"✅ 向量库已有 {count} 条数据")
    except Exception as e:
        logger.warning(f"⚠️ 检查向量库状态异常: {e}")
    return vectordb


class HybridRetriever:
    def __init__(self, vectordb, documents, k=20):
        self.vector_retriever = vectordb.as_retriever(search_kwargs={"k": k})
        self.reranker = BGEReranker(top_k=CONFIG.get("top_k_final", 3))

        if documents and len(documents) > 0:
            self.bm25 = BM25Retriever.from_documents(documents)
            self.bm25.k = k
        else:
            self.bm25 = None
            logger.warning("⚠️ [HybridRetriever] 文档为空，BM25 未初始化")

        self._cache: dict = {}
        self._cache_ttl = 300

    def search(self, query: str, top_k_final: int = 3) -> List[Document]:
        cache_key = hashlib.md5(f"{query}_{top_k_final}".encode("utf-8")).hexdigest()
        if cache_key in self._cache:
            result, ts = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                logger.info(f"⚡ [Cache Hit] 跳过重复检索: {query[:50]}...")
                return result
            del self._cache[cache_key]

        logger.info(f"🔍 [HybridRetriever] 检索: {query[:60]}...")

        v_docs = self.vector_retriever.invoke(query)
        b_docs = self.bm25.invoke(query) if self.bm25 else []

        seen = {}
        for d in v_docs + b_docs:
            seen[d.page_content] = d
        candidates = list(seen.values())

        if not candidates:
            logger.warning("⚠️ 检索结果为空")
            self._cache[cache_key] = ([], time.time())
            return []

        logger.info(f"🔍 召回 {len(candidates)} 条，开始 rerank...")

        result = self.reranker.rerank(query, candidates, top_k=top_k_final)

        self._cache[cache_key] = (result, time.time())
        return result

    def clear_cache(self):
        count = len(self._cache)
        self._cache.clear()
        if count > 0:
            logger.info(f"🗑️ [HybridRetriever] 清空 {count} 条检索缓存")


class UnifiedSearchEngine:
    def __init__(self, persist_dir: str, top_k: int, docs_dir=None):
        logger.info("🔧 初始化 UnifiedSearchEngine...")

        self.docs_dir = (
                docs_dir
                or os.getenv("MEDICAL_DOCS_DIR")
                or CONFIG.get("docs_dir", "./data/documents")
        )
        logger.info(f"📂 文档目录: {self.docs_dir}")

        try:
            raw_docs = load_pdfs_from_dir(self.docs_dir)
        except Exception as e:
            logger.error(f"❌ 加载文档失败: {e}")
            raw_docs = []

        self.chunks = split_documents(raw_docs)
        self.vectorstore = build_or_load_vectorstore(
            self.chunks,
            persist_dir,
            enable_qa=bool(CONFIG.get("enable_qa_generation", False))
        )
        self.retriever = HybridRetriever(
            self.vectorstore,
            raw_docs,
            k=CONFIG.get("reranker_initial_k", 8)
        )

    def search(self, query: str, top_k_final: int = 3) -> List[Document]:
        try:
            logger.info(f"🔍 执行检索: {query[:60]}...")
            docs = self.retriever.search(query, top_k_final=top_k_final)
            logger.info(f"🏆 检索完成，命中 {len(docs)} 条")
            return docs
        except Exception as e:
            logger.error(f"❌ 检索失败: {e}")
            return []

    def clear_cache(self):
        self.retriever.clear_cache()