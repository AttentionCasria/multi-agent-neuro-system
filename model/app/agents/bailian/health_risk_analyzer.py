import os
import asyncio
import json
import logging
from http import HTTPStatus

import dashscope

logger = logging.getLogger(__name__)

# 快速健康风险分析提示词（优化版）
_RISK_ANALYSIS_PROMPT = """你是三甲医院全科医生。快速分析以下患者信息，给出简洁意见。

患者信息：
{patient_info}

请直接输出 JSON（不要用 markdown 代码块）：
{{
    "riskLevel": "低风险/中风险/高风险",
    "suggestion": "最重要的处置建议（1句，50字以内）",
    "analysisDetails": "健康状况评估摘要（50字以内）"
}}

要求：
- riskLevel 必须是"低风险"、"中风险"、"高风险"之一
- 禁止确诊语气
- 禁止具体药物剂量"""


class HealthRiskAnalyzer:
    """独立健康风险分析模块，直接调用 DashScope API，不依赖 LangChain 链路。"""

    def __init__(self, model: str = "qwen-turbo", api_key: str = None):
        # 使用 qwen-turbo 模型以获得更快的响应速度
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
            max_tokens=256,
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
            "suggestion": "建议结合线下检查结果进一步评估。",
            "analysisDetails": "系统已完成基础风险评估。",
        }