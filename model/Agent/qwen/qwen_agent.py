# Agent/qwen/qwenAgent.py — LangGraph-Free 状态机版 v3
# 修改记录：增加对用户明确问题的提取与强制逐题回答功能

import logging
import asyncio
import json
import re
from typing import Generator, List, Dict, Any, Optional, TypedDict
from langchain_core.messages import HumanMessage, SystemMessage
from config.config_loader import PromptManager, ReportTemplateManager

logger = logging.getLogger(__name__)

MAX_SUB_QUESTIONS = 3
MAX_EVIDENCE_CHARS = 800
MAX_PROPOSAL_CHARS = 3000
MAX_CRITIQUE_CHARS = 3000

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

1. 首选平扫CT是因为快速、普及、安全，且能明确排除出血。急性期第一要务是区分缺血还是出血。CT对急性脑出血诊断率接近100%。CT“未见异常”不代表没问题，超急性期脑梗死CT常不显示低密度灶，这反而是溶栓的影像学指征。

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

# ═══════════════════════════════════════════════════════
# 轻量状态机（替代 LangGraph，零依赖）
# ═══════════════════════════════════════════════════════
class ClinicalState(TypedDict, total=False):
    """图状态定义：所有节点共享的数据"""
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
    user_questions: List[str]   # [MODIFIED] 新增字段，存储用户明确提出的问题

class SimpleGraph:
    """
    纯 Python DAG 状态机。
    替代 LangGraph StateGraph，零外部依赖。
    用法:
        graph = SimpleGraph()
        graph.add_node("name", async_or_sync_fn)
        graph.set_entry_point("name")
        graph.add_edge("a", "b")
        graph.add_conditional_edges("a", router_fn, {"val1": "b", "val2": None})
        compiled = graph.compile()
        result = await compiled.ainvoke(initial_state)
    约定:
        - 节点函数签名: (state: dict) -> dict  (返回需要合并的字段)
        - router_fn 签名: (state: dict) -> str
        - 目标为 None 表示 END
    """
    END = "__end__"

    def __init__(self):
        self._nodes: Dict[str, Any] = {}
        self._edges: Dict[str, Any] = {}  # node -> target_node | None
        self._conditional: Dict[str, tuple] = {}  # node -> (router_fn, mapping)
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
    """编译后的图，支持 ainvoke"""
    def __init__(self, graph: SimpleGraph):
        self._g = graph

    async def ainvoke(self, state: dict) -> dict:
        current = self._g._entry
        if not current:
            raise RuntimeError("未设置 entry_point")

        while current and current != SimpleGraph.END:
            # 执行当前节点
            fn = self._g._nodes.get(current)
            if fn is None:
                raise RuntimeError(f"未找到节点: {current}")

            # 支持 sync / async 节点
            if asyncio.iscoroutinefunction(fn):
                updates = await fn(state)
            else:
                updates = fn(state)

            # 合并返回值到 state
            if updates and isinstance(updates, dict):
                state.update(updates)

            # 决定下一个节点
            if current in self._g._conditional:
                router_fn, mapping = self._g._conditional[current]
                route_key = router_fn(state)
                next_node = mapping.get(route_key)
                current = next_node  # None = END
            elif current in self._g._edges:
                current = self._g._edges[current]
            else:
                current = None  # 没有后续边 = END

        return state

# ═══════════════════════════════════════════════════════
# qwenAgent 主类
# ═══════════════════════════════════════════════════════
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

        # =========================
        # Tool Registry（Agent工具）
        # =========================
        self.tools = {
            "retrieve_evidence": self.medical_assistant.fast_parallel_retrieve
        }

        # =========================
        # 构建状态机图
        # =========================
        self.graph = self._build_graph()

    # =========================================================
    # 工具方法
    # =========================================================
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
        logger.info(
            content_str[:500] + ("..." if len(content_str) > 500 else "")
        )
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
        """智能截断：保留开头和结尾"""
        if not text or len(text) <= max_chars:
            return text
        half = max_chars // 2
        return (
                text[:half]
                + f"\n\n... [已截断 {len(text) - max_chars} 字符] ...\n\n"
                + text[-half:]
        )

    # =========================================================
    # Agent Tool Router
    # =========================================================
    def _run_tool(self, tool_name: str, *args, **kwargs):
        """Agent工具调用入口"""
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

    # =========================================================
    # 状态机构建
    # =========================================================
    def _build_graph(self) -> _CompiledGraph:
        """
        构建 DAG 状态机:
            intent ──► [irrelevant] ──► END
                   ──► [knowledge]  ──► END
                   ──► [consultation] ──► analysis ──► retrieve ──► reason ──► END
        """
        graph = SimpleGraph()

        # ========== 节点 ==========
        graph.add_node("intent", self._node_intent)
        graph.add_node("analysis", self._node_analysis)
        graph.add_node("retrieve", self._node_retrieve)
        graph.add_node("reason", self._node_reason)

        # ========== 流程 ==========
        graph.set_entry_point("intent")
        graph.add_conditional_edges(
            "intent",
            self._route_intent,
            {
                "consultation": "analysis",
                "knowledge": None,  # END
                "irrelevant": None  # END
            }
        )
        graph.add_edge("analysis", "retrieve")
        graph.add_edge("retrieve", "reason")
        # reason 没有后续边 → 自动 END

        return graph.compile()

    # =========================================================
    # Graph Nodes
    # =========================================================
    async def _node_intent(self, state: dict) -> dict:
        """意图分类节点"""
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
        intent_response = await self.llm_critic.ainvoke(
            [HumanMessage(content=intent_prompt)]
        )
        logging.info(f"=== 意图分类原始响应: {intent_response.content} ===")
        intent_result = self._parse_json(
            intent_response.content, {"type": "irrelevant"}
        )
        logging.info(f"=== 意图分类解析结果: {intent_result} ===")
        intent_type = intent_result.get("type", "irrelevant")
        logging.info(f"=== 最终意图类型: {intent_type} ===")
        return {"intent_type": intent_type}

    def _route_intent(self, state: dict) -> str:
        """意图路由函数"""
        t = state.get("intent_type", "irrelevant")
        if t == "consultation":
            return "consultation"
        if t == "knowledge":
            return "knowledge"
        return "irrelevant"

    async def _node_analysis(self, state: dict) -> dict:
        """统一分析节点：结构化提取 + 复杂度 + 临床问题 + 用户原始问题"""
        case_text = state["case_text"]
        all_info = state.get("all_info", "")
        analysis = await self._unified_analysis(case_text, all_info)

        context = analysis.get(
            "structured_context", {"原始病例": case_text}
        )
        clinical_questions = analysis.get("clinical_questions", [])
        key_risks = analysis.get("key_risks", [])
        complexity = analysis.get("complexity", "high")
        # [MODIFIED] 提取用户原始问题
        user_questions = analysis.get("user_questions", [])

        if not clinical_questions:
            clinical_questions = ["该患者当前最紧急的临床问题和处置要点"]
        clinical_questions = clinical_questions[:MAX_SUB_QUESTIONS]

        return {
            "context": context,
            "clinical_questions": clinical_questions,
            "key_risks": key_risks,
            "complexity": complexity,
            "user_questions": user_questions   # [MODIFIED] 存入状态
        }

    def _node_retrieve(self, state: dict) -> dict:
        """证据检索节点"""
        questions = state.get("clinical_questions", [])
        logging.info(f"🔧 Agent Tool 调用: retrieve_evidence")
        evidence = self._run_tool("retrieve_evidence", questions)
        evidence_truncated = self._truncate(evidence, MAX_EVIDENCE_CHARS)
        return {"evidence": evidence_truncated}

    async def _node_reason(self, state: dict) -> dict:
        """Proposer + Critic 并行推理节点"""
        context = state.get("context", {})
        evidence = state.get("evidence", "")
        all_info = state.get("all_info", "")
        # [MODIFIED] 获取用户问题列表
        user_questions = state.get("user_questions", [])
        proposal, critique = await self._parallel_propose_and_critique(
            context, evidence, all_info, user_questions   # [MODIFIED] 传递
        )
        return {"proposal": proposal, "critique": critique}

    # =========================================================
    # 对外入口
    # =========================================================
    def run_clinical_reasoning(
            self,
            case_text: str,
            all_info: str = "",
            report_mode: str = "emergency",
            show_thinking: bool = True
    ) -> Generator[dict, None, None]:
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            classification = loop.run_until_complete(self._classify_multi_mcq_with_llm(case_text))
            llm_multi_mcq = classification.get("is_multi_mcq", False)
            llm_q_type = classification.get("question_type", "unknown")
            is_multi_mcq = llm_multi_mcq or self._is_multi_mcq(case_text)

            if is_multi_mcq:
                if show_thinking:
                    yield self._emit_thinking(
                        "Intent",
                        "✅ 检测到多题选择题任务",
                        f"进入拆题并行求解流程（type={llm_q_type}）"
                    )
                default_q_type = llm_q_type if llm_q_type in {"single", "multiple", "mixed"} else "unknown"
                multi_result = loop.run_until_complete(
                    self._run_multi_mcq(case_text, default_question_type=default_q_type))
                if multi_result:
                    yield {"type": "result", "content": multi_result}
                    if show_thinking:
                        yield self._emit_thinking("Done", "✅ 多题处理完成", "已按Q1/Q2/...格式输出")
                else:
                    error_msg = "已检测到这可能是多道选择题，但拆分题目失败，请检查输入格式。"
                    yield {"type": "result", "content": error_msg}
                return

            # ══════════════════════════════════════
            # 运行状态机
            # ══════════════════════════════════════
            initial_state = {
                "case_text": case_text,
                "all_info": all_info,
                "report_mode": report_mode,
                "show_thinking": show_thinking
            }

            result = loop.run_until_complete(
                self.graph.ainvoke(initial_state)
            )

            # ══════════════════════════════════════
            # 根据意图类型分流输出
            # ══════════════════════════════════════
            intent_type = result.get("intent_type", "irrelevant")

            # --- irrelevant ---
            if intent_type == "irrelevant":
                logging.info("=== 意图被分类为 irrelevant，返回拒绝消息 ===")
                yield {
                    "type": "result",
                    "content": "请提供脑卒中医疗临床相关查询，此输入无关。"
                }
                return

            # --- knowledge ---
            if intent_type == "knowledge":
                logging.info("=== 意图被分类为 knowledge，进入知识问答流程 ===")
                if show_thinking:
                    yield self._emit_thinking(
                        "Intent", "✅ 意图验证：通用知识问题",
                        "使用 Qwen-Max 直接回答"
                    )
                knowledge_prompt = f"""你是三甲医院神经内科主任医师。请基于循证医学知识，直接回答以下脑卒中相关通用问题。

                问题：{case_text}

                回答要求：
                - 用中文，简洁专业
                - 禁止确诊语气
                - 禁止具体剂量
                - 如果需要，引用权威指南"""
                knowledge_response = loop.run_until_complete(
                    self.llm_proposer.ainvoke([
                        HumanMessage(content=knowledge_prompt)
                    ])
                )
                answer = knowledge_response.content if hasattr(
                    knowledge_response, "content"
                ) else str(knowledge_response)
                yield {"type": "result", "content": answer}
                return

            # --- consultation（完整流程输出） ---
            if show_thinking:
                yield self._emit_thinking(
                    "Intent", "✅ 意图验证通过", "输入为问诊相关查询"
                )

            # 从 graph 结果中提取各阶段数据
            context = result.get("context", {"原始病例": case_text})
            clinical_questions = result.get("clinical_questions", [])
            key_risks = result.get("key_risks", [])
            complexity = result.get("complexity", "high")
            evidence = result.get("evidence", "")
            proposal = result.get("proposal", "")
            critique = result.get("critique", "")
            user_questions = result.get("user_questions", [])   # [MODIFIED] 获取用户问题

            # [MODIFIED] 如果存在用户明确问题，直接返回融合后的答案
            if user_questions:

                if show_thinking:
                    yield self._emit_thinking(
                        "DirectAnswer",
                        "✅ 检测到用户问题列表，生成最终答案",
                        f"共 {len(user_questions)} 个问题"
                    )

                final_answer = proposal

                yield {
                    "type": "result",
                    "content": final_answer
                }

                return

            # 以下为原有报告生成流程（当没有用户问题时）
            if show_thinking:
                yield self._emit_thinking(
                    "Step 1", "✅ 病例分析完成", {
                        "complexity": complexity,
                        "questions": clinical_questions,
                        "key_risks": key_risks
                    }
                )

            yield {
                "type": "meta",
                "content": {
                    "complexity": complexity,
                    "report_mode": report_mode,
                    "key_risks": key_risks
                }
            }

            if show_thinking:
                yield self._emit_thinking(
                    "Step 2", "✅ 证据检索完成",
                    f"证据 {len(evidence)} 字符"
                )
                yield self._emit_thinking(
                    "Step 3a", "✅ Proposer 推理完成",
                    proposal[:800] + "..."
                    if len(proposal) > 800 else proposal
                )
                yield self._emit_thinking(
                    "Step 3b", "✅ Critic 批判完成",
                    critique[:800] + "..."
                    if len(critique) > 800 else critique
                )

            # ══════════════════════════════════════
            # 流式生成最终报告
            # ══════════════════════════════════════
            if show_thinking:
                yield self._emit_thinking(
                    "Step 4",
                    f"📝 生成最终报告 (模式={report_mode})...",
                    "融合推理 + 批判 → 最终临床报告"
                )

            proposal_truncated = self._truncate(proposal, MAX_PROPOSAL_CHARS)
            critique_truncated = self._truncate(critique, MAX_CRITIQUE_CHARS)

            final_chunks = []

            async def collect_final():
                async for chunk in self.medical_assistant.stream_final_report(
                        context=context,
                        proposal=proposal_truncated,
                        critique=critique_truncated,
                        evidence=evidence,
                        all_info=all_info,
                        report_mode=report_mode
                ):
                    if isinstance(chunk, str) and chunk:
                        final_chunks.append(chunk)
                    elif hasattr(chunk, "content") and chunk.content:
                        final_chunks.append(chunk.content)

            loop.run_until_complete(collect_final())

            # 一次性输出完整报告
            full_report = "".join(final_chunks)
            if full_report:
                yield {"type": "result", "content": full_report}

            if show_thinking:
                yield self._emit_thinking(
                    "Done", "✅ 全部完成", "临床推理管线执行完毕"
                )

        except Exception as e:
            logging.error(f"=== 临床推理管线异常: {e} ===")
            logging.error(f"=== 异常类型: {type(e).__name__} ===")
            import traceback
            logging.error(f"=== 详细堆栈: {traceback.format_exc()} ===")
            yield {"type": "error", "content": f"管线异常: {str(e)}"}
        finally:
            if loop:
                loop.close()

    # =========================================================
    # 新增：3-shot CoT 临床问答
    # =========================================================
    def answer_clinical_qa_with_cot(self, question: str) -> str:
        """
        使用3-shot Chain-of-Thought示例回答临床问答题。
        参数:
            question: 临床问题文本（可包含多个子问题）
        返回:
            包含逐步推理的答案文本
        """
        try:
            prompt = f"{COT_EXAMPLES}\n\n现在，请回答下面的问题：\n问题：{question}\n答案："
            response = self.llm_proposer.invoke([HumanMessage(content=prompt)])
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error(f"CoT问答失败: {e}")
            return "生成答案时出现错误，请稍后重试。"

    # =========================================================
    # LLM #1: 统一分析
    # =========================================================
    async def _unified_analysis(
            self, case_text: str, all_info: str
    ) -> Dict[str, Any]:
        # [MODIFIED] 在提示词中新增 user_questions 字段
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
        "如果输入中包含“请回答以下问题：”或类似明确的问题列表，请将每个问题原文提取出来；若没有，则返回空列表"
    ]
}}

要求：
- structured_context: 提取所有临床信息
- complexity: critical=危及生命
- clinical_questions: 3个最需要查证的问题，用于检索医学文献，必须用中文
- user_questions: 若输入中用户明确提出了若干具体问题（例如以“请回答以下问题：”引导的列表），请将每个问题原文提取为字符串数组；若无，则返回空数组。"""

        response = await self.llm_critic.ainvoke([
            HumanMessage(content=prompt)
        ])
        result = self._parse_json(response.content, None)

        if result and isinstance(result, dict):
            # [MODIFIED] 确保返回的字典包含 user_questions 字段
            if "user_questions" not in result:
                result["user_questions"] = []
            return result

        # 解析失败时的默认返回
        return {
            "structured_context": {"原始病例": case_text},
            "complexity": "high",
            "key_risks": [],
            "clinical_questions": ["该患者当前最紧急的临床问题和处置要点"],
            "user_questions": []   # [MODIFIED] 默认空列表
        }

    # =========================================================
    # LLM #2 + #3: Proposer 和 Critic 并行
    # =========================================================
    async def _parallel_propose_and_critique(
            self,
            context: Dict,
            evidence: str,
            all_info: str,
            user_questions: List[str]   # [MODIFIED] 新增参数
    ) -> tuple:
        context_str = json.dumps(context, ensure_ascii=False, indent=2)
        evidence_str = evidence if evidence else "未检索到相关��据"
        all_info_str = all_info if all_info else "无"

        # =========================
        # 如果用户有明确问题 → 使用简化回答模式
        # =========================
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

        proposer_task = self.llm_proposer.ainvoke([
            HumanMessage(content=proposer_prompt)
        ])
        critic_task = self.llm_critic.ainvoke([
            HumanMessage(content=pre_critic_prompt)
        ])

        proposer_resp, critic_resp = await asyncio.gather(
            proposer_task, critic_task
        )
        
        proposal_text = proposer_resp.content
        critic_text = critic_resp.content

        # =========================
        # Critic参与最终答案
        # =========================

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

        final_resp = await self.llm_proposer.ainvoke([
            HumanMessage(content=final_prompt)
        ])

        final_answer = final_resp.content

        return final_answer, critic_text

    # 以下方法（analyze_patient_risk, MCQ处理等）保持不变
    def analyze_patient_risk(self, patient_data: str, all_info: str = "") -> Dict[str, str]:
        """面向 API 的简版健康风险分析，返回稳定结构。"""
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            analysis = loop.run_until_complete(
                self._unified_analysis(patient_data, all_info)
            )
            context = analysis.get("structured_context", {"原始病例": patient_data})
            complexity = str(analysis.get("complexity", "high")).lower()
            key_risks = analysis.get("key_risks", []) or []
            questions = analysis.get("clinical_questions", []) or []

            prompt = f"""你是资深临床风险评估医生。请基于以下患者信息，输出该患者的健康风险结论。

            【患者原始数据】
            {patient_data}

            【结构化分析】
            {json.dumps(context, ensure_ascii=False, indent=2)}

            【关键风险】
            {json.dumps(key_risks, ensure_ascii=False)}

            【待关注临床问题】
            {json.dumps(questions, ensure_ascii=False)}

            请直接输出 JSON：

            {{
                "riskLevel": "低风险/中风险/高风险",
                "suggestion": "一句到两句干预建议",
                "analysisDetails": "简要说明风险依据"
            }}

            要求：
            - 仅输出 JSON，不要 markdown
            - riskLevel 只能是：低风险、中风险、高风险
            - suggestion 简洁、可执行，不写具体药物剂量"""

            response = loop.run_until_complete(
                self.llm_critic.ainvoke([HumanMessage(content=prompt)])
            )
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
            if risk_level not in {"低风险", "中风险", "高风险"}:
                risk_level = default_risk_level

            return {
                "riskLevel": risk_level,
                "suggestion": result.get("suggestion") or default_suggestion,
                "analysisDetails": result.get("analysisDetails") or default_details
            }
        except Exception as e:
            logger.error(f"患者风险分析失败: {e}")
            return {
                "riskLevel": "中风险",
                "suggestion": "建议结合线下检查结果进一步评估，如症状加重请及时就医。",
                "analysisDetails": "系统已完成基础风险评估，但详细分析生成失败，请结合临床实际判断。"
            }
        finally:
            if loop:
                loop.close()

    # =========================================================
    # MCQ (多选题) 核心处理逻辑 (全面升级为LLM拆题)
    # =========================================================
    def _is_multi_mcq(self, text: str) -> bool:
        """快速初步判定是否包含选择题选项"""
        return len(re.findall(r"(?:^|\n)\s*[A-D][\.\、\):：]\s+", text)) >= 2

    async def _split_mcq_with_llm(self, text: str) -> List[Dict[str, Any]]:
        """使用大模型对多道选择题进行智能拆分，替代原有的脆弱正则"""
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
        """正则兜底拆分"""
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
        """
        LLM判断是否为多道选择题，并判定题型倾向（single/multiple/mixed/unknown）。
        """
        if not text or len(text.strip()) < 8:
            return {"is_multi_mcq": False, "question_type": "unknown", "reason": "empty"}
        prompt = f"""你是任务识别器。请判断输入是否为“包含2道及以上选择题”的试题文本，并判断题型。

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
3) 若出现“多选/可多选/选出所有正确项”等，优先判为 multiple 或 mixed
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

    async def _detect_question_type_with_llm(self, question_text: str, default_type: str = "single") -> str:
        """
        单题判定题型：single 或 multiple。
        """
        prompt = f"""你是题型识别器。判断下列题目是单选题还是多选题。

题目：

{question_text}

只输出 JSON：
{{"question_type":"single/multiple","reason":"一句话"}}

规则：
- 出现“多选/可多选/选出所有正确项/不止一个正确答案” => multiple
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
        """
        解析模型返回答案：
        - single: 返回单个字母，如 A
        - multiple: 返回逗号分隔，如 A,C,E
        """
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
        """
        支持单选/多选作答。
        """
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

        tasks = [
            self._answer_single_mcq(item["text"], q_type)
            for item, q_type in zip(questions, per_question_types)
        ]
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