import os
import asyncio
import json
import logging
from http import HTTPStatus

import dashscope

logger = logging.getLogger(__name__)

# 四维健康风险审查提示词
_RISK_ANALYSIS_PROMPT = """你是一位资深三甲医院全科医生，具备神经内科、心血管科专业背景。
请根据以下患者信息，进行系统性健康风险审查，给出专业意见。

患者信息：
{patient_info}

请从以下四个维度进行分析，每个维度简洁、专业：

1. 当前健康状况评估
   - 主要异常指标及临床意义
   - 整体风险等级（低风险 / 中风险 / 高风险）

2. 可能存在的风险因素
   - 列举 2~4 个主要风险点，按严重程度排序

3. 建议的进一步检查或处置方向
   - 优先级最高的 1~2 项检查或会诊建议

4. 日常生活与饮食建议
   - 可执行的具体建议，避免笼统表述

输出严格遵循以下 JSON 格式，不包含 markdown 代码块：

{{
    "riskLevel": "低风险/中风险/高风险",
    "suggestion": "最重要的处置建议（1~2句）",
    "analysisDetails": "健康状况评估摘要（80字以内）",
    "riskFactors": ["风险点1", "风险点2"],
    "examSuggestions": "建议检查方向（1句）",
    "lifestyleAdvice": "生活饮食建议（1~2句）"
}}

要求：
- riskLevel 必须是"低风险"、"中风险"、"高风险"之一
- 禁止给出明确诊断；禁止提及具体药物剂量"""


class HealthRiskAnalyzer:
    """独立健康风险分析模块，直接调用 DashScope API，不依赖 LangChain 链路。"""

    def __init__(self, model: str = "qwen-plus", api_key: str = None):
        # 使用独立的模型实例，不复用主推理链中的 llm_proposer/llm_critic
        self.model = model
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")

    async def analyze(self, patient_data: str) -> dict:
        """异步入口：将同步 DashScope 调用包装为 async，供 FastAPI 路由调用。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_analyze, patient_data)

    def _sync_analyze(self, patient_data: str) -> dict:
        """同步调用 DashScope Generation API，执行四维健康风险分析。"""
        prompt = _RISK_ANALYSIS_PROMPT.format(patient_info=patient_data)

        response = dashscope.Generation.call(
            model=self.model,
            api_key=self.api_key,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.3,
            result_format="message",
        )

        if response.status_code != HTTPStatus.OK:
            logger.error(
                f"[HealthRiskAnalyzer] DashScope 调用失败: "
                f"status={response.status_code} code={response.code} msg={response.message}"
            )
            return self._fallback()

        content = response.output.choices[0].message.content
        result = self._parse_json(content)
        if not result:
            return self._fallback()

        # 归一化 riskLevel 简写（如"高" → "高风险"）
        _normalize = {"高": "高风险", "中": "中风险", "低": "低风险"}
        if result.get("riskLevel") in _normalize:
            result["riskLevel"] = _normalize[result["riskLevel"]]

        logger.info(f"[HealthRiskAnalyzer] 分析完成 riskLevel={result.get('riskLevel')}")
        return result

    def _parse_json(self, text: str) -> dict:
        """从模型输出中提取 JSON，兼容带 markdown 代码块的情况。"""
        try:
            stripped = text.strip()
            # 去掉 ```json ... ``` 包装
            if stripped.startswith("```"):
                parts = stripped.split("```")
                stripped = parts[1] if len(parts) > 1 else stripped
                if stripped.startswith("json"):
                    stripped = stripped[4:]
            return json.loads(stripped.strip())
        except Exception:
            logger.warning(f"[HealthRiskAnalyzer] JSON 解析失败，原始输出片段: {text[:300]}")
            return {}

    @staticmethod
    def _fallback() -> dict:
        """API 调用或解析失败时的兜底返回。"""
        return {
            "riskLevel": "中风险",
            "suggestion": "建议结合线下检查结果进一步评估，如症状加重请及时就医。",
            "analysisDetails": "系统已完成基础风险评估，但详细分析生成失败，请结合临床实际判断。",
            "riskFactors": [],
            "examSuggestions": "",
            "lifestyleAdvice": "",
        }
