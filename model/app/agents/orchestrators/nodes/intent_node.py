"""
意图分类节点 - 用户输入类型识别模块

功能说明：
- 作为临床推理图的入口节点，负责识别用户输入的意图类型
- 根据输入内容路由到不同的处理流程
- 实现了类似医疗分诊的意图识别机制

工作流程：
1. 接收用户输入文本
2. 通过LLM判断输入类型（问诊/知识/无关）
3. 返回意图类型用于后续路由决策

设计模式：
- 分类器模式：将输入映射到预定义的类别
- 路由模式：为不同类型的输入选择不同的处理路径
"""

import logging
import json
from typing import Dict
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from app.agents.core.schema import ClinicalState
from app.agents.orchestrators.nodes.base import BaseNode

logger = logging.getLogger(__name__)

# 意图分类的Prompt模板（硬编码，建议移至配置文件）
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


class IntentNode(BaseNode):
    """
    意图分类节点 - 临床推理图的入口守门人

    职责：
    - 识别用户输入的意图类型
    - 为后续处理提供路由决策依据
    - 过滤无关输入，提高系统效率

    输入状态：
    - case_text: 用户输入的文本内容

    输出状态：
    - intent_type: 意图类型（consultation/knowledge/irrelevant）

    路由规则：
    - consultation → 进入完整临床推理流程
    - knowledge → 直接回答知识问题
    - irrelevant → 拒绝处理
    """

    def __init__(self, llm):
        """
        初始化意图分类节点

        参数：
        - llm: 大语言模型，用于意图分类
        """
        # 构建处理链：Prompt → LLM → 输出解析器
        self.chain = _INTENT_PROMPT | llm | StrOutputParser()

    async def run(self, state: ClinicalState) -> Dict:
        """
        执行意图分类

        工作流程：
        1. 调用LLM进行意图分类
        2. 解析JSON格式的分类结果
        3. 返回意图类型用于路由决策

        参数：
        - state: 临床状态对象，包含用户输入文本

        返回：
        - Dict: 包含意图类型的字典
        """
        # 调用LLM进行意图分类
        content = await self.chain.ainvoke({"case_text": state["case_text"]})
        
        # 解析JSON格式的分类结果
        result = self._parse_json(content)
        intent_type = result.get("type", "irrelevant")
        
        # 记录分类结果
        logger.info(f"[intent] 分类结果: {intent_type}")
        return {"intent_type": intent_type}

    def _parse_json(self, text: str):
        """
        解析LLM返回的JSON结果

        参数：
        - text: LLM返回的文本内容

        返回：
        - dict: 解析后的JSON对象，解析失败时返回默认值

        异常处理：
        - 如果JSON解析失败，默认返回"irrelevant"类型
        """
        try:
            return json.loads(text)
        except:
            # JSON解析失败，默认返回无关类型
            return {"type": "irrelevant"}