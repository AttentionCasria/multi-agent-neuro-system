# Agent/qwen/qwenAgent.py — LangGraph-Free 状态机版 v3

import logging
import asyncio
import json
from typing import Generator, List, Dict, Any, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from config.config_loader import PromptManager, ReportTemplateManager

logger = logging.getLogger(__name__)

MAX_SUB_QUESTIONS = 3
MAX_EVIDENCE_CHARS = 3000
MAX_PROPOSAL_CHARS = 3000
MAX_CRITIQUE_CHARS = 3000


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
    # 工具方法（全部保留不变）
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
    # Agent Tool Router（新增）
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
    # 状态机构建（新增，替代 LangGraph）
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
    # Graph Nodes（新增）
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
        """统一分析节点：结构化提取 + 复杂度 + 临床问题"""
        case_text = state["case_text"]
        all_info = state.get("all_info", "")

        analysis = await self._unified_analysis(case_text, all_info)

        context = analysis.get(
            "structured_context", {"原始病例": case_text}
        )
        clinical_questions = analysis.get("clinical_questions", [])
        key_risks = analysis.get("key_risks", [])
        complexity = analysis.get("complexity", "high")

        if not clinical_questions:
            clinical_questions = ["该患者当前最紧急的临床问题和处置要点"]
        clinical_questions = clinical_questions[:MAX_SUB_QUESTIONS]

        return {
            "context": context,
            "clinical_questions": clinical_questions,
            "key_risks": key_risks,
            "complexity": complexity
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

        proposal, critique = await self._parallel_propose_and_critique(
            context, evidence, all_info
        )

        return {"proposal": proposal, "critique": critique}

    # =========================================================
    # 对外入口（重写：graph 调用 + 流式输出）
    # =========================================================

    # =========================================================
    # 对外入口（修复版：避免 astream 在 graph 后 hang）
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

            # --- knowledge（✅ 修复：用 ainvoke 替代 astream） ---
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
            # ✅ 修复：先收集所有 chunks，再一次性 yield
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
    # LLM #1: 统一分析（保留不变，被 _node_analysis 复用）
    # =========================================================

    async def _unified_analysis(
            self, case_text: str, all_info: str
    ) -> Dict[str, Any]:

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
    ]
}}

要求：
- structured_context: 提取所有临床信息
- complexity: critical=危及生命
- clinical_questions: 3个最需要查证的问题，用于检索医学文献，必须用中文"""

        response = await self.llm_critic.ainvoke([
            HumanMessage(content=prompt)
        ])

        result = self._parse_json(response.content, None)
        if result and isinstance(result, dict):
            return result

        return {
            "structured_context": {"原始病例": case_text},
            "complexity": "high",
            "key_risks": [],
            "clinical_questions": ["该患者当前最紧急的临床问题和处置要点"]
        }

    # =========================================================
    # LLM #2 + #3: Proposer 和 Critic 并行（保留不变，被 _node_reason 复用）
    # =========================================================

    async def _parallel_propose_and_critique(
            self,
            context: Dict,
            evidence: str,
            all_info: str
    ) -> tuple:

        context_str = json.dumps(context, ensure_ascii=False, indent=2)
        evidence_str = evidence if evidence else "未检索到相关证据"
        all_info_str = all_info if all_info else "无"

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
        
        对每个风险给出严重程度和建议。请精简输出，重��突出。
        
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

        return proposer_resp.content, critic_resp.content

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
            - suggestion 简明、可执行，不写具体药物剂量"""

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
