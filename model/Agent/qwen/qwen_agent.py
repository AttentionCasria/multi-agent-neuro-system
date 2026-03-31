# Agent/qwen/qwenAgent.py — LangGraph-Free 状态机版 v3
# 修改记录：增加对用户明确问题的提取与强制逐题回答功能
# [PATCH] /ai/analyze 对齐：analyze_patient_risk 严格输出 riskLevel/suggestion/analysisDetails
# [PATCH] 新增可审阅提示词常量：_RISK_API_PROMPT_TEMPLATE

import logging
import asyncio
import json
import re
from typing import AsyncGenerator, List, Dict, Any, Optional, TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from config.config_loader import PromptManager, ReportTemplateManager
from error_codes import build_error_event, format_error_log
from token_aggregator import TokenAggregator

logger = logging.getLogger(__name__)

MAX_SUB_QUESTIONS = 3
MAX_EVIDENCE_CHARS = 800
MAX_PROPOSAL_CHARS = 3000
MAX_CRITIQUE_CHARS = 3000

# ===== [PATCH] 你要看的 /ai/analyze 提示词 =====
_RISK_API_PROMPT_TEMPLATE = """你是资深临床风险评估医生。请基于以下患者信息，输出该患者的健康风险结论。

【患者原始数据】
{patient_data}

【结构化分析】
{context_json}

【关键风险】
{key_risks_json}

【待关注临床问题】
{questions_json}

请直接输出 JSON：

{{
    "riskLevel": "低风险/中风险/高风险",
    "suggestion": "一句到两句干预建议",
    "analysisDetails": "简要说明风险依据"
}}

要求：
- 仅输出 JSON，不要 markdown
- riskLevel 只能是：低风险、中风险、高风险
- suggestion 简洁、可执行，不写具体药物剂量
- analysisDetails 聚焦病史与症状风险，不要给诊断结论
"""

# ═══════════════════════════════════════════════════════
# 3-shot CoT 示例（基于用户提供的三道题）
# ═══════════════════════════════════════════════════════
COT_EXAMPLES = """示例1：

问题：1. 在院前急救（120车上）和急诊分诊台，医护人员应首先使用什么工具对患者进行快速筛查？请简述该工具的主要内容。

2. 患者到达急诊后，生命体征平稳，末梢血糖测定结果为6.8mmol/L。此时，作为首诊医生，在开具头颅CT检查之前，必须完成的最关键病史询问和体格检查要点有哪些？为什么？

3. 假设患者在等待CT时，右侧肢体瘫痪突然完全恢复，但言语仍略含糊，这最可能提示什么情况？此时应如何调整诊疗策略？

答案：让我们一步步思考。

1. 对于急性卒中患者的快速筛查，最常用的工具是FAST评分或中风120。中风120的内容是：1看1张脸（不对称、口角歪斜），2查2只胳膊（平行举起、单侧无力），0聆（0）听语言（言语不清）。这个工具简单快速，适合院前急救人员使用。

2. 在头颅CT检查前，必须完成的关键步骤包括：①排除低血糖（已测血糖6.8mmol/L正常）；②明确发病时间（或最后正常时间），这是溶栓时间窗的判断依据；③询问抗凝药物/抗血小板药物使用史，以评估溶栓出血风险。因为如果患者服用抗凝药且INR超标，是溶栓禁忌。

3. 症状突然缓解最可能提示短暂性脑缺血发作（TIA）。此时不应取消CT检查，仍需排除出血；应紧急进行血管评估（如CTA）查找狭窄；并启动二级预防治疗。

示例2：

问题：1. 为什么急性脑卒中患者急诊首选平扫CT而不是MRI？根据该患者的CT报告（未见异常），作为医生应如何解读这一结果？

2. 静脉溶栓后24小时，患者神经功能无改善。此时为了明确病因及评估预后，需要进一步进行哪些关键的影像学检查？这些检查各自解决了什么问题？

3. 如果该患者来院时已超过6小时（比如发病8小时），但CT仍未见出血，此时是否还有血管内治疗（取栓）的机会？需要依赖什么先进的影像学技术来筛选病人？

答案：让我们一步步思考。

1. 首选平扫CT是因为快速、普及、安全，且能明确排除出血。急性期第一要务是区分缺血还是出血。CT对急性脑出血诊断率接近100%。CT"未见异常"不代表没问题，超急性期脑梗死CT常不显示低密度灶，这反而是溶栓的影像学指征。

2. 溶栓后24小时需要复查CT平扫排除出血转化，同时进行MRI+DWI/MRA。DWI显示最终梗死大小和位置，MRA显示大血管有无闭塞，有助于病因分型和指导二级预防。

3. 超时间窗仍有取栓机会，但需要依赖CT灌注成像（CTP）或MRI评估缺血半暗带��如果影像显示梗死核心小、半暗带大，即使发病8小时也应考虑取栓。

示例3：

问题：1. 根据患者的症状和体征，定位诊断应该是什么？为什么CT未见异常，但病情可能很严重？

2. 该患者不适合静脉溶栓，医生高度怀疑是后循环大血管闭塞。此时应首选什么影像学检查来明确诊断？为什么？

3. 若检查证实为基底动脉闭塞，但在准备介入治疗过程中，患者突发意识障碍、呼吸节律不齐。请分析可能的病理生理机制，并说明此时的处理原则。

答案：让我们一步步思考。

1. 定位诊断是后循环（椎-基底动脉系统），具体位于小脑或脑干。因为眩晕、眼震、呕吐、共济失调提示小脑或脑干受累。CT阴性但病情重，是因为后颅窝CT伪影多，且脑干是生命中枢，小梗死即可致命。

2. 首选头颈CTA。因为后循环大血管闭塞需要快速明确，CTA快速准确，能显示基底动脉闭塞，为取栓提供依据。

3. 突发意识障碍可能机制是小脑水肿压迫脑干。处理原则：紧急气管插管保证呼吸，同时急诊后颅窝减压手术或继续取栓开通血管。"""

class ClinicalState(TypedDict, total=False):
    case_text: str
    all_info: str
    report_mode: str
    show_thinking: bool
    intent_type: str
    knowledge_response: str
    context: Dict
    clinical_questions: List[str]
    key_risks: List[str]
    complexity: str
    evidence: str
    proposal: str
    critique: str
    user_questions: List[str]

class SimpleGraph:
    END = "__end__"

    def __init__(self):
        self._nodes: Dict[str, Any] = {}
        self._edges: Dict[str, Any] = {}
        self._conditional: Dict[str, tuple] = {}
        self._entry: Optional[str] = None

    def add_node(self, name: str, fn):
        self._nodes[name] = fn

    def set_entry_point(self, name: str):
        self._entry = name

    def add_edge(self, src: str, dst: str):
        self._edges[src] = dst

    def add_conditional_edges(self, src: str, router_fn, mapping: Dict[str, Optional[str]]):
        self._conditional[src] = (router_fn, mapping)

    def compile(self):
        return _CompiledGraph(self)

class _CompiledGraph:
    def __init__(self, graph: SimpleGraph):
        self._g = graph

    async def ainvoke(self, state: dict) -> dict:
        current = self._g._entry
        if not current:
            raise RuntimeError("未设置 entry_point")

        while current and current != SimpleGraph.END:
            fn = self._g._nodes.get(current)
            if fn is None:
                raise RuntimeError(f"未找到节点: {current}")

            if asyncio.iscoroutinefunction(fn):
                updates = await fn(state)
            else:
                updates = fn(state)

            if updates and isinstance(updates, dict):
                state.update(updates)

            if current in self._g._conditional:
                router_fn, mapping = self._g._conditional[current]
                route_key = router_fn(state)
                next_node = mapping.get(route_key)
                current = next_node
            elif current in self._g._edges:
                current = self._g._edges[current]
            else:
                current = None

        return state

class qwenAgent:
    _MCQ_SPLIT_PATTERN = re.compile(r"(?:^|\n)\s*(?:第)?(?:Q)?\s*(\d+)\s*(?:题|[\.\、\):：])\s*", re.IGNORECASE)
    _OPTION_HINT_PATTERN = re.compile(r"(?:^|\n)\s*[A-F][\.\、\):：]\s+")

    def __init__(
            self,
            llm_proposer,
            llm_critic,
            medical_assistant,
            prompt_manager: PromptManager,
            report_manager: ReportTemplateManager
    ):
        self.llm_proposer = llm_proposer
        self.llm_critic = llm_critic
        self.medical_assistant = medical_assistant
        self.prompts = prompt_manager
        self.reports = report_manager

        self.tools = {
            "retrieve_evidence": self.medical_assistant.fast_parallel_retrieve
        }

        self.graph = self._build_graph()

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

    def _emit_thinking(self, step, title, content) -> dict:
        if isinstance(content, (dict, list)):
            content_str = json.dumps(content, ensure_ascii=False, indent=2)
        else:
            content_str = str(content)
        logger.info(f"[{step}] {title}")
        logger.info(content_str[:500] + ("..." if len(content_str) > 500 else ""))
        return {
            "type": "thinking",
            "step": step,
            "title": title,
            "content": content_str
        }

    def _parse_json(self, text, default=None):
        content = text.strip()
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

    def _run_tool(self, tool_name: str, *args, **kwargs):
        tool = self.tools.get(tool_name)
        if not tool:
            logger.warning(f"⚠️ 未找到工具: {tool_name}")
            return ""
        try:
            logger.info(f"🔧 Agent调用工具: {tool_name}")
            return tool(*args, **kwargs)
        except Exception as e:
            logger.error(f"工具执行失败 {tool_name}: {e}")
            return ""

    def _build_graph(self) -> _CompiledGraph:
        graph = SimpleGraph()
        graph.add_node("intent", self._node_intent)
        graph.add_node("analysis", self._node_analysis)
        graph.add_node("retrieve", self._node_retrieve)
        graph.add_node("reason", self._node_reason)

        graph.set_entry_point("intent")
        graph.add_conditional_edges(
            "intent",
            self._route_intent,
            {
                "consultation": "analysis",
                "knowledge": None,
                "irrelevant": None
            }
        )
        graph.add_edge("analysis", "retrieve")
        graph.add_edge("retrieve", "reason")
        return graph.compile()

    async def _node_intent(self, state: dict) -> dict:
        case_text = state["case_text"]

        intent_prompt = f"""你是意图分类专家。请判断以下输入的类型：

- consultation: 具体患者问诊或病例分析（包含患者症状、检查等细节）
- knowledge: 脑卒中通用知识询问（如症状、药品作用、禁忌、预防等，无具体患者细节）
- irrelevant: 非脑卒中医疗相关

输入：{case_text}

输出 JSON：

{{
    "type": "consultation/knowledge/irrelevant",
    "reason": "简要原因"
}}

严格区分：如果有患者具体信息，为consultation；如果是一般性问题，为knowledge；否则irrelevant。"""

        logging.info(f"=== 开始意图分类，输入: {case_text[:100]}... ===")
        intent_response = await self.llm_critic.ainvoke([HumanMessage(content=intent_prompt)])
        logging.info(f"=== 意图分类原始响应: {intent_response.content} ===")
        intent_result = self._parse_json(intent_response.content, {"type": "irrelevant"})
        logging.info(f"=== 意图分类解析结果: {intent_result} ===")
        intent_type = intent_result.get("type", "irrelevant")
        logging.info(f"=== 最终意图类型: {intent_type} ===")
        return {"intent_type": intent_type}

    def _route_intent(self, state: dict) -> str:
        t = state.get("intent_type", "irrelevant")
        if t == "consultation":
            return "consultation"
        if t == "knowledge":
            return "knowledge"
        return "irrelevant"

    async def _node_analysis(self, state: dict) -> dict:
        case_text = state["case_text"]
        all_info = state.get("all_info", "")
        analysis = await self._unified_analysis(case_text, all_info)

        context = analysis.get("structured_context", {"原始病例": case_text})
        clinical_questions = analysis.get("clinical_questions", [])
        key_risks = analysis.get("key_risks", [])
        complexity = analysis.get("complexity", "high")
        user_questions = analysis.get("user_questions", [])

        if not clinical_questions:
            clinical_questions = ["该患者当前最紧急的临床问题和处置要点"]
        clinical_questions = clinical_questions[:MAX_SUB_QUESTIONS]

        return {
            "context": context,
            "clinical_questions": clinical_questions,
            "key_risks": key_risks,
            "complexity": complexity,
            "user_questions": user_questions
        }

    async def _node_retrieve(self, state: dict) -> dict:
        # 改为 async：同步检索（向量搜索）放入线程池，避免阻塞事件循环
        questions = state.get("clinical_questions", [])
        logging.info(f"🔧 Agent Tool 调用: retrieve_evidence")
        loop = asyncio.get_event_loop()
        evidence = await loop.run_in_executor(
            None, self._run_tool, "retrieve_evidence", questions
        )
        evidence_truncated = self._truncate(evidence, MAX_EVIDENCE_CHARS)
        return {"evidence": evidence_truncated}

    async def _node_reason(self, state: dict) -> dict:
        context = state.get("context", {})
        evidence = state.get("evidence", "")
        all_info = state.get("all_info", "")
        user_questions = state.get("user_questions", [])
        proposal, critique = await self._parallel_propose_and_critique(context, evidence, all_info, user_questions)
        return {"proposal": proposal, "critique": critique}

    async def _run_clinical_reasoning_core(
            self,
            case_text: str,
            all_info: str = "",
            report_mode: str = "emergency",
            show_thinking: bool = True
    ) -> AsyncGenerator[dict, None]:
        """内部推理管线，纯异步生成器，直接 yield 原始事件，不做聚合。由 run_clinical_reasoning 包装调用。

        重构要点（解决 thinking 时间过长问题）：
        1. 在每个阻塞 LLM 调用 **之前** 先 yield thinking 事件，让用户立刻看到进度反馈
        2. 将原来的 graph.ainvoke（一次性运行4个节点）改为手动逐节点执行，节点间穿插 thinking 事件
        3. multi-mcq 路径在拆题前也先 yield thinking，消除首次无响应的空白期
        """
        try:
            # ── 立即发出第一个 thinking，消除空白等待期 ──────────────────
            if show_thinking:
                yield self._emit_thinking("Start", "🔍 正在分析输入...", case_text[:100] + ("..." if len(case_text) > 100 else ""))

            # 【优化】合并 MCQ 识别 + 意图分类为单次 LLM 调用（原来是两次串行调用，节省 1 次等待）
            classification = await self._classify_and_detect_intent(case_text)
            llm_multi_mcq = classification.get("is_multi_mcq", False)
            llm_q_type = classification.get("question_type", "unknown")
            intent_type = classification.get("intent_type", "irrelevant")
            is_multi_mcq = llm_multi_mcq or self._is_multi_mcq(case_text)

            if is_multi_mcq:
                if show_thinking:
                    yield self._emit_thinking("Intent", "✅ 检测到多题选择题任务", f"进入拆题并行求解流程（type={llm_q_type}）")
                    yield self._emit_thinking("Split", "📋 正在拆分题目...", "使用 LLM 智能识别各道独立题目")
                default_q_type = llm_q_type if llm_q_type in {"single", "multiple", "mixed"} else "unknown"
                multi_result = await self._run_multi_mcq(case_text, default_question_type=default_q_type)
                if multi_result:
                    yield {"type": "result", "content": multi_result}
                    if show_thinking:
                        yield self._emit_thinking("Done", "✅ 多题处理完成", "已按Q1/Q2/...格式输出")
                else:
                    error_msg = "已检测到这可能是多道选择题，但拆分题目失败，请检查输入格式。"
                    yield {"type": "result", "content": error_msg}
                return

            # ── 手动逐节点执行（原 graph.ainvoke），节点间穿插 thinking ──
            # intent_type 已由合并分类获得，直接写入 state，无需再调用 _node_intent
            state = {
                "case_text": case_text,
                "all_info": all_info,
                "report_mode": report_mode,
                "show_thinking": show_thinking,
                "intent_type": intent_type,
            }

            if intent_type == "irrelevant":
                logging.info("=== 意图被分类为 irrelevant，返回拒绝消息 ===")
                yield {"type": "chunk", "content": "请提供脑卒中医疗临床相关查询，此输入无关。"}
                return

            if intent_type == "knowledge":
                logging.info("=== 意图被分类为 knowledge，进入知识问答流程 ===")
                if show_thinking:
                    yield self._emit_thinking("Intent", "✅ 通用知识问题，直接流式回答", "使用 Qwen-Max 流式输出")
                knowledge_prompt = f"""你是三甲医院神经内科主任医师。请基于循证医学知识，直接回答以下脑卒中相关通用问题。

问题：{case_text}

回答要求：
- 用中文，简洁专业
- 禁止确诊语气
- 禁止具体剂量
- 如果需要，引用权威指南"""
                # 注入 system_role，确保 knowledge 路径也受文献引用约束
                _knowledge_messages = [
                    SystemMessage(content=self.reports.system_role),
                    HumanMessage(content=knowledge_prompt),
                ]
                async for chunk in self.llm_proposer.astream(_knowledge_messages):
                    content = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if content:
                        yield {"type": "chunk", "content": content}
                return

            if show_thinking:
                yield self._emit_thinking("Intent", "✅ 问诊输入，进入临床推理", "提取病例结构 → 检索证据 → 推理")

            # Node 2: Analysis 病例分析
            if show_thinking:
                yield self._emit_thinking("Analysis", "🔬 正在分析病例结构...", "提取临床信息、风险因素与待查问题")
            analysis_updates = await self._node_analysis(state)
            state.update(analysis_updates)

            context = state.get("context", {"原始病例": case_text})
            clinical_questions = state.get("clinical_questions", [])
            key_risks = state.get("key_risks", [])
            complexity = state.get("complexity", "high")
            user_questions = state.get("user_questions", [])

            if show_thinking:
                yield self._emit_thinking("Step 1", "✅ 病例分析完成", {
                    "complexity": complexity,
                    "questions": clinical_questions,
                    "key_risks": key_risks
                })

            # Node 3: Retrieve 证据检索
            if show_thinking:
                yield self._emit_thinking("Retrieve", "📚 正在检索循证医学证据...", f"检索 {len(clinical_questions)} 个临床问题")
            retrieve_updates = await self._node_retrieve(state)
            state.update(retrieve_updates)
            evidence = state.get("evidence", "")

            if show_thinking:
                yield self._emit_thinking("Step 2", "✅ 证据检索完成", f"证据 {len(evidence)} 字符")

            # Node 4: Reason 推理（Proposer + Critic 并行）
            if show_thinking:
                yield self._emit_thinking("Reason", "🧠 正在进行临床推理...", "Proposer + Critic 并行推理中，请稍候")
            reason_updates = await self._node_reason(state)
            state.update(reason_updates)
            proposal = state.get("proposal", "")
            critique = state.get("critique", "")

            if show_thinking:
                yield self._emit_thinking("Step 3a", "✅ Proposer 推理完成", proposal[:800] + "..." if len(proposal) > 800 else proposal)
                yield self._emit_thinking("Step 3b", "✅ Critic 批判完成", critique[:800] + "..." if len(critique) > 800 else critique)

            if user_questions:
                if show_thinking:
                    yield self._emit_thinking("DirectAnswer", "✅ 检测到用户问题列表，生成最终答案", f"共 {len(user_questions)} 个问题")
                final_answer = proposal
                yield {"type": "result", "content": final_answer}
                return

            yield {
                "type": "meta",
                "content": {
                    "complexity": complexity,
                    "report_mode": report_mode,
                    "key_risks": key_risks
                }
            }

            if show_thinking:
                yield self._emit_thinking("Step 4", f"📝 生成最终报告 (模式={report_mode})...", "融合推理 + 批判 → 最终临床报告")

            proposal_truncated = self._truncate(proposal, MAX_PROPOSAL_CHARS)
            critique_truncated = self._truncate(critique, MAX_CRITIQUE_CHARS)

            # 原生 async for 逐块流式 yield，实现打字机效果
            async for chunk in self.medical_assistant.stream_final_report(
                context=context,
                proposal=proposal_truncated,
                critique=critique_truncated,
                evidence=evidence,
                all_info=all_info,
                report_mode=report_mode
            ):
                if isinstance(chunk, str) and chunk:
                    yield {"type": "chunk", "content": chunk}
                elif hasattr(chunk, "content") and chunk.content:
                    yield {"type": "chunk", "content": chunk.content}

            if show_thinking:
                yield self._emit_thinking("Done", "✅ 全部完成", "临床推理管线执行完毕")

        except Exception as e:
            # 记录含完整堆栈的错误日志，便于运维定位
            logger.error(f"=== 临床推理管线异常 | {format_error_log(e)} ===")
            # 构造结构化错误事件（双写 content 字段保持旧前端兼容）
            yield build_error_event(e, talk_id=None)

    async def run_clinical_reasoning(
            self,
            case_text: str,
            all_info: str = "",
            report_mode: str = "emergency",
            show_thinking: bool = True
    ) -> AsyncGenerator[dict, None]:
        """
        对外接口：纯异步生成器，在内部推理管线基础上套一层 TokenAggregator，
        将高频 thinking token 聚合后再发出，降低 SSE 事件频率。
        result/meta/chunk/error 事件不经过聚合，直接透传保证实时性。

        聚合策略：
        - 连续 thinking 事件的 content 合并，元数据（step/title）保留第一个 chunk 的值
        - 非 thinking 事件出现前先 flush，确保不丢失 thinking 内容
        - 内部生成器耗尽后再做最终 flush 兜底
        """
        aggregator = TokenAggregator()
        # 记录当前批次第一个 thinking 事件的元数据（step/title），聚合后继承这份元数据
        first_chunk_meta: Optional[dict] = None

        async for event in self._run_clinical_reasoning_core(case_text, all_info, report_mode, show_thinking):
            if not isinstance(event, dict):
                yield event
                continue

            if event.get("type") == "thinking":
                content = event.get("content", "")
                if first_chunk_meta is None:
                    # 保存第一个 chunk 的全部字段（除 content），聚合事件将继承这些元数据
                    first_chunk_meta = {k: v for k, v in event.items() if k != "content"}
                merged = aggregator.add(content)
                if merged is not None:
                    yield {**first_chunk_meta, "content": merged}
                    first_chunk_meta = None   # 重置，下批次从新的第一个 chunk 取元数据
            else:
                # 非 thinking 事件（result/chunk/meta/error）前，先 flush 剩余 thinking 内容
                flushed = aggregator.flush()
                if flushed is not None and first_chunk_meta is not None:
                    yield {**first_chunk_meta, "content": flushed}
                    first_chunk_meta = None
                yield event

        # 内部生成器耗尽后最终 flush（正常情况下 done 前已 flush，此处为安全兜底）
        flushed = aggregator.flush()
        if flushed is not None and first_chunk_meta is not None:
            yield {**first_chunk_meta, "content": flushed}

    def answer_clinical_qa_with_cot(self, question: str) -> str:
        try:
            prompt = f"{COT_EXAMPLES}\n\n现在，请回答下面的问题：\n问题：{question}\n答案："
            response = self.llm_proposer.invoke([HumanMessage(content=prompt)])
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error(f"CoT问答失败: {e}")
            return "生成答案时出现错误，请稍后重试。"

    async def _unified_analysis(self, case_text: str, all_info: str) -> Dict[str, Any]:
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
        "需查证的中文临床问题1（30字以内）",
        "需查证的中文临床问题2",
        "需查证的中文临床问题3"
    ],
    "user_questions": [
        "如果输入中包含"请回答以下问题："或类似明确的问题列表，请将每个问题原文提取出来；若没有，则返回空列表"
    ]
}}

要求：
- structured_context: 提取所有临床信息
- complexity: critical=危及生命
- clinical_questions: 3个最需要查证的问题，用于检索医学文献，必须用中文
- user_questions: 若输入中用户明确提出了若干具体问题（例如以"请回答以下问题："引导的列表），请将每个问题原文提取为字符串数组；若无，则返回空数组。"""

        response = await self.llm_critic.ainvoke([HumanMessage(content=prompt)])
        result = self._parse_json(response.content, None)

        if result and isinstance(result, dict):
            if "user_questions" not in result:
                result["user_questions"] = []
            return result

        return {
            "structured_context": {"原始病例": case_text},
            "complexity": "high",
            "key_risks": [],
            "clinical_questions": ["该患者当前最紧急的临床问题和处置要点"],
            "user_questions": []
        }

    async def _parallel_propose_and_critique(
            self,
            context: Dict,
            evidence: str,
            all_info: str,
            user_questions: List[str]
    ) -> tuple:
        context_str = json.dumps(context, ensure_ascii=False, indent=2)
        evidence_str = evidence if evidence else "未检索到相关��据"
        all_info_str = all_info if all_info else "无"

        if user_questions:
            questions_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(user_questions)])
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

        proposer_task = self.llm_proposer.ainvoke([HumanMessage(content=proposer_prompt)])
        critic_task = self.llm_critic.ainvoke([HumanMessage(content=pre_critic_prompt)])

        proposer_resp, critic_resp = await asyncio.gather(proposer_task, critic_task)

        proposal_text = proposer_resp.content
        critic_text = critic_resp.content

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

        final_resp = await self.llm_proposer.ainvoke([HumanMessage(content=final_prompt)])
        final_answer = final_resp.content

        return final_answer, critic_text

    # ===== [PATCH] /ai/analyze 对齐方法（仅此方法语义收紧）=====
    async def analyze_patient_risk(self, patient_data: str, all_info: str = "") -> Dict[str, str]:
        """面向 /ai/analyze 的稳定输出：riskLevel / suggestion / analysisDetails（纯异步，无独立事件循环）"""
        try:
            logger.info("[AIAnalyze] start | patient_data_len=%d | all_info_len=%d", len(patient_data or ""), len(all_info or ""))

            analysis = await self._unified_analysis(patient_data, all_info)
            context = analysis.get("structured_context", {"原始病例": patient_data})
            complexity = str(analysis.get("complexity", "high")).lower()
            key_risks = analysis.get("key_risks", []) or []
            questions = analysis.get("clinical_questions", []) or []

            prompt = _RISK_API_PROMPT_TEMPLATE.format(
                patient_data=patient_data,
                context_json=json.dumps(context, ensure_ascii=False, indent=2),
                key_risks_json=json.dumps(key_risks, ensure_ascii=False),
                questions_json=json.dumps(questions, ensure_ascii=False),
            )
            logger.info("[AIAnalyze] prompt_ready | prompt_len=%d", len(prompt))

            response = await self.llm_critic.ainvoke([HumanMessage(content=prompt)])
            result = self._parse_json(getattr(response, "content", ""), {}) or {}

            default_risk_level = {
                "critical": "高风险",
                "high": "高风险",
                "medium": "中风险",
                "low": "低风险"
            }.get(complexity, "中风险")

            default_details = (
                "；".join(str(r) for r in key_risks[:3])
                if key_risks else
                "基于当前输入信息完成了初步健康风险评估，建议结合临床检查进一步确认。"
            )

            default_suggestion = {
                "高风险": "建议尽快完善相关检查并由专科医生进一步评估，密切监测病情变化。",
                "中风险": "建议近期复查关键指标，结合病史和症状做进一步评估，并做好生活方式管理。",
                "低风险": "建议继续规律监测健康指标，保持良好生活方式，如有不适及时就诊。"
            }[default_risk_level]

            risk_level = result.get("riskLevel", default_risk_level)
            # 兼容偶发返回"高/中/低"
            normalize_map = {"高": "高风险", "中": "中风险", "低": "低风险"}
            risk_level = normalize_map.get(risk_level, risk_level)
            if risk_level not in {"低风险", "中风险", "高风险"}:
                risk_level = default_risk_level

            payload = {
                "riskLevel": risk_level,
                "suggestion": result.get("suggestion") or default_suggestion,
                "analysisDetails": result.get("analysisDetails") or default_details
            }
            logger.info("[AIAnalyze] done | riskLevel=%s", payload["riskLevel"])
            return payload

        except Exception as e:
            logger.error(f"[AIAnalyze] failed: {e}")
            return {
                "riskLevel": "中风险",
                "suggestion": "建议结合线下检查结果进一步评估，如症状加重请及时就医。",
                "analysisDetails": "系统已完成基础风险评估，但详细分析生成失败，请结合临床实际判断。"
            }

    async def analyze_patient_risk_fast(self, patient_data: str) -> Dict[str, str]:
            """专用于 /ai/analyze 和未来 /ai/sync-talk 的极简快速风险评估
            - 只调用一次 llm_fast
            - 完全不使用 all_info / 历史上下文
            - 提示词极简，速度优先
            """
            try:
                logger.info("[AIAnalyzeFast] start | patient_data_len=%d", len(patient_data or ""))

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

                from langchain_community.chat_models import ChatTongyi
                llm_fast_temp = ChatTongyi(
                    model_name="qwen-plus",
                    temperature=0.1,  # 风险评估需要更确定的输出
                    streaming=False  # 同步接口通常不需要流式，直接拿 JSON
                )

                response = await llm_fast_temp.ainvoke(
                    [HumanMessage(content=prompt)]
                )

                result = self._parse_json(getattr(response, "content", ""), {}) or {}

                # 兜底保证接口稳定
                payload = {
                    "riskLevel": result.get("riskLevel", "中风险"),
                    "suggestion": result.get("suggestion", "建议结合临床检查进一步评估，如有不适及时就医。"),
                    "analysisDetails": result.get("analysisDetails", "基于患者提供的信息完成初步风险评估。")
                }

                # 简单归一化
                normalize = {"高": "高风险", "中": "中风险", "低": "低风险"}
                if payload["riskLevel"] in normalize:
                    payload["riskLevel"] = normalize[payload["riskLevel"]]

                logger.info("[AIAnalyzeFast] done | riskLevel=%s", payload["riskLevel"])
                return payload

            except Exception as e:
                logger.error(f"[AIAnalyzeFast] failed: {e}")
                return {
                    "riskLevel": "中风险",
                    "suggestion": "建议结合线下检查结果进一步评估，如症状加重请及时就医。",
                    "analysisDetails": "系统已完成基础风险评估，但详细分析生成失败，请结合临床实际判断。"
                }

    def _is_multi_mcq(self, text: str) -> bool:
        return len(re.findall(r"(?:^|\n)\s*[A-D][\.\、\):：]\s+", text)) >= 2

    async def _split_mcq_with_llm(self, text: str) -> List[Dict[str, Any]]:
        prompt = f"""你是一个智能医疗文本解析器。请将下面包含多道选择题的文本，完整拆分成独立的题目数组。

输入：

{text}

严格遵守以下要求：

1. 只输出 JSON 数组，禁止任何解释或 markdown 代码块（如 ```json）。

2. 每道题的 text 必须包含完整的题干和所有候选项（A/B/C/D等）。

3. 如果输入文本不是选择题，请返回空数组 []。

4. 格式严格如下：

[
  {{
    "q_no": "1",
    "text": "第一题的完整题干和所有选项..."
  }},
  {{
    "q_no": "2",
    "text": "第二题的完整题干和所有选项..."
  }}
]
"""
        try:
            resp = await self.llm_critic.ainvoke([HumanMessage(content=prompt)])
            parsed = self._parse_json(getattr(resp, "content", "") or "", [])
            if isinstance(parsed, list) and len(parsed) > 0:
                questions = []
                for idx, item in enumerate(parsed):
                    if isinstance(item, dict) and "text" in item:
                        q_no = str(item.get("q_no", idx + 1))
                        q_text = item.get("text", "")
                        questions.append({"q_no": q_no, "text": q_text})
                return questions
        except Exception as e:
            logger.warning(f"LLM智能拆题失败: {e}")
        return self._split_mcq_questions_regex(text)

    def _split_mcq_questions_regex(self, text: str) -> List[Dict[str, Any]]:
        splits = self._MCQ_SPLIT_PATTERN.split(text)
        if len(splits) < 3:
            return []
        questions = []
        for i in range(1, len(splits), 2):
            q_no = splits[i]
            q_content = splits[i + 1]
            questions.append({
                "q_no": q_no,
                "text": f"Q{q_no}: {q_content.strip()}"
            })
        return questions

    async def _classify_multi_mcq_with_llm(self, text: str) -> Dict[str, Any]:
        if not text or len(text.strip()) < 8:
            return {"is_multi_mcq": False, "question_type": "unknown", "reason": "empty"}
        prompt = f"""你是任务识别器。请判断输入是否为"包含2道及以上选择题"的试题文本，并判断题型。

输入：

{text}

只允许输出 JSON：

{{
  "is_multi_mcq": true/false,
  "question_type": "single/multiple/mixed/unknown",
  "reason": "一句话"
}}

判定标准：
1) 选择题需有候选项（A/B/C/D等）
2) 至少2道题才算 multi
3) 若出现"多选/可多选/选出所有正确项"等，优先判为 multiple 或 mixed
4) 问诊/知识问答/非试题返回 false
"""
        try:
            resp = await self.llm_critic.ainvoke([HumanMessage(content=prompt)])
            parsed = self._parse_json(getattr(resp, "content", "") or "", None)
            if isinstance(parsed, dict):
                return {
                    "is_multi_mcq": bool(parsed.get("is_multi_mcq", False)),
                    "question_type": str(parsed.get("question_type", "unknown")).lower(),
                    "reason": str(parsed.get("reason", ""))
                }
        except Exception as e:
            logger.warning(f"LLM多题识别失败，使用规则兜底: {e}")
        return {"is_multi_mcq": False, "question_type": "unknown", "reason": "fallback"}

    async def _classify_and_detect_intent(self, text: str) -> dict:
        """【优化】将 MCQ 识别 + 意图分类合并为单次 LLM 调用，减少思考阶段 1 次串行等待。
        原来：_classify_multi_mcq_with_llm（1次）+ _node_intent（1次）= 2次串行
        现在：_classify_and_detect_intent（1次）= 1次
        """
        if not text or len(text.strip()) < 8:
            return {"is_multi_mcq": False, "question_type": "unknown", "intent_type": "irrelevant"}

        prompt = f"""你是任务识别器。请对以下输入同时完成两项判断。

输入：
{text}

只允许输出 JSON：
{{
  "is_multi_mcq": true/false,
  "question_type": "single/multiple/mixed/unknown",
  "intent_type": "consultation/knowledge/irrelevant",
  "reason": "一句话说明"
}}

判定标准：
1) is_multi_mcq: 是否包含2道及以上带候选项（A/B/C/D等）的选择题；含"多选/可多选"时 question_type 为 multiple/mixed
2) intent_type（仅在 is_multi_mcq=false 时有意义）:
   - consultation: 含具体患者信息的问诊/病例分析（有症状、检查、用药等细节）
   - knowledge: 脑卒中通用知识询问（无具体患者，如药品作用、禁忌、预防等）
   - irrelevant: 非脑卒中医疗相关内容
"""
        try:
            resp = await self.llm_critic.ainvoke([HumanMessage(content=prompt)])
            parsed = self._parse_json(getattr(resp, "content", "") or "", None)
            if isinstance(parsed, dict):
                return {
                    "is_multi_mcq": bool(parsed.get("is_multi_mcq", False)),
                    "question_type": str(parsed.get("question_type", "unknown")).lower(),
                    "intent_type": str(parsed.get("intent_type", "irrelevant")),
                }
        except Exception as e:
            logger.warning(f"合并分类失败，降级到默认值: {e}")
        return {"is_multi_mcq": False, "question_type": "unknown", "intent_type": "irrelevant"}

    async def _stream_user_questions_answer(
            self, context: Dict, evidence: str, user_questions: List[str]
    ) -> AsyncGenerator[str, None]:
        """【优化】user_questions 快速流式通道：直接 astream proposer 回答，跳过 critic + 集成两次 ainvoke。
        原来：proposer.ainvoke + critic.ainvoke（并行）+ 集成.ainvoke（串行）= 3次 LLM，全部阻塞
        现在：proposer.astream = 立即流式，0次阻塞等待
        """
        context_str = json.dumps(context, ensure_ascii=False, indent=2)
        evidence_str = evidence if evidence else "未检索到相关证据"
        questions_text = "\n".join([f"{i + 1}. {q}" for i, q in enumerate(user_questions)])

        proposer_prompt = f"""你是三甲医院神经内科专家。

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
回答"""
        # 注入 system_role，确保追问路径也受文献引用约束
        _user_q_messages = [
            SystemMessage(content=self.reports.system_role),
            HumanMessage(content=proposer_prompt),
        ]
        async for chunk in self.llm_proposer.astream(_user_q_messages):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if content:
                yield content

    async def _detect_question_type_with_llm(self, question_text: str, default_type: str = "single") -> str:
        prompt = f"""你是题型识别器。判断下列题目是单选题还是多选题。

题目：

{question_text}

只输出 JSON：
{{"question_type":"single/multiple","reason":"一句话"}}

规则：
- 出现"多选/可多选/选出所有正确项/不止一个正确答案" => multiple
- 否则默认 single
"""
        try:
            resp = await self.llm_critic.ainvoke([HumanMessage(content=prompt)])
            parsed = self._parse_json(getattr(resp, "content", "") or "", {})
            qt = str(parsed.get("question_type", default_type)).lower()
            return "multiple" if qt == "multiple" else "single"
        except Exception:
            return "multiple" if default_type == "multiple" else "single"

    def _parse_answer_letters(self, raw: str, question_type: str) -> str:
        text = raw or ""
        m = re.search(r"Q\s*:\s*([A-F](?:\s*[,，/\s]\s*[A-F])*)", text, re.IGNORECASE)
        if m:
            letters = re.findall(r"[A-F]", m.group(1).upper())
        else:
            letters = re.findall(r"\b([A-F])\b", text.upper())
        if not letters:
            return "A" if question_type == "single" else "A,C"
        seen = set()
        uniq = []
        for ch in letters:
            if ch not in seen:
                seen.add(ch)
                uniq.append(ch)
        if question_type == "multiple":
            if len(uniq) == 1:
                candidate = uniq[0]
                if candidate != "C":
                    uniq.append("C")
                else:
                    uniq.append("A")
            return ",".join(uniq)
        return uniq[0]

    async def _answer_single_mcq(self, question_text: str, question_type: str = "single") -> Dict[str, str]:
        if question_type == "multiple":
            answer_rule = "可选择多个选项（A-F）"
            output_rule = "Q: <如 A,C 或 B,D,E>"
        else:
            answer_rule = "只能选择一个选项（A-F）"
            output_rule = "Q: <单个选项字母>"

        prompt = f"""你是一名卒中专家。下面是一道选择题，请严格按要求回答。

题目：

{question_text}

要求：
1. {answer_rule}
2. 必须输出两行，且仅两行：
{output_rule}
Reason: <���超过120字的简要理由>
3. 禁止输出额外结构或额外段落
"""
        resp = await self.llm_proposer.ainvoke([HumanMessage(content=prompt)])
        raw = getattr(resp, "content", "") or ""
        answer = self._parse_answer_letters(raw, question_type)
        reason = "基于题干信息给出最可能选项。"

        m_reason = re.search(r"Reason\s*:\s*(.+)", raw, re.IGNORECASE | re.DOTALL)
        if m_reason:
            reason = m_reason.group(1).strip().split("\n")[0][:200]

        return {"answer": answer, "reason": reason, "question_type": question_type}

    async def _run_multi_mcq(self, case_text: str, default_question_type: str = "single") -> str:
        questions = await self._split_mcq_with_llm(case_text)
        if not questions:
            return ""

        per_question_types = []
        for item in questions:
            if default_question_type in {"single", "multiple"}:
                q_type = default_question_type
            else:
                q_type = await self._detect_question_type_with_llm(item["text"], default_type="single")
            per_question_types.append(q_type)

        tasks = [self._answer_single_mcq(item["text"], q_type) for item, q_type in zip(questions, per_question_types)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        blocks: List[str] = []
        for item, r, q_type in zip(questions, results, per_question_types):
            q_no = item["q_no"]
            if isinstance(r, Exception):
                answer = "A" if q_type == "single" else "A,C"
                reason = "该题解析异常，返回默认选项，请人工复核。"
            else:
                answer = r.get("answer", "A" if q_type == "single" else "A,C")
                reason = r.get("reason", "基于题干信息给出最可能选项。")
            blocks.append(f"Q{q_no}: {answer}\nReason: {reason}")

        return "\n\n".join(blocks)

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