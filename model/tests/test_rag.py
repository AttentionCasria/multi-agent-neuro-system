import os
import sys
import logging
from dotenv import load_dotenv

# 确保在项目根目录下可以导入其他模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rag.retrievers import UnifiedSearchEngine, CONFIG

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def test_rag_retrieval():
    logger.info("==========================================")
    logger.info("🧪 开始测试 RAG 检索功能")
    logger.info("==========================================")

    # 1. 尝试初始化检索引擎 (如果之前已经构建过，这里只会执行加载并连通)
    persist_dir = CONFIG.get("persist_dir", "./chroma_db_unified")
    logger.info(f"👉 初始化检索引擎 (使用数据库路径: {persist_dir})")
    try:
        search_engine = UnifiedSearchEngine(persist_dir=persist_dir, top_k=3)
        logger.info("✅ 检索引擎初始化成功！")
    except Exception as e:
        logger.error(f"❌ 检索引擎初始化失败: {e}")
        return

    # 2. 定义想要测试验证的问题
    test_queries = [
        "脑梗死后出血转化的主要危险因素有哪些？",
        "急性缺血性脑卒中的静脉溶栓时间窗是多久？",
        "什么是阿替普酶，应该怎么使用？"
    ]

    # 3. 对每个问题执行检索，并展示匹配的相关片段和得分
    for i, query in enumerate(test_queries, 1):
        logger.info("\n" + "="*50)
        logger.info(f"🧐 【测试问题 {i}】: {query}")
        logger.info("="*50)

        # 执行检索
        try:
            docs = search_engine.search(query, top_k_final=3)
            
            if not docs:
                logger.warning("⚠️ 未检索到相关文档！")
                continue
                
            logger.info(f"🎯 共召回 {len(docs)} 条相关结果:\n")
            for j, doc in enumerate(docs, 1):
                source = doc.metadata.get("source", "未知出处")
                page = doc.metadata.get("page", "未知页码")
                score = doc.metadata.get("relevance_score", "N/A")
                doc_type = doc.metadata.get("doc_type", "原文")
                
                # 更新判定条件：匹配我们新的 batch 生成类型的标签
                if doc_type in ["qa_generated", "qa_generated_batch"]:
                    type_tag = "[生成的 QA 对]"
                else:
                    type_tag = "[切割的文档片段]"
                
                logger.info(f"--- 结果 {j} ---")
                logger.info(f"来源: {source} (页码: {page}) {type_tag} | 重排得分(相关度): {score}")
                logger.info(f"内容内容预览: {doc.page_content[:200]}...")
                logger.info("-" * 40)
                
        except Exception as e:
            logger.error(f"❌ '{query}' 检索时发生异常: {e}")

if __name__ == "__main__":
    load_dotenv()
    test_rag_retrieval()
