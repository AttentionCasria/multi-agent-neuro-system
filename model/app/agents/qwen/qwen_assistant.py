
import logging
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, AsyncGenerator, Dict

from langchain_core.messages import HumanMessage, SystemMessage
from app.agents.qwen.medical_agent import MedicalReActAgent
from app.config.config_loader import PromptManager, ReportTemplateManager

logger = logging.getLogger(__name__)


class MedicalAssistant:

    def __init__(
        self,
        llm_main=None,
        llm_fast=None,
        retriever=None,
        prompt_manager: PromptManager = None,
        report_manager: ReportTemplateManager = None,
        llm=None,
    ):
        if llm_main is None:
            llm_main = llm
        if llm_fast is None:
            llm_fast = llm_main

        self.llm = llm_main
        self.llm_fast = llm_fast
        self.retriever = retriever
        self.prompts = prompt_manager
        self.reports = report_manager

        self.agent = MedicalReActAgent(
            llm_main=self.llm,
            llm_fast=self.llm_fast,
            retriever=self.retriever,
            prompt_manager=self.prompts
        )

        logger.info("✅ MedicalAssistant（极速版 v2）初始化完成")


    def fast_parallel_retrieve(self, sub_questions: List[str]) -> str:
        if not sub_questions:
            return ""

        logger.info(f"🔍 快速并行检索 {len(sub_questions)} 个子问题...")

        results = {}
        worker_count = min(len(sub_questions), 3)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(self.agent.fast_retrieve, q): q
                for q in sub_questions
            }

            for future in as_completed(future_map):
                q = future_map[future]
                try:
                    results[q] = future.result()
                except Exception as e:
                    logger.error(f"子问题检索失败: {q} | {e}")
                    results[q] = ""

        from app.agents.qwen.qwen_agent import MAX_EVIDENCE_PER_QUESTION
        parts = []
        for i, q in enumerate(sub_questions):
            r = results.get(q, "")
            if r:
                if len(r) > MAX_EVIDENCE_PER_QUESTION:
                    r = r[:MAX_EVIDENCE_PER_QUESTION] + "... [已截断]"
                parts.append(f"### 检索维度{i+1}: {q}\n{r}")

        combined = "\n\n---\n\n".join(parts)
        logger.info(f"🔍 检索完成，总长度: {len(combined)} 字符")
        return combined

    def parallel_retrieve_and_synthesize(
        self, sub_questions: List[str]
    ) -> str:
        if not sub_questions:
            return ""

        results = {}
        worker_count = min(len(sub_questions), 3)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(self.agent.run, q): q
                for q in sub_questions
            }
            for future in as_completed(future_map):
                q = future_map[future]
                try:
                    results[q] = future.result()
                except Exception as e:
                    logger.error(f"子问题检索失败: {q} | {e}")
                    results[q] = "未检索到直接证据"

        parts = []
        for i, q in enumerate(sub_questions):
            parts.append(
                f"### 检索维度{i+1}: {q}\n{results.get(q, '未检索到')}"
            )
        return "\n\n---\n\n".join(parts)

    async def stream_fast_response(
        self, case_text: str, evidence: str = ""
    ) -> AsyncGenerator[str, None]:
        try:
            prompt = (
                f"你是三甲医院神经内科主任医师。\n\n"
                f"【患者信息】\n{case_text}\n\n"
                f"【参考证据】\n{evidence if evidence else '无'}\n\n"
                f"请简洁回答，禁止确诊语气，禁止具体剂量。"
            )

            if self.prompts:
                p = self.prompts.get(
                    "fast_track",
                    case_text=case_text,
                    evidence=evidence if evidence else "无"
                )
                if p:
                    prompt = p

            messages = [
                SystemMessage(content=self.reports.system_role),
                HumanMessage(content=prompt)
            ]

            async for chunk in self.llm_fast.astream(messages):
                if hasattr(chunk, "content") and chunk.content:
                    yield chunk.content
                elif isinstance(chunk, str) and chunk:
                    yield chunk

        except Exception as e:
            logger.exception("❌ 快速通道响应失败")
            yield "⚠️ 系统异常，请结合临床独立判断。"

    async def stream_final_report(
        self,
        context: Dict,
        proposal: str,
        critique: str,
        evidence: str,
        all_info: str = "",
        report_mode: str = "emergency"
    ) -> AsyncGenerator[str, None]:

        try:
            template_name = self.reports.get_template_name(report_mode)
            logger.info(f"📝 生成报告: {template_name} (模式={report_mode})")

            report_template = self.reports.get_template(report_mode)

            context_str = (
                json.dumps(context, ensure_ascii=False, indent=2)
                if isinstance(context, dict) else str(context)
            )

            prompt_text = report_template.format(
                context=context_str,
                all_info=all_info if all_info else "无历史记录",
                evidence=evidence if evidence else "未检索到相关证据",
                proposal=proposal if proposal else "无",
                critique=critique if critique else "无批判意见"
            )

            messages = [
                SystemMessage(content=self.reports.system_role),
                HumanMessage(content=prompt_text)
            ]

            async for chunk in self.llm.astream(messages):
                if hasattr(chunk, "content") and chunk.content:
                    yield chunk.content
                elif isinstance(chunk, str) and chunk:
                    yield chunk

            logger.info("✅ 报告生成完成")

        except Exception as e:
            logger.exception("❌ 报告生成失败")
            yield "⚠️ 系统异常，请结合临床独立判断。"