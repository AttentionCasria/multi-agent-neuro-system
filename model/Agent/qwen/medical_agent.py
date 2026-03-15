# Agent/qwen/medicalAgent.py — 极速版 v2：rerank 失败时 graceful fallback

import logging
import traceback
import time
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.messages import SystemMessage, HumanMessage
from makeData.Retrieve import UnifiedSearchEngine, CONFIG
from config.config_loader import PromptManager

logger = logging.getLogger(__name__)


class MedicalReActAgent:

    _FALLBACK_SEARCH_PROMPT = """你是医学检索专家。
根据以下临床问题生成 2 个精准中文检索关键词组合。
每行一个，必须使用中文医学术语，不要解释。
临床问题：{question}"""

    # 【修改点4】优先提取AHA/ASA指南推荐等级
    _FALLBACK_EVIDENCE_PROMPT = """你是循证医学证据整理专家。
临床问题：{question}
检索文献：{evidence}
任务：提取与问题直接相关的事实，保留推荐等级和具体数字。优先提取指南。"""

    def __init__(
        self,
        llm_main,
        llm_fast,
        retriever: UnifiedSearchEngine,
        prompt_manager: Optional[PromptManager] = None
    ):
        self.llm_main = llm_main
        self.llm_fast = llm_fast
        self.retriever = retriever
        self.prompts = prompt_manager

    # ============================
    # 极速模式：直接检索，0 次 LLM
    # ============================

    def fast_retrieve(self, question: str) -> str:
        """直接用问题文本检索，不经过LLM。"""
        try:
            t0 = time.time()
            logger.info(f"📋 [MedicalAgent] 快速检索: {question[:60]}...")

            top_k = CONFIG.get("top_k_final", 3)
            search_query = question

            # 【修改点4】优先拉取最新指南
            if "指南" in question or "AHA" in question or "ASA" in question:
                top_k = 5  # 多拉几条
                search_query = question + " 2023 2026 AHA/ASA 中国卒中指南"

            # 带重试的检索（应对 rerank rate limit）
            docs = self._search_with_retry(search_query, top_k)

            if not docs:
                logger.warning(f"  ⚠️ 未检索到文档: {question[:40]}")
                return ""

            elapsed = time.time() - t0
            logger.info(
                f"  📄 命中 {len(docs)} 条文档 ({elapsed:.1f}s)"
            )

            results = []
            for i, doc in enumerate(docs):
                source = doc.metadata.get(
                    "source", "未知"
                ).replace(".pdf", "")
                page = doc.metadata.get("page", "?")
                score = doc.metadata.get("relevance_score", "N/A")

                logger.info(
                    f"    文献{i+1}: 《{source}》p.{page} "
                    f"(相关度:{score})"
                )

                # 限制每条文档长度，减少总 token
                content = doc.page_content[:400]
                results.append(
                    f"【文献{i+1}】[来源: 《{source}》 p.{page}] "
                    f"(相关度:{score})\n{content}"
                )

            return "\n\n".join(results)

        except Exception as e:
            logger.error(f"快速检索失败: {e}")
            return ""

    def _search_with_retry(self, query, top_k, max_retries=2):
        """带重试的检索，应对 rerank API rate limit"""
        for attempt in range(max_retries + 1):
            try:
                return self.retriever.search(query, top_k)
            except Exception as e:
                err_str = str(e)
                if "RateQuota" in err_str or "rate limit" in err_str.lower():
                    if attempt < max_retries:
                        wait = 1.0 * (attempt + 1)
                        logger.warning(
                            f"  ⚠️ Rerank 限流，{wait}s 后重试 "
                            f"({attempt+1}/{max_retries})"
                        )
                        time.sleep(wait)
                        continue
                # 非限流错误或重试耗尽
                raise
        return []

    # ============================
    # 完整模式（保留）
    # ============================

    def run(self, question: str) -> str:
        try:
            logger.info(f"📋 [MedicalAgent] 完整处理: {question}")

            queries = self._generate_search_queries(question)
            logger.info(f"  🔑 生成检索关键词: {queries}")

            evidence_text = self._parallel_search(queries)
            logger.info(f"  📚 检索到证据: {len(evidence_text)} 字符")

            if not evidence_text:
                return "未检索到相关医学文献。"

            result = self._synthesize_evidence(question, evidence_text)
            logger.info(f"  ✅ 证据整合完成")
            return result

        except Exception as e:
            logger.error(f"MedicalReActAgent错误: {e}")
            logger.error(traceback.format_exc())
            return "证据层运行异常。"

    def _generate_search_queries(self, question: str) -> List[str]:
        prompt = None
        if self.prompts:
            prompt = self.prompts.get(
                "search_query_generation", question=question
            )
        if not prompt:
            prompt = self._FALLBACK_SEARCH_PROMPT.format(question=question)

        resp = self.llm_fast.invoke([
            SystemMessage(content="你是医学检索专家。请用中文回答。"),
            HumanMessage(content=prompt)
        ])

        lines = [
            l.strip().lstrip("0123456789.-·•) ")
            for l in resp.content.split("\n")
            if l.strip() and len(l.strip()) > 2
        ]

        chinese_lines = [
            l for l in lines
            if any('\u4e00' <= c <= '\u9fff' for c in l)
        ]

        if chinese_lines:
            return chinese_lines[:2]
        elif lines:
            return lines[:2]
        else:
            cn_chars = ''.join(
                c for c in question if '\u4e00' <= c <= '\u9fff'
            )
            return [cn_chars[:30]] if cn_chars else [question[:50]]

    def _parallel_search(self, queries: List[str]) -> str:
        results = []
        with ThreadPoolExecutor(max_workers=min(3, len(queries))) as executor:
            future_map = {
                executor.submit(
                    self._search_with_retry, q, CONFIG.get("top_k_final", 3)
                ): q for q in queries
            }
            for future in as_completed(future_map):
                q = future_map[future]
                try:
                    docs = future.result()
                    for i, doc in enumerate(docs):
                        source = doc.metadata.get(
                            "source", "未知"
                        ).replace(".pdf", "")
                        page = doc.metadata.get("page", "?")
                        score = doc.metadata.get("relevance_score", "N/A")
                        results.append(
                            f"【{q}-文献{i+1}】"
                            f"[来源: 《{source}》 p.{page}] "
                            f"(相关度:{score})\n"
                            f"{doc.page_content[:500]}"
                        )
                except Exception as e:
                    logger.error(f"检索失败 [{q}]: {e}")
        return "\n\n".join(results)

    def _synthesize_evidence(self, question: str, evidence: str) -> str:
        prompt_text = None
        if self.prompts:
            prompt_text = self.prompts.get(
                "evidence_synthesis", question=question, evidence=evidence
            )
        if not prompt_text:
            prompt_text = self._FALLBACK_EVIDENCE_PROMPT.format(
                question=question, evidence=evidence
            )
        resp = self.llm_main.invoke([
            SystemMessage(content="你是循证医学专家。请用中文回答。"),
            HumanMessage(content=prompt_text)
        ])
        return resp.content