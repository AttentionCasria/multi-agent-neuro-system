# Agent/qwen/qwen_agent.py — LangGraph 原始四节点管线 v4
#
# 重构说明：
# - 删除全部死代码（MCQ路径、未使用的 _build_graph、废弃分类器、旧 analyze_patient_risk）
# - 以 LangGraph StateGraph 实现原始推理管线（intent→analysis→retrieve→reason→report）
# - astream_events(version="v2") + 事件翻译层输出新 SSE 事件格式
#   新格式：node_start / node_done / token / done / error
# - /ai/analyze 快速风险评估独立保留，复用 llm_critic 实例

import logging
import asyncio
import json
from typing import AsyncGenerator, List, Dict, Any, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import StateGraph, END

from config.config_loader import PromptManager, ReportTemplateManager
from error_codes import build_error_event, format_error_log

logger = logging.getLogger(__name__)

# 检索相关上限
MAX_SUB_QUESTIONS      = 3
MAX_EVIDENCE_CHARS     = 2000
MAX_EVIDENCE_PER_QUESTION = 600
MAX_PROPOSAL_CHARS     = 3000
MAX_CRITIQUE_CHARS     = 3000

# ── 意图分类 Prompt ───────────────────────────────────────────────────────────
_INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("human", """你是意图分类专家。请判断以下输入的类型：

- consultation: 具体患者问诊或病例分析（包含患者症状、检查等细节）
- knowledge: 脑卒中通用知识询问（如症状、药品作用、禁忌、预防等，无具体患者细节）
- irrelevant: 非脑卒中医疗相关

输入：{case_text}

输出 JSON：

{{
    "type": "consultation/knowledge/irrelevant",
    "reason": "简要原因"
}}

严格区分：如果有患者具体信息，为consultation；如果是一般性问题，为knowledge；否则irrelevant。""")
])

# ── 非 user_questions 路径的 proposer fallback 提示词 ────────────────────────
_FALLBACK_PROPOSER = """你是三甲医院神经内科主任医师，拥有 20 年急诊经验。

【患者结构化信息】
{context}

【历史上下文】
{all_info}

【检索到的循证医学证据】
{evidence}

请给出完整临床推理：
1. 鉴别诊断排序（至少3个，含概率区间和依据）
2. 当前最危险的生理问题
3. 立即行动建议（分钟级、小时级、24h内）
4. 关键风险分析
5. 缺失的关键信息
6. 不确定性声明
7. 证据支持说明

禁止确诊语气。禁止具体药物剂量。"""

# ── 节点人类可读标签（用于 node_start 事件）──────────────────────────────────
_NODE_LABELS: Dict[str, str] = {
    "intent":          "正在判断问题类型...",
    "reject":          "正在处理回复...",
    "analysis":        "正在分析病例结构...",
    "retrieve":        "正在检索循证医学证据...",
    "reason":          "正在进行临床推理...",
    "report":          "正在生成临床报告...",
    "knowledge_answer":"正在回答知识问题...",
}

# ── 图状态定义 ────────────────────────────────────────────────────────────────
class ClinicalState(TypedDict, total=False):
    case_text:         str
    all_info:          str
    report_mode:       str
    intent_type:       str
    context:           Dict
    clinical_questions: List[str]
    key_risks:         List[str]
    complexity:        str
    evidence:          str
    proposal:          str
    critique:          str
    user_questions:    List[str]
    report:            str


class qwenAgent:

    # 只有这两个节点的 LLM token 需要流向前端
    _STREAMING_NODES = {"knowledge_answer", "report"}

    def __init__(
        self,
        llm_proposer,
        llm_critic,
        medical_assistant,
        prompt_manager: PromptManager,
        report_manager: ReportTemplateManager,
        llm_turbo=None,
    ):
        self.llm_proposer = llm_proposer
        self.llm_critic   = llm_critic
        # llm_turbo 用于简单分类任务（intent）；未传入时回退到 llm_critic
        self.llm_turbo    = llm_turbo or llm_critic
        self.medical_assistant = medical_assistant
        self.prompts = prompt_manager
        self.reports = report_manager
        self.graph = self._build_graph()

    # ── 图构建 ────────────────────────────────────────────────────────────────

    def _build_graph(self):
        graph = StateGraph(ClinicalState)

        graph.add_node("intent",           self._node_intent)
        graph.add_node("reject",           self._node_reject)
        graph.add_node("knowledge_answer", self._node_knowledge_answer)
        graph.add_node("analysis",         self._node_analysis)
        graph.add_node("retrieve",         self._node_retrieve)
        graph.add_node("reason",           self._node_reason)
        graph.add_node("report",           self._node_report)

        graph.set_entry_point("intent")
        graph.add_conditional_edges(
            "intent",
            self._route_intent,
            {
                "irrelevant":   "reject",
                "knowledge":    "knowledge_answer",
                "consultation": "analysis",
            }
        )
        graph.add_edge("reject",           END)
        graph.add_edge("knowledge_answer", END)
        graph.add_edge("analysis",  "retrieve")
        graph.add_edge("retrieve",  "reason")
        graph.add_edge("reason",    "report")
        graph.add_edge("report",    END)

        return graph.compile()

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def _get_prompt(self, key, fallback, **kwargs):
        prompt = None
        if self.prompts:
            prompt = self.prompts.get(key, **kwargs)
        if not prompt:
            try:
                prompt = fallback.format(**kwargs)
            except KeyError:
                prompt = fallback
        return prompt

    def _parse_json(self, text: str, default=None):
        content = (text or "").strip()
        try:
            return json.loads(content)
        except Exception:
            pass
        for marker in ["```json", "```"]:
            if marker in content:
                try:
                    s = content.split(marker)[1].split("```")[0].strip()
                    return json.loads(s)
                except Exception:
                    pass
        for sc, ec in [("{", "}"), ("[", "]")]:
            si, ei = content.find(sc), content.rfind(ec)
            if si != -1 and ei > si:
                try:
                    return json.loads(content[si:ei + 1])
                except Exception:
                    pass
        return default

    def _truncate(self, text: str, max_chars: int) -> str:
        if not text or len(text) <= max_chars:
            return text
        half = max_chars // 2
        return (
            text[:half]
            + f"\n\n... [已截断 {len(text) - max_chars} 字符] ...\n\n"
            + text[-half:]
        )

    # ── 节点实现 ──────────────────────────────────────────────────────────────

    async def _node_intent(self, state: ClinicalState) -> ClinicalState:
        # 三分类任务，用 llm_turbo（qwen-turbo）即可
        chain = _INTENT_PROMPT | self.llm_turbo | StrOutputParser()
        content = await chain.ainvoke({"case_text": state["case_text"]})
        result = self._parse_json(content, {"type": "irrelevant"})
        intent_type = result.get("type", "irrelevant")
        logger.info(f"[intent] 分类结果: {intent_type}")
        return {"intent_type": intent_type}

    def _route_intent(self, state: ClinicalState) -> str:
        t = state.get("intent_type", "irrelevant")
        if t in {"consultation", "knowledge"}:
            return t
        return "irrelevant"

    async def _node_reject(self, state: ClinicalState) -> ClinicalState:
        # 静态拒绝消息，翻译层在 on_chain_end 时将其作为 token 事件发出
        return {"report": "请提供脑卒中医疗临床相关查询，此输入无关。"}

    async def _node_knowledge_answer(self, state: ClinicalState) -> ClinicalState:
        # astream 调用使 astream_events 捕获 on_chat_model_stream 事件，实现流式输出
        knowledge_prompt = f"""你是三甲医院神经内科主任医师。请基于循证医学知识，直接回答以下脑卒中相关通用问题。

问题：{state["case_text"]}

回答要求：
- 用中文，简洁专业
- 禁止确诊语气
- 禁止具体剂量
- 如果需要，引用权威指南"""
        messages = [
            SystemMessage(content=self.reports.system_role),
            HumanMessage(content=knowledge_prompt),
        ]
        content = ""
        # knowledge 问答直接输出给用户，qwen-plus 质量足够，无需 max
        async for chunk in self.llm_critic.astream(messages):
            c = chunk.content if hasattr(chunk, "content") else str(chunk)
            content += c
        return {"report": content}

    async def _node_analysis(self, state: ClinicalState) -> ClinicalState:
        analysis = await self._unified_analysis(
            state["case_text"], state.get("all_info", "")
        )
        clinical_questions = analysis.get(
            "clinical_questions", ["该患者当前最紧急的临床问题和处置要点"]
        )

        # task drift 防护：诊断意图时过滤治疗类子问题
        _DIAGNOSTIC_KW = {"TOAST", "分型", "病因", "定位", "定性", "鉴别", "卒中类型", "发病机制", "卒中原因"}
        _TREATMENT_KW  = {"溶栓", "取栓", "抗凝", "降压", "手术", "时间窗", "剂量", "适应证", "禁忌"}
        if any(kw in state["case_text"] for kw in _DIAGNOSTIC_KW):
            filtered = [q for q in clinical_questions if not any(kw in q for kw in _TREATMENT_KW)]
            if filtered:
                clinical_questions = filtered

        return {
            "context":             analysis.get("structured_context", {"原始病例": state["case_text"]}),
            "clinical_questions":  clinical_questions[:MAX_SUB_QUESTIONS],
            "key_risks":           analysis.get("key_risks", []),
            "complexity":          analysis.get("complexity", "high"),
            "user_questions":      analysis.get("user_questions", []),
        }

    async def _node_retrieve(self, state: ClinicalState) -> ClinicalState:
        # 同步检索放入线程池，避免阻塞事件循环
        loop = asyncio.get_event_loop()
        evidence = await loop.run_in_executor(
            None,
            self.medical_assistant.fast_parallel_retrieve,
            state.get("clinical_questions", []),
        )
        return {"evidence": self._truncate(evidence, MAX_EVIDENCE_CHARS)}

    async def _node_reason(self, state: ClinicalState) -> ClinicalState:
        uq = state.get("user_questions", [])
        logger.info(f"[reason] user_questions count={len(uq)}, items={uq}")
        proposal, critique = await self._parallel_propose_and_critique(
            state.get("context", {}),
            state.get("evidence", ""),
            state.get("all_info", ""),
            uq,
        )
        logger.info(f"[reason] proposal_len={len(proposal)}, critique_len={len(critique)}")
        return {"proposal": proposal, "critique": critique}

    async def _node_report(self, state: ClinicalState) -> ClinicalState:
        # user_questions 路径：proposal 已是答案，直接返回（无 LLM 流式）
        # 翻译层通过 on_chain_end fallback 机制发出完整内容
        if state.get("user_questions"):
            return {"report": state.get("proposal", "")}

        # 标准路径：直接在 LangGraph 节点内调用 llm_proposer.astream()，
        # 确保 astream_events 能捕获 on_chat_model_stream 事件实现流式输出。
        # （不通过 MedicalAssistant.stream_final_report，避免自定义 async generator
        #   截断 LangGraph 回调上下文，导致 token 无法流出）
        report_mode = state.get("report_mode", "emergency")
        context = state.get("context", {})
        context_str = (
            json.dumps(context, ensure_ascii=False, indent=2)
            if isinstance(context, dict) else str(context)
        )
        report_template = self.reports.get_template(report_mode)
        prompt_text = report_template.format(
            context=context_str,
            all_info=state.get("all_info", "") or "无历史记录",
            evidence=state.get("evidence", "") or "未检索到相关证据",
            proposal=self._truncate(state.get("proposal", ""), MAX_PROPOSAL_CHARS) or "无",
            critique=self._truncate(state.get("critique", ""), MAX_CRITIQUE_CHARS) or "无批判意见",
        )
        messages = [
            SystemMessage(content=self.reports.system_role),
            HumanMessage(content=prompt_text),
        ]
        report = ""
        async for chunk in self.llm_proposer.astream(messages):
            c = chunk.content if hasattr(chunk, "content") else str(chunk)
            report += c
        return {"report": report}

    # ── 事件翻译层 ────────────────────────────────────────────────────────────

    def _node_summary(self, node: str, output: dict) -> str:
        """从节点输出状态提取人类可读摘要，用于 node_done 事件。"""
        if not isinstance(output, dict):
            return ""
        if node == "analysis":
            q = output.get("clinical_questions", [])
            return f"提取到 {len(q)} 个临床子问题"
        if node == "retrieve":
            ev = output.get("evidence", "")
            count = ev.count("---") + 1 if ev.strip() else 0
            return f"检索到 {count} 个证据片段"
        if node == "reason":
            return "Proposer + Critic 推理完成"
        return ""

    def _translate_event(
        self,
        event: dict,
        show_thinking: bool,
        streamed_nodes: set,
    ) -> Optional[dict]:
        """
        将 LangGraph astream_events(v2) 事件翻译为业务 SSE 事件。

        映射规则：
          on_chain_start  (节点名) → node_start
          on_chain_end    (节点名) → node_done | token（fallback）
          on_chat_model_stream     → token（仅 STREAMING_NODES）
        """
        evt          = event.get("event", "")
        name         = event.get("name", "")
        meta         = event.get("metadata", {})
        langgraph_node = meta.get("langgraph_node", "")

        # 调试：打印所有 chain 级事件，确认节点名与输出结构
        if evt in ("on_chain_start", "on_chain_end"):
            logger.info(f"[DBG] evt={evt} name={name!r} langgraph_node={langgraph_node!r} "
                        f"output_keys={list(event.get('data',{}).get('output',{}).keys()) if isinstance(event.get('data',{}).get('output'),dict) else type(event.get('data',{}).get('output')).__name__}")

        # ── 节点开始 ──────────────────────────────────────────────────────────
        if evt == "on_chain_start" and name in _NODE_LABELS and show_thinking:
            return {"type": "node_start", "node": name, "label": _NODE_LABELS[name]}

        # ── 节点结束 ──────────────────────────────────────────────────────────
        if evt == "on_chain_end" and name in _NODE_LABELS:
            output = event.get("data", {}).get("output", {})
            report_text = output.get("report", "") if isinstance(output, dict) else ""

            # reject：静态拒绝文本作为单个 token 事件输出
            if name == "reject":
                return {"type": "token", "content": report_text} if report_text else None

            # knowledge_answer / report：
            # 若该节点没有通过 astream 流式输出过 token（user_questions 路径），
            # 则在此处 fallback 输出完整内容
            if name in self._STREAMING_NODES and name not in streamed_nodes:
                if report_text:
                    return {"type": "token", "content": report_text}

            # 其余节点输出进度摘要
            if show_thinking:
                summary = self._node_summary(name, output)
                return {"type": "node_done", "node": name, "summary": summary}

        # ── LLM 流式 token（仅面向用户的节点）────────────────────────────────
        if evt == "on_chat_model_stream" and langgraph_node in self._STREAMING_NODES:
            chunk = event.get("data", {}).get("chunk")
            content = getattr(chunk, "content", "") if chunk else ""
            if content:
                return {"type": "token", "content": content}

        return None

    # ── 公开推理接口 ──────────────────────────────────────────────────────────

    async def run_clinical_reasoning(
        self,
        case_text: str,
        all_info: str = "",
        report_mode: str = "emergency",
        show_thinking: bool = True,
    ) -> AsyncGenerator[dict, None]:
        """
        对外接口：驱动 LangGraph 图执行，通过事件翻译层输出业务 SSE 事件。

        事件类型：node_start / node_done / token / error
        done 事件由 main.py 在流结束后组装并发出（携带 all_info、name、request_id）。
        """
        initial_state: ClinicalState = {
            "case_text":   case_text,
            "all_info":    all_info,
            "report_mode": report_mode,
        }
        # 追踪哪些节点通过 astream 发出了 token，用于 fallback 判断
        streamed_nodes: set = set()

        try:
            async for event in self.graph.astream_events(initial_state, version="v2"):
                # 记录已发生流式输出的节点
                if (event.get("event") == "on_chat_model_stream"
                        and event.get("metadata", {}).get("langgraph_node", "")
                        in self._STREAMING_NODES):
                    streamed_nodes.add(
                        event["metadata"]["langgraph_node"]
                    )

                translated = self._translate_event(event, show_thinking, streamed_nodes)
                if translated:
                    yield translated

        except Exception as e:
            logger.error(f"临床推理管线异常 | {format_error_log(e)}")
            yield build_error_event(e, talk_id=None)

    # ── /ai/analyze 快速风险评估（独立接口，不走主管线）─────────────────────

    async def analyze_patient_risk_fast(self, patient_data: str) -> Dict[str, str]:
        """
        /ai/analyze 专用：单次快速 LLM 调用，复用 self.llm_critic 实例。
        不使用历史上下文，速度优先。
        """
        prompt = f"""你是资深临床风险评估医生。请基于以下患者信息，快速给出健康风险结论。

    患者信息：{patient_data}

    请直接输出 JSON，不要任何解释、不要 markdown 代码块：

    {{
        "riskLevel": "低风险/中风险/高风险",
        "suggestion": "一句到两句实用干预建议，不要写具体药物剂量",
        "analysisDetails": "简要说明主要风险依据（控制在80字以内）"
    }}

    要求：
    - riskLevel 必须是：低风险、中风险、高风险之一
    - suggestion 简洁、可执行
    - analysisDetails 聚焦关键症状和已知病史，不要给出明确诊断"""

        try:
            response = await self.llm_critic.ainvoke([HumanMessage(content=prompt)])
            result = self._parse_json(getattr(response, "content", ""), {}) or {}
            payload = {
                "riskLevel":       result.get("riskLevel", "中风险"),
                "suggestion":      result.get("suggestion", "建议结合临床检查进一步评估，如有不适及时就医。"),
                "analysisDetails": result.get("analysisDetails", "基于患者提供的信息完成初步风险评估。"),
            }
            # 归一化简写
            normalize = {"高": "高风险", "中": "中风险", "低": "低风险"}
            if payload["riskLevel"] in normalize:
                payload["riskLevel"] = normalize[payload["riskLevel"]]
            logger.info(f"[AIAnalyzeFast] riskLevel={payload['riskLevel']}")
            return payload
        except Exception as e:
            logger.error(f"[AIAnalyzeFast] failed: {e}")
            return {
                "riskLevel":       "中风险",
                "suggestion":      "建议结合线下检查结果进一步评估，如症状加重请及时就医。",
                "analysisDetails": "系统已完成基础风险评估，但详细分析生成失败，请结合临床实际判断。",
            }

    # ── 内部推理方法（供节点调用）────────────────────────────────────────────

    async def _unified_analysis(self, case_text: str, all_info: str) -> Dict[str, Any]:
        """一次 LLM 调用完成病例结构化、子问题生成、关键风险提取。"""
        _DIAGNOSTIC_KW = {"TOAST", "分型", "病因", "定位", "定性", "鉴别", "卒中类型", "发病机制", "卒中原因"}
        _TREATMENT_KW  = {"溶栓", "取栓", "抗凝", "降压", "手术", "用药", "时间窗", "剂量", "治疗方案"}
        _PROGNOSIS_KW  = {"预后", "复发", "康复", "二级预防", "随访", "致残", "死亡率"}

        if any(kw in case_text for kw in _DIAGNOSTIC_KW):
            intent_hint = "诊断/分型方向：重点生成定位、定性、病因分型（TOAST）、鉴别诊断类问题，不生成溶栓/取栓等治疗操作类问题。"
        elif any(kw in case_text for kw in _TREATMENT_KW):
            intent_hint = "治疗决策方向：重点生成治疗方案、禁忌症、时间窗、用药安全性类问题。"
        elif any(kw in case_text for kw in _PROGNOSIS_KW):
            intent_hint = "预后/随访方向：重点生成预后评估、复发风险、二级预防类问题。"
        else:
            intent_hint = "综合分析方向：按临床优先级生成最需查证的问题，优先覆盖诊断，再覆盖治疗。"

        prompt = f"""你是神经急诊专家。请对以下病例完成三项任务，一次性输出。

【病例】
{case_text}

【历史上下文】
{all_info if all_info else "无"}

请直接输出 JSON（不要用 markdown 代码块包裹）：

{{
    "structured_context": {{
        "基本信息": {{"年龄": "", "性别": ""}},
        "起病方式": "",
        "主要症状": [],
        "神经系统查体": {{}},
        "意识水平": "",
        "生命体征": {{}},
        "既往史": [],
        "用药史": [],
        "危险因素": [],
        "非卒中线索": []
    }},
    "complexity": "low/medium/high/critical",
    "key_risks": ["最危险的问题1", "最危险的问题2"],
    "clinical_questions": [
        "服务于用户问题方向的检索子问题1（30字以内）",
        "服务于用户问题方向的检索子问题2",
        "服务于用户问题方向的检索子问题3"
    ],
    "user_questions": [
        "如果输入中包含"请回答以下问题："或类似明确的问题列表，请将每个问题原文提取出来；若没有，则返回空列表"
    ]
}}

要求：
- structured_context: 提取所有临床信息
- complexity: critical=危及生命
- clinical_questions: 【重要】{intent_hint} 问题必须用中文，每条30字以内，用于检索医学文献
- user_questions: 若输入中用户明确提出了若干具体问题（例如以"请回答以下问题："引导的列表），请将每个问题原文提取为字符串数组；若无，则返回空数组。"""

        response = await self.llm_critic.ainvoke([HumanMessage(content=prompt)])
        result = self._parse_json(getattr(response, "content", ""), None)

        if result and isinstance(result, dict):
            result.setdefault("user_questions", [])
            return result

        return {
            "structured_context": {"原始病例": case_text},
            "complexity":         "high",
            "key_risks":          [],
            "clinical_questions": ["该患者当前最紧急的临床问题和处置要点"],
            "user_questions":     [],
        }

    async def _parallel_propose_and_critique(
        self,
        context: Dict,
        evidence: str,
        all_info: str,
        user_questions: List[str],
    ) -> tuple:
        """Proposer 和 Critic 并行推理，最终由 Proposer 集成。"""
        context_str  = json.dumps(context, ensure_ascii=False, indent=2)
        evidence_str = evidence or "未检索到相关证据"
        all_info_str = all_info or "无"

        if user_questions:
            questions_text = "\n".join(f"{i+1}. {q}" for i, q in enumerate(user_questions))
            proposer_prompt = f"""
你是三甲医院神经内科专家。

【患者信息】
{context_str}

【医学证据】
{evidence_str}

用户提出了以下问题：

{questions_text}

请严格遵守：

1 只回答这些问题
2 禁止扩展额外章节
3 禁止提出行动计划
4 禁止输出无关分析

回答格式：

### 问题1
回答

### 问题2
回答
"""
        else:
            proposer_prompt = self._get_prompt(
                "proposer",
                _FALLBACK_PROPOSER,
                context=context_str,
                all_info=all_info_str,
                evidence=evidence_str
            )

        pre_critic_prompt = f"""你是临床质量控制专家和医疗安全审查员。

        请基于以下患者信息和医学证据，预先识别所有潜在的临床风险和容易遗漏的问题。

        【患者信息】
        {context_str}

        【医学证据】
        {evidence_str}

        请从以下角度系统性识别风险：
        1. 容易被忽视的鉴别诊断（非卒中可能）
        2. 气道与呼吸的隐性风险
        3. 时间窗判断的陷阱
        4. 合并症对治疗决策的影响
        5. 可能的治疗禁忌
        6. 致命性遗漏风险

        对每个风险给出严重程度和建议。请精简输出，重突出。

        请额外输出：
        - 当前最可能被忽视但致命的风险（仅1项）
        - 若未处理，最可能导致的后果
        - 建议优先级
        """

        # proposer 为中间推理步骤，结果由 _node_report 二次处理，qwen-plus 足够
        proposer_task = self.llm_critic.ainvoke([
            SystemMessage(content=self.reports.system_role),
            HumanMessage(content=proposer_prompt),
        ])
        critic_task = self.llm_critic.ainvoke([
            SystemMessage(content=self.reports.system_role),
            HumanMessage(content=pre_critic_prompt),
        ])
        logger.info("[propose] 开始等待 asyncio.gather (proposer + critic)...")
        proposer_resp, critic_resp = await asyncio.gather(proposer_task, critic_task)
        logger.info(f"[propose] gather 完成，proposer_len={len(proposer_resp.content)}, critic_len={len(critic_resp.content)}")
        proposal_text = proposer_resp.content
        critic_text   = critic_resp.content

        # user_questions 路径：proposal 已是最终答案，无需集成步骤
        if user_questions:
            return proposal_text, critic_text

        # 标准路径：Proposer 集成初步回答与 Critic 审查意见
        final_prompt = f"""
        你是临床质量审查专家。

        以下是两个内容：

        【初步回答】
        {proposal_text}

        【风险审查意见】
        {critic_text}

        任务：

        1 如果回答存在医学风险或逻辑错误 → 修改
        2 如果回答已经合理 → 保持原结构
        3 仅进行必要修改
        4 保持回答简洁

        输出最终答案。
        """

        logger.info(f"[propose] 开始第三次 ainvoke (integration)，prompt_len={len(final_prompt)}")
        # integration 仅做合并校对，无需 max 级别能力，改用 llm_critic（qwen-plus）降低限流风险
        final_resp = await self.llm_critic.ainvoke([
            SystemMessage(content=self.reports.system_role),
            HumanMessage(content=final_prompt),
        ])
        logger.info(f"[propose] integration 完成，result_len={len(final_resp.content)}")
        return final_resp.content, critic_text
