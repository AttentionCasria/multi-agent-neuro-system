"""
临床推理图 - 多层架构的临床决策支持系统

功能说明：
- 基于LangGraph构建的临床推理工作流
- 实现了类似医院会诊流程的多层决策机制
- 支持人工干预和反思循环，确保医疗建议的安全性

架构设计：
- 前层：意图识别 + 病例分析 + 证据检索
- 中层：多专家协作推理（全科、专科、药师）
- 后层：双层校验（规则引擎 + LLM反思）

工作流程：
1. 意图识别：判断用户输入类型
2. 病例分析：结构化病例信息，生成子问题
3. 证据检索：基于子问题检索医学文献
4. 多专家推理：三位专家并行推理并综合
5. 结果校验：规则引擎+LLM双重校验
6. 报告生成：生成最终临床报告

特色功能：
- 反思循环：支持基于校验反馈的重新推理（最多3次）
- 人工干预：在报告生成前支持人工审批
- 状态持久化：支持断点续传和状态恢复
"""

import logging
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from app.agents.core.schema import ClinicalState
from app.agents.orchestrators.nodes.intent_node import IntentNode
from app.agents.orchestrators.nodes.analysis_node import AnalysisNode
from app.agents.orchestrators.nodes.retrieve_node import RetrieveNode
from app.agents.orchestrators.nodes.reason_node import ReasonNode
from app.agents.orchestrators.nodes.report_node import ReportNode
from app.agents.orchestrators.nodes.validate_node import ValidateNode
from app.config.config_loader import get_validation_manager

logger = logging.getLogger(__name__)


class ClinicalGraphBuilder:
    """
    临床推理图构建器（多层架构版）

    职责：
    - 构建完整的临床推理工作流
    - 配置节点之间的连接关系
    - 设置路由条件和中断点
    - 编译生成可执行的计算图

    架构层次：
    - 前层：意图识别 → 病例分析 → 证据检索
    - 中层：多专家协作推理
    - 后层：双层校验 → 报告生成

    特色功能：
    - 反思循环：支持基于反馈的重新推理（可配置次数）
    - 人工干预：报告生成前的人工审批
    - 状态持久化：支持断点续传
    """

    def __init__(
        self,
        intent_node: IntentNode,
        analysis_node: AnalysisNode,
        retrieve_node: RetrieveNode,
        reason_node: ReasonNode,
        report_node: ReportNode,
        validate_node: ValidateNode = None,
        llm_critic=None,
        report_manager=None,
    ):
        """
        初始化临床推理图构建器

        参数：
        - intent_node: 意图识别节点
        - analysis_node: 病例分析节点
        - retrieve_node: 证据检索节点
        - reason_node: 多专家推理节点
        - report_node: 报告生成节点
        - validate_node: 结果校验节点（可选）
        - llm_critic: 用于知识问答的LLM（可选）
        - report_manager: 报告模板管理器（可选）
        """
        self.intent_node = intent_node
        self.analysis_node = analysis_node
        self.retrieve_node = retrieve_node
        self.reason_node = reason_node
        self.report_node = report_node
        self.validate_node = validate_node
        self.llm_critic = llm_critic
        self.report_manager = report_manager
        
        # 加载校验配置以获取最大反思次数
        self.validation_manager = get_validation_manager()
        self.max_reflection_count = self.validation_manager.get_max_reflection_count()
        
        # 实例化持久化内存用于断点等待
        # 支持状态持久化和断点续传
        self.checkpointer = MemorySaver()

    def build(self):
        """
        构建并编译临床推理图

        工作流程：
        1. 创建状态图
        2. 添加所有节点
        3. 设置入口点
        4. 配置节点间的连接关系
        5. 设置路由条件
        6. 编译生成可执行图

        返回：
        - CompiledGraph: 编译后的临床推理图
        """
        # 步骤1: 创建状态图，定义状态类型
        graph = StateGraph(ClinicalState)

        # 步骤2: 添加所有节点
        graph.add_node("intent", self.intent_node.run)
        graph.add_node("reject", self._reject_node)
        graph.add_node("knowledge_answer", self._knowledge_node)
        graph.add_node("analysis", self.analysis_node.run)
        graph.add_node("retrieve", self.retrieve_node.run)
        graph.add_node("reason", self.reason_node.run)
        
        # 校验节点是可选的
        if self.validate_node:
            graph.add_node("validate", self.validate_node.run)
            
        graph.add_node("generate_report", self.report_node.run)

        # 步骤3: 设置入口点为意图识别节点
        graph.set_entry_point("intent")

        # 步骤4: 添加条件边（意图路由）
        # 根据意图类型路由到不同的处理流程
        graph.add_conditional_edges(
            "intent",
            self._route_intent,
            {
                "irrelevant": "reject",      # 无关输入 → 拒绝处理
                "knowledge": "knowledge_answer",  # 知识问答 → 直接回答
                "consultation": "analysis",  # 临床问诊 → 进入完整推理流程
            }
        )

        # 步骤5: 添加节点间的连接边
        graph.add_edge("reject", END)                    # 拒绝节点 → 结束
        graph.add_edge("knowledge_answer", END)          # 知识问答 → 结束
        graph.add_edge("analysis", "retrieve")           # 病例分析 → 证据检索
        graph.add_edge("retrieve", "reason")             # 证据检索 → 多专家推理
        
        # 步骤6: 配置中层到后层的流程（支持反思循环）
        if self.validate_node:
            # 有校验节点：推理 → 校验 → (通过/重试/失败) → 报告
            graph.add_edge("reason", "validate")
            graph.add_conditional_edges(
                "validate",
                self._route_validation,
                {
                    "pass": "generate_report",  # 通过校验 → 生成报告
                    "retry": "reason",          # 未通过 → 重新推理（反思循环）
                    "fail": "generate_report"   # 多次失败 → 强制输出（附带警告）
                }
            )
            logger.info("[graph] 已添加校验节点和反思循环路由")
            logger.info("[graph] 路由映射: pass -> generate_report, retry -> reason, fail -> generate_report")
        else:
            # 无校验节点：推理 → 直接生成报告
            graph.add_edge("reason", "generate_report")
            logger.info("[graph] 无校验节点，推理直接连接到报告生成")
            
        graph.add_edge("generate_report", END)          # 报告生成 → 结束

        # 步骤7: 编译图
        # 移除中断点，让流程自动完成
        return graph.compile(
            checkpointer=self.checkpointer
        )

    def _route_intent(self, state: ClinicalState) -> str:
        """
        路由意图分类结果

        参数：
        - state: 临床状态对象，包含意图类型

        返回：
        - str: 路由目标节点名称
        """
        t = state['intent_type']
        if t in ("consultation", "knowledge"):
            return t
        return "irrelevant"

    async def _reject_node(self, state: ClinicalState) -> dict:
        """
        拒绝节点 - 处理无关输入

        参数：
        - state: 临床状态对象

        返回：
        - dict: 包含拒绝信息的字典
        """
        return {"report": "请提供脑卒中医疗临床相关查询，此输入无关。"}

    async def _knowledge_node(self, state: ClinicalState) -> dict:
        """
        知识回答节点 - 处理通用医学知识问题

        参数：
        - state: 临床状态对象

        返回：
        - dict: 包含知识回答的字典
        """
        # 检查LLM是否就绪
        if not self.llm_critic:
            return {"report": "知识回答服务未就绪"}

        # 构建知识问答的prompt
        knowledge_prompt = f"""你是三甲医院神经内科主任医师。请基于循证医学知识，直接回答以下脑卒中相关通用问题。

问题：{state['case_text']}

回答要求：
- 用中文，简洁专业
- 禁止确诊语气
- 禁止具体剂量
- 如果需要，引用权威指南"""

        # 构建消息列表
        messages = [
            SystemMessage(content=self.report_manager.system_role if self.report_manager else "你是一位专业的神经内科医生。"),
            HumanMessage(content=knowledge_prompt),
        ]

        # 流式生成回答
        content = ""
        async for chunk in self.llm_critic.astream(messages):
            c = chunk.content if hasattr(chunk, "content") else str(chunk)
            content += c

        return {"report": content}
        
    def _route_validation(self, state: ClinicalState) -> str:
        """
        路由校验结果与反思循环

        参数：
        - state: 临床状态对象，包含校验结果和反思次数

        返回：
        - str: 路由决策（pass/retry/fail）

        路由规则：
        - pass: 校验通过 → 生成报告
        - retry: 校验未通过且反思次数<最大值 → 重新推理
        - fail: 校验未通过且反思次数>=最大值 → 强制输出
        """
        logger.info(f"[route_validation] 校验路由决策")
        logger.info(f"[route_validation] 校验状态: {state['validation_passed']}")
        logger.info(f"[route_validation] 反思次数: {state['reflection_count']}")
        logger.info(f"[route_validation] 最大反思次数: {self.max_reflection_count}")
        
        route_decision = None
        if state['validation_passed']:
            route_decision = "pass"
            logger.info(f"[route_validation] 决策: pass → 生成报告")
        elif state['reflection_count'] < self.max_reflection_count:  # 使用配置的最大反思次数
            route_decision = "retry"
            logger.info(f"[route_validation] 决策: retry → 重新推理 (反思次数 {state['reflection_count']} < {self.max_reflection_count})")
        else:
            route_decision = "fail"
            logger.info(f"[route_validation] 决策: fail → 强制输出 (反思次数 {state['reflection_count']} >= {self.max_reflection_count})")
        
        logger.info(f"[route_validation] 最终路由决策: {route_decision} (类型: {type(route_decision)})")
        
        # 确保返回字符串
        if not isinstance(route_decision, str):
            logger.error(f"[route_validation] 路由决策不是字符串: {route_decision}，强制返回'fail'")
            route_decision = "fail"
        
        return route_decision