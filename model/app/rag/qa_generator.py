import os
import logging
from typing import List
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

class QAGenerator:
    def __init__(self, model_name="qwen-turbo"):
        """
        初始化大模型调用。项目里主要用的是阿里云 DashScope (qwen-turbo)。
        """
        api_key = os.getenv("DASHSCOPE_API_KEY")
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        
        if not api_key:
            logger.warning("⚠️ 未找到 DASHSCOPE_API_KEY，QA生成可能失败。")
            
        self.llm = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url
        )
        self.prompt = ChatPromptTemplate.from_template(
            "你是一个专业的医学助理。请阅读以下由多个连续医学文档片段组合而成的长文本，提取出其中最重要的关联信息，生成3到5个高质量的问答对(Q&A)。\n"
            "这能够帮助建立倒排检索的向量库。\n\n"
            "输出格式要求，请严格按照：\n"
            "Q: [问题1]\n"
            "A: [答案1]\n\n"
            "Q: [问题2]\n"
            "A: [答案2]\n\n"
            "文档片段集合：\n{text}"
        )
        self.chain = self.prompt | self.llm

    def generate_qa_for_chunks(self, chunks: List[Document], batch_size: int = 10) -> List[Document]:
        """
        将多个 chunk 合并打批传给大模型生成 QA，从而大幅节省接口请求次数并提升速度。
        """
        qa_docs = []
        logger.info(f"🧠 开始为 {len(chunks)} 个chunk生成QA对 (按每 {batch_size} 个chunk打一个批次进行加速)...")
        
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i + batch_size]
            
            if i > 0 and (i // batch_size) % 5 == 0:
                logger.info(f"  ...已处理 {i}/{len(chunks)} 个 chunk (批次进度: {i // batch_size})")

            # 将这 10 个片段合并为一段大文本交由大模型一次性处理
            combined_text = "\n\n--- 片段分隔 ---\n\n".join([c.page_content for c in batch_chunks])
            
            # 使用集合去重这批 chunk 的来源与页码信息
            sources = list(set([c.metadata.get("source", "未知") for c in batch_chunks]))
            pages = list(set([str(c.metadata.get("page", "")) for c in batch_chunks]))
            
            merged_meta = {
                "source": ", ".join(sources),
                "page": ", ".join(pages),
                "doc_type": "qa_generated_batch",
                "original_chunk_count": len(batch_chunks)
            }
            
            try:
                response = self.chain.invoke({"text": combined_text})
                qa_content = response.content.strip()
                
                # 若生成的文本为空或者非常短则跳过
                if len(qa_content) < 10:
                    continue
                    
                qa_doc = Document(page_content=qa_content, metadata=merged_meta)
                qa_docs.append(qa_doc)
                
                # 每处理一定批次后，打印演示
                if len(qa_docs) % 5 == 0:
                    logger.info(f"  📝 最新生成的批次 QA 对 (合并来源: {merged_meta['source']}):\n{qa_content}\n" + "-"*40)
                    
            except Exception as e:
                logger.error(f"❌ 生成 QA 失败 (批次 {i // batch_size}): {e}")
                
        logger.info(f"✅ QA 生成完成，共生成 {len(qa_docs)} 个综合 QA 集合(批次)！")
        return qa_docs
