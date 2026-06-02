"""
临床推理节点 - 多专家协作推理模块

功能说明：
- 这是临床推理图的核心节点，负责多专家并行推理和意见综合
- 采用"多Agent协作 + 意见综合"的架构模式
- 实现了类似医疗会诊的多专家协同决策机制

工作流程：
1. 并行调用多位专家进行独立推理
2. 收集各专家意见
3. 通过LLM进行意见综合，生成最终提案和风险批判
4. 返回结构化的推理结果

设计模式：
- 并行执行模式：多位专家同时推理，提高效率
- 意见综合模式：通过LLM统筹多专家意见，避免简单拼接
- 反思机制：支持基于校验反馈的重新推理
- 动态配置模式：专家角色和职责可配置化
"""

import logging
import asyncio
from typing import Dict
from app.agents.core.schema import ClinicalState
from app.agents.orchestrators.nodes.base import BaseNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.config.config_loader import get_expert_manager

logger = logging.getLogger(__name__)


class ReasonNode(BaseNode):
    """
    临床推理节点（中层：领域专家多Agent团协作）

    职责：
    - 协调多专家并行推理
    - 综合多专家意见生成最终提案
    - 识别潜在风险并提供批判性意见

    输入状态：
    - case_text: 患者病例文本
    - all_info: 历史上下文信息
    - evidence: 检索到的医学证据
    - validation_feedback: 之前的校验反馈（用于反思）

    输出状态：
    - proposal: 综合治疗提案
    - critique: 风险批判意见
    - 以及各专家的独立建议（动态生成）

    特色功能：
    - 动态专家配置：从配置文件加载专家角色和职责
    - 专家启用/禁用：支持选择性启用特定专家
    - 可扩展架构：易于添加新的专家角色
    """

    def __init__(self, llm, expert_config=None):
        """
        初始化推理节点

        参数：
        - llm: 底层大语言模型，用于专家推理和意见综合
        - expert_config: 专家配置管理器（可选，默认使用全局单例）
        """
        self.llm = llm
        self.expert_manager = expert_config or get_expert_manager()
        
        # 加载专家配置
        self.experts = self.expert_manager.get_experts()
        self.synthesis_config = self.expert_manager.get_synthesis_config()
        
        logger.info(f"[reason] 已加载 {len(self.experts)} 位专家配置")
        for expert in self.experts:
            logger.info(f"  - {expert.get('role')} (优先级: {expert.get('priority', 'N/A')})")

    async def run(self, state: ClinicalState) -> Dict:
        """
        执行多专家并行推理

        工作流程：
        1. 构建病例信息上下文（包含历史反馈）
        2. 并行调用多位专家进行推理
        3. 综合专家意见生成最终提案和批判
        4. 返回结构化结果

        参数：
        - state: 临床状态对象，包含病例信息、上下文、证据等

        返回：
        - Dict: 包含各专家建议和综合结果的字典
        """
        logger.info(f"[reason] 开始执行推理节点")
        logger.info(f"[reason] 病例文本长度: {len(state['case_text'])}")
        logger.info(f"[reason] 证据长度: {len(state['evidence']) if state['evidence'] else 0}")
        logger.info(f"[reason] 反思次数: {state['reflection_count']}")
        
        # 步骤1: 构建完整的病例上下文信息
        case_info = f"病例：{state['case_text']}\n上下文：{state['all_info']}\n证据：{state['evidence']}"
        
        # 如果存在之前的校验反馈，添加到上下文中用于反思
        if state['validation_feedback']:
            case_info += f"\n\n【之前被驳回的反馈，请反思】：{state['validation_feedback']}"
            logger.info(f"[reason] 存在校验反馈，进入反思模式")
        
        logger.info(f"[reason] 开启多专家并行推理 (Reflection Count: {state['reflection_count']})")
        
        # 步骤2: 动态创建专家任务并并行执行
        # 使用asyncio.gather实现真正的并行推理，提高效率
        tasks = []
        expert_roles = []
        
        for expert in self.experts:
            role = expert.get("role")
            instruction = expert.get("instruction")
            expert_roles.append(role)
            
            tasks.append(self._ask_expert(role, instruction, case_info))
        
        logger.info(f"[reason] 已创建 {len(tasks)} 个专家推理任务")
        
        # 并行执行所有专家推理任务
        results = await asyncio.gather(*tasks)
        
        logger.info(f"[reason] 专家推理完成，收到 {len(results)} 个结果")
        
        # 构建专家建议字典
        expert_advices = {}
        successful_experts = 0
        for role, advice in zip(expert_roles, results):
            expert_advices[f"{role}_advice"] = advice
            if advice and not advice.startswith("未能获取"):
                successful_experts += 1
                logger.info(f"[reason] {role} 推理成功，建议长度: {len(advice)}")
            else:
                logger.warning(f"[reason] {role} 推理失败或返回空结果")
        
        logger.info(f"[reason] 成功推理专家数: {successful_experts}/{len(expert_roles)}")
        
        # 步骤3: 意见综合 - 通过LLM统筹多专家意见
        # 采用Tree-of-Thoughts/Consensus机制，避免简单意见拼接
        logger.info("[reason] 进行多专家意见统筹汇总 (Tree-of-Thoughts / Consensus)")
        
        # 构建意见综合prompt
        expert_opinions_text = self._build_expert_opinions_text(expert_roles, results)
        logger.info(f"[reason] 专家意见文本长度: {len(expert_opinions_text)}")
        
        synthesis_prompt = self.synthesis_config.get(
            "prompt_template",
            "作为主治医师，请统筹以下各位专家的意见，并给出最终综合提案(Proposal)和潜在风险批评(Critique)：\n{expert_opinions}\n请将输出分为两部分，用 \"### PROPOSAL ###\" 和 \"### CRITIQUE ###\" 隔开。"
        ).format(expert_opinions=expert_opinions_text)
        
        logger.info(f"[reason] 开始调用LLM进行意见综合")
        
        try:
            # 调用LLM进行意见综合
            synthesis_res = await self.llm.ainvoke([HumanMessage(content=synthesis_prompt)])
            content = getattr(synthesis_res, "content", str(synthesis_res))
            logger.info(f"[reason] 意见综合完成，结果长度: {len(content)}")
        except Exception as e:
            logger.error(f"[reason] 意见综合失败: {type(e).__name__} - {str(e)}")
            # 如果意见综合失败，使用默认结果
            content = "### PROPOSAL ###\n基于专家意见，建议进一步检查和评估。\n\n### CRITIQUE ###\n由于意见综合失败，无法提供详细的风险批判。"
        
        # 步骤4: 解析综合结果，分离提案和批判
        proposal_separator = self.synthesis_config.get("proposal_separator", "### PROPOSAL ###")
        critique_separator = self.synthesis_config.get("critique_separator", "### CRITIQUE ###")
        
        parts = content.split(critique_separator)
        proposal_text = parts[0].replace(proposal_separator, "").strip()
        critique_text = parts[1].strip() if len(parts) > 1 else "无明显风险批判。"

        logger.info(f"[reason] 提案长度: {len(proposal_text)}, 批判长度: {len(critique_text)}")
        
        # 返回完整的推理结果
        result = {
            "proposal": proposal_text,
            "critique": critique_text
        }
        
        # 添加各专家的独立建议
        result.update(expert_advices)
        
        logger.info(f"[reason] 推理节点执行完成，返回结果")
        return result

    def _build_expert_opinions_text(self, roles: list, results: list) -> str:
        """
        构建专家意见文本

        参数：
        - roles: 专家角色列表
        - results: 专家建议结果列表

        返回：
        - str: 格式化的专家意见文本
        """
        separator = self.synthesis_config.get("opinion_separator", "【{role}建议】{opinion}\n")
        
        opinions = []
        for role, advice in zip(roles, results):
            opinions.append(separator.format(role=role, opinion=advice))
        
        return "\n".join(opinions)

    async def _ask_expert(self, role: str, instruction: str, case_info: str) -> str:
        """
        向单个专家咨询意见

        参数：
        - role: 专家角色名称（如"全科医生"、"神经专科医生"等）
        - instruction: 专家的具体任务指令
        - case_info: 病例信息上下文

        返回：
        - str: 专家的建议意见

        异常处理：
        - 如果专家推理失败，返回错误信息并记录日志
        """
        # 获取专家的系统提示词
        expert_config = self.expert_manager.get_expert_by_role(role)
        system_prompt = expert_config.get("system_prompt", f"你是专业的{role}") if expert_config else f"你是专业的{role}"
        
        # 构建专家专用的prompt，包含角色设定和任务指令
        prompt = f"你目前扮演【{role}】。\n{instruction}\n\n【病历资料】\n{case_info}"
        
        try:
            # 调用LLM进行专家推理
            # SystemMessage设定专家角色，HumanMessage提供具体任务
            res = await self.llm.ainvoke([
                SystemMessage(content=system_prompt), 
                HumanMessage(content=prompt)
            ])
            return getattr(res, "content", "")
        except Exception as e:
            # 异常处理：记录错误并返回友好的错误信息
            logger.error(f"{role} 推理失败: {e}")
            return f"未能获取{role}建议。"