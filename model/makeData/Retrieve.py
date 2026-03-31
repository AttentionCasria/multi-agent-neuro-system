# makeData/Retrieve.py — 优化版：空文档安全 + 检索缓存 + 配置优化

import logging
import os
import hashlib
import time
from typing import List
from dotenv import load_dotenv
from langchain.schema import Document
from langchain_community.embeddings import DashScopeEmbeddings
from chromadb.config import Settings
from http import HTTPStatus
import dashscope

load_dotenv()
logger = logging.getLogger(__name__)

# ==========================================
# 配置
# ==========================================
CONFIG = {
    "persist_dir": "./chroma_db_unified",
    "docs_dir": "./docs",
    "top_k_per_store": 4,
    "top_k_final": 3,
    "use_reranker": True,
    "reranker_initial_k": 8,
}

# ==========================================
# 工具函数
# ==========================================

def clean_text(text: str) -> str:
    text = text.replace("\n", "").replace(" ", "")
    text = text.replace("，，", "，").replace("。。", "。")
    return text.strip()


from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document


def load_pdfs_from_dir(dir_path: str):
    documents = []
    if not os.path.exists(dir_path):
        logger.warning(f"⚠️ 文档目录不存在: {dir_path}")
        return []
    for filename in os.listdir(dir_path):
        if not filename.lower().endswith(".pdf"):
            continue
        pdf_path = os.path.join(dir_path, filename)
        logger.info(f"📄 加载 PDF: {filename}")
        try:
            loader = PyPDFLoader(pdf_path)
            pages = loader.load()
            for page in pages:
                cleaned = clean_text(page.page_content)
                if len(cleaned) < 50:
                    continue
                documents.append(Document(
                    page_content=cleaned,
                    metadata={
                        "source": filename,
                        "page": page.metadata.get("page", -1)
                    }
                ))
        except Exception as e:
            logger.error(f"❌ 加载 {filename} 失败: {e}")
    logger.info(f"✅ 共加载 {len(documents)} 页医学文档")
    return documents


from langchain.text_splitter import RecursiveCharacterTextSplitter


def split_documents(documents):
    if not documents:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=512,
        chunk_overlap=128,
        separators=["\n\n", "。", "；", "\n", " ", ""]
    )
    return splitter.split_documents(documents)


# ==========================================
# Reranker
# ==========================================

class BGEReranker:
    def __init__(self, top_k: int = 5):
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            logger.warning("⚠️ 未找到 DASHSCOPE_API_KEY，Rerank 可能失效")
        self.top_k = top_k
        self.model = "gte-rerank"

    def rerank(self, query: str, docs: List[Document]) -> List[Document]:
        if not docs:
            return []
        try:
            doc_contents = [doc.page_content for doc in docs]
            resp = dashscope.TextReRank.call(
                model=self.model,
                query=query,
                documents=doc_contents,
                top_n=self.top_k,
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
                return docs[:self.top_k]
        except Exception as e:
            logger.error(f"❌ Rerank 异常: {e}")
            return docs[:self.top_k]


# ==========================================
# VectorStore
# ==========================================

from langchain_community.vectorstores import Chroma


def build_or_load_vectorstore(chunks, persist_dir: str):
    logger.info(f"🔌 [VectorStore] 连接: {persist_dir}")
    embeddings = DashScopeEmbeddings(
        model="text-embedding-v2",
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY")
    )
    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
        client_settings=Settings(anonymized_telemetry=False)
    )
    try:
        count = vectordb._collection.count()
        if count == 0 and chunks:
            logger.info(f"⚠️ 向量库为空，写入 {len(chunks)} 条...")
            batch_size = 32
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                try:
                    vectordb.add_documents(documents=batch)
                except Exception as e:
                    logger.error(f"❌ 批次写入失败: {e}")
            logger.info("✅ 向量库写入完成")
        else:
            logger.info(f"✅ 向量库已有 {count} 条数据")
    except Exception as e:
        logger.warning(f"⚠️ 检查向量库状态异常: {e}")
    return vectordb


# ==========================================
# 带缓存的混合检索器
# ==========================================

from langchain_community.retrievers import BM25Retriever


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

        # {cache_key: (result, timestamp)}，TTL 300s 避免跨患者上下文污染
        self._cache: dict = {}
        self._cache_ttl = 300

    def search(self, query: str, top_k_final: int = 3) -> List[Document]:
        cache_key = hashlib.md5(query.encode("utf-8")).hexdigest()
        if cache_key in self._cache:
            result, ts = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                logger.info(f"⚡ [Cache Hit] 跳过重复检索: {query[:50]}...")
                return result
            # 缓存过期，删除旧记录
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

        result = self.reranker.rerank(query, candidates)

        self._cache[cache_key] = (result, time.time())
        return result

    def clear_cache(self):
        """每次新用户请求时调用，清空上一轮缓存"""
        count = len(self._cache)
        self._cache.clear()
        if count > 0:
            logger.info(f"🗑️ [HybridRetriever] 清空 {count} 条检索缓存")


# ==========================================
# 统一搜索引擎
# ==========================================

class UnifiedSearchEngine:
    def __init__(self, persist_dir: str, top_k: int, docs_dir=None):
        logger.info("🔧 初始化 UnifiedSearchEngine...")

        self.docs_dir = (
            docs_dir
            or os.getenv("MEDICAL_DOCS_DIR")
            or "/www/wwwroot/Python-backend/Data/documents"
        )
        logger.info(f"📂 文档目录: {self.docs_dir}")

        try:
            raw_docs = load_pdfs_from_dir(self.docs_dir)
        except FileNotFoundError as e:
            logger.error(f"❌ 找不到文档目录: {self.docs_dir}")
            raw_docs = []

        self.chunks = split_documents(raw_docs)
        self.vectorstore = build_or_load_vectorstore(self.chunks, persist_dir)
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
        """代理清空底层检索器缓存"""
        self.retriever.clear_cache()