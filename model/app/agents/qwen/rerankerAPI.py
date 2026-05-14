import logging
import requests
from typing import List, Tuple
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class DashScopeReranker:

    def __init__(self):
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "未找到 DASHSCOPE_API_KEY 环境变量，请在 .env 文件中配置"
            )
        self.url = (
            "https://dashscope.aliyuncs.com/api/v1/services/"
            "rerank/text-rerank/text-rerank"
        )
        self.model = "gte-rerank"
        logger.info("✅ [DashScopeReranker] 初始化成功")

    def rerank(
        self, query: str, documents: List[str], top_k: int = 5
    ) -> List[Tuple[int, str, float]]:
        if not documents:
            logger.warning("⚠️ [DashScopeReranker] 文档列表为空")
            return []

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "input": {"query": query, "documents": documents},
                "parameters": {
                    "top_n": min(top_k, len(documents)),
                    "return_documents": True
                }
            }

            logger.info(
                f"🔄 [DashScopeReranker] 重排序 {len(documents)} 条文档..."
            )

            response = requests.post(
                self.url, headers=headers, json=payload, timeout=10
            )
            response.raise_for_status()
            result = response.json()

            if result.get("code") and result["code"] != "200":
                error_msg = result.get("message", "未知错误")
                logger.error(f"❌ [DashScopeReranker] API错误: {error_msg}")
                raise Exception(error_msg)

            rerank_results = result["output"]["results"]
            logger.info(
                f"✅ [DashScopeReranker] 返回 {len(rerank_results)} 条"
            )

            return [
                (item["index"], item["document"]["text"], item["relevance_score"])
                for item in rerank_results
            ]

        except requests.exceptions.Timeout:
            logger.error("❌ [DashScopeReranker] 请求超时")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ [DashScopeReranker] 网络失败: {e}")
            return []
        except KeyError as e:
            logger.error(f"❌ [DashScopeReranker] 解析失败: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ [DashScopeReranker] 调用失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []