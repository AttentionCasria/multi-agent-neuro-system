"""
结果校验节点 - 质量控制和安全审查模块

功能说明：
- 作为临床推理图的出口节点，负责对推理结果进行双重校验
- 结合静态规则引擎和动态LLM反思，确保医疗建议的安全性
- 实现了类似医疗质控的多层审查机制

工作流程：
1. 静态规则引擎检查：动态加载的禁忌症规则匹配
2. 动态LLM反思：通过LLM进行深层次的医学逻辑审查
3. 根据校验结果决定是否通过或需要重新推理

设计模式：
- 双层校验模式：规则引擎 + LLM反思
- 反思循环模式：支持基于反馈的重新推理
- 安全兜底模式：异常情况下默认放行，避免阻塞
- 动态配置模式：规则和参数可配置化
"""

import logging
from typing import Dict
from app.agents.core.schema import ClinicalState
from app.agents.orchestrators.nodes.base import BaseNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.config.config_loader import get_validation_manager

logger = logging.getLogger(__name__)

class ValidateNode(BaseNode):
    """
    结果校验节点 - 医疗建议的安全守门人

    职责：
    - 静态规则引擎检查：动态加载的禁忌症规则匹配
    - 动态LLM反思：深层次的医学逻辑审查
    - 决定推理结果是否通过或需要重新推理

    输入状态：
    - case_text: 患者病例文本
    - proposal: 综合治疗提案
    - evidence: 检索到的医学证据
    - reflection_count: 当前反思次数

    输出状态：
    - validation_passed: 是否通过校验
    - validation_feedback: 校验反馈信息
    - reflection_count: 更新后的反思次数

    校验策略：
    - 静态规则：快速匹配动态加载的禁忌症
    - 动态反思：LLM深层次医学逻辑审查
    - 反思循环：最多N次反思机会（可配置）
    """

    def __init__(self, llm, validation_config=None):
        """
        初始化校验节点

        参数：
        - llm: 大语言模型，用于动态反思校验
        - validation_config: 校验配置管理器（可选，默认使用全局单例）
        """
        self.llm = llm
        self.validation_manager = validation_config or get_validation_manager()
        
        # 加载校验配置
        self.contraindication_rules = self.validation_manager.get_contraindication_rules()
        self.max_reflection_count = self.validation_manager.get_max_reflection_count()
        self.enable_rule_engine = self.validation_manager.is_rule_engine_enabled()
        self.enable_llm_reflection = self.validation_manager.is_llm_reflection_enabled()
        
        logger.info(f"[validate] 已加载校验配置")
        logger.info(f"  - 禁忌症规则: {len(self.contraindication_rules)} 个治疗方式")
        logger.info(f"  - 最大反思次数: {self.max_reflection_count}")
        logger.info(f"  - 规则引擎: {'启用' if self.enable_rule_engine else '禁用'}")
        logger.info(f"  - LLM反思: {'启用' if self.enable_llm_reflection else '禁用'}")

    async def run(self, state: ClinicalState) -> Dict:
        """
        执行双层校验

        工作流程：
        1. 静态规则引擎检查禁忌症（如果启用）
        2. 如果规则检查通过，进行LLM动态反思（如果启用）
        3. 根据校验结果决定是否通过或需要重新推理

        参数：
        - state: 临床状态对象，包含病例、提案、证据等

        返回：
        - Dict: 包含校验结果和反馈信息的字典
        """
        logger.info(f"[validate] 开始后层结果校验，当前已反思次数: {state['reflection_count']}")
        logger.info(f"[validate] 提案长度: {len(state['proposal']) if state['proposal'] else 0}")
        logger.info(f"[validate] 最大反思次数: {self.max_reflection_count}")
        
        # 第一层：静态规则引擎检查（如果启用）
        if self.enable_rule_engine:
            logger.info(f"[validate] 开始规则引擎检查")
            rule_feedback = await self._rule_engine_check(state)
            if rule_feedback:
                logger.warning(f"[validate] 规则引擎检查失败: {rule_feedback}")
                return self._fail_state(state, rule_feedback)
            logger.info(f"[validate] 规则引擎检查通过")
        else:
            logger.info("[validate] 规则引擎已禁用，跳过规则检查")

        # 第二层：动态LLM反思校验（如果启用）
        if self.enable_llm_reflection:
            logger.info(f"[validate] 开始LLM反思检查")
            return await self._llm_reflection_check(state)
        else:
            logger.info("[validate] LLM反思已禁用，默认通过")
            return {"validation_passed": True, "validation_feedback": ""}

    async def _rule_engine_check(self, state: ClinicalState) -> str:
        """
        静态规则引擎检查

        参数：
        - state: 临床状态对象

        返回：
        - str: 触发的规则反馈信息，如果没有触发则返回空字符串
        """
        # 快速匹配动态加载的禁忌症规则
        rule_feedback = []
        for treatment, rules in self.contraindication_rules.items():
            # 检查提案中是否包含该治疗方式
            if treatment in state['proposal']:
                # 检查是否存在禁忌症
                for rule in rules:
                    # 在病例文本和证据中搜索禁忌症关键词
                    if rule in state['case_text'] or rule in state['evidence']:
                        rule_feedback.append(
                            f"触发[{treatment}]禁忌症硬规则拦截: 检测到【{rule}】的冲突证据。"
                        )
        
        return " \n".join(rule_feedback) if rule_feedback else ""

    async def _llm_reflection_check(self, state: ClinicalState) -> Dict:
        """
        动态LLM反思校验

        参数：
        - state: 临床状态对象

        返回：
        - Dict: 包含校验结果的字典
        """
        # 通过LLM进行深层次的医学逻辑审查
        reflection_prompt = f"""作为院级独立医学伦理与质控审查专家，请校验以下治疗提案是否存在严重致命错误或禁忌症遗漏。只检查致命错误或明显的医学指南违反。

【患者输入】:
{state['case_text']}
【当前综合方案 Proposal】: 
{state['proposal']}

判断要求：
如果没有严重问题，请回复 "PASS"。
如果存在致命禁忌症未能发现或违背常识的建议，请回复 "REJECT: "，并紧接详细的驳回理由。"""
        
        try:
            # 调用LLM进行反思校验
            res = await self.llm.ainvoke([
                SystemMessage(content="你是严厉的医疗质控审查员。"), 
                HumanMessage(content=reflection_prompt)
            ])
            verdict = getattr(res, "content", "PASS").strip()
            
            # 解析校验结果
            if verdict.startswith("REJECT"):
                # LLM认为存在严重问题，驳回提案
                return self._fail_state(state, verdict)
            elif "PASS" in verdict:
                # 通过校验
                logger.info("[validate] 方案已通过质控审查")
                return {"validation_passed": True, "validation_feedback": ""}
            else:
                # 模糊回复，默认放行交由人工兜底
                logger.warning(f"[validate] 审查结果模糊: {verdict}. 默认PASS")
                return {"validation_passed": True, "validation_feedback": ""}
                
        except Exception as e:
            # 异常处理：LLM调用失败，默认放行避免阻塞
            logger.error(f"[validate] Reflection 调用异常: {e}，默认放行")
            return {"validation_passed": True, "validation_feedback": ""}

    def _fail_state(self, state: ClinicalState, reason: str) -> Dict:
        """
        生成校验失败状态

        参数：
        - state: 当前临床状态
        - reason: 失败原因

        返回：
        - Dict: 包含校验失败信息的字典
        """
        new_reflection_count = state['reflection_count'] + 1
        logger.warning(f"[validate] 方案被驳回! 理由: {reason}")
        logger.warning(f"[validate] 当前反思次数: {state['reflection_count']} -> {new_reflection_count}")
        logger.warning(f"[validate] 最大反思次数: {self.max_reflection_count}")
        
        result = {
            "validation_passed": False,
            "validation_feedback": reason,
            "reflection_count": new_reflection_count  # 增加反思次数
        }
        
        # 保留之前的推理结果，避免重新推理时丢失
        if state['proposal']:
            result["proposal"] = state['proposal']
        if state['critique']:
            result["critique"] = state['critique']
            
        logger.info(f"[validate] 返回失败状态，保留推理结果")
        return result