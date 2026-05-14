import logging
import json
import re
from typing import Tuple

from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def safe_truncate(text: str, max_len: int = 1200) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + " ..."

def parse_score_response(raw_text: str, default_score: float = 0.0) -> Tuple[float, str]:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return default_score, "empty response"

    try:
        data = json.loads(raw_text)
        score = float(data.get("score", default_score))
        reason = str(data.get("reason", ""))
        return max(0.0, min(1.0, score)), reason
    except Exception:
        pass

    match = re.search(r"(0(?:\.\d+)?|1(?:\.0+)?)", raw_text)
    if match:
        try:
            score = float(match.group(1))
            return max(0.0, min(1.0, score)), raw_text
        except Exception:
            pass
    return default_score, raw_text

class ConversationSummaryService:
    def __init__(self, llm=None, prompt_manager=None):
        self.llm = llm
        self.prompts = prompt_manager

    def _get_prompt(self, key: str, fallback: str, **kwargs) -> str:
        if self.prompts:
            prompt = self.prompts.get(key, **kwargs)
            if prompt:
                return prompt
        try:
            return fallback.format(**kwargs)
        except Exception:
            return fallback

    def score_turn_value(self, question: str, answer: str, previous_all_info: str = "") -> Tuple[float, str]:
        answer = (answer or "").strip()
        if not answer:
            return 0.0, "empty answer"

        fallback_prompt = """你是对话价值评估器。请判断下面这一轮问答是否值得写入长期病历摘要。

【历史摘要】
{previous_all_info}

【本轮问题】
{question}

【本轮回答】
{answer}

评分标准：
- 1.0：包含关键病情变化、重要检查、治疗决策、风险提示、明确随访建议
- 0.6：包含有价值的症状、病史、鉴别诊断、下一步检查建议
- 0.2：主要是泛泛解释、重复信息、礼貌性补充
- 0.0：无医学价值或与病情无关

只输出 JSON：
{{"score": 0.0-1.0, "reason": "一句话原因"}}"""

        prompt = self._get_prompt(
            "conversation_value_score",
            fallback_prompt,
            previous_all_info=safe_truncate(previous_all_info),
            question=safe_truncate(question),
            answer=safe_truncate(answer)
        )

        if not self.llm:
            heuristic_score = 0.2
            keywords = ["建议", "风险", "检查", "复查", "病史", "症状", "体征", "处理", "治疗"]
            hit_count = sum(1 for word in keywords if word in answer)
            if hit_count >= 3:
                heuristic_score = 0.7
            elif hit_count >= 1:
                heuristic_score = 0.5
            if len(answer) > 120:
                heuristic_score = max(heuristic_score, 0.6)
            return heuristic_score, "heuristic score"

        try:
            # 使用 StrOutputParser 链，替代手写 getattr(response, "content", response)
            chain = self.llm | StrOutputParser()
            content = chain.invoke(prompt)
            return parse_score_response(content, default_score=0.0)
        except Exception as e:
            logger.warning(f"对话价值评分失败，使用启发式评分: {e}")
            return 0.5 if len(answer) > 80 else 0.2, "fallback heuristic"

    def summarize_context(self, previous_all_info: str, question: str, answer: str) -> str:
        fallback_prompt = """你是病历摘要整理助手。请把旧摘要与本轮有价值问答合并成新的 all_info。

要求：
1. 只保留对后续问诊有帮助的信息
2. 优先保留：主诉、症状演变、检查结果、重要病史、危险因素、处理建议、随访建议
3. 删除重复、寒暄、无价值表述
4. 输出 3-6 条中文要点，每条独立，简洁清晰
5. 不要输出 markdown 标题

【旧摘要】
{previous_all_info}

【本轮问题】
{question}

【本轮回答】
{answer}
"""

        prompt = self._get_prompt(
            "conversation_summary_merge",
            fallback_prompt,
            previous_all_info=safe_truncate(previous_all_info, 1800),
            question=safe_truncate(question, 800),
            answer=safe_truncate(answer, 1800)
        )

        if not self.llm:
            parts = []
            if previous_all_info.strip():
                parts.append(previous_all_info.strip())
            parts.append(f"本轮问题：{question.strip()}")
            parts.append(f"本轮结论：{answer.strip()}")
            return "\n".join(parts).strip()

        try:
            chain = self.llm | StrOutputParser()
            merged = chain.invoke(prompt).strip()
            return merged or previous_all_info
        except Exception as e:
            logger.warning(f"摘要合并失败，回退拼接策略: {e}")
            parts = [p for p in [previous_all_info.strip(), f"本轮问题：{question.strip()}", f"本轮结论：{answer.strip()}"] if p]
            return "\n".join(parts).strip()

    def update_all_info(self, previous_all_info: str, question: str, answer: str, threshold: float = 0.4):
        score, reason = self.score_turn_value(question, answer, previous_all_info)
        is_valuable = score > threshold
        updated_all_info = previous_all_info.strip()

        if is_valuable:
            updated_all_info = self.summarize_context(previous_all_info, question, answer)

        return {
            "score": score,
            "reason": reason,
            "is_valuable": is_valuable,
            "updated_all_info": updated_all_info
        }
