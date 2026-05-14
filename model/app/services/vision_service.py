
import asyncio
import logging
import os
import threading
from typing import AsyncGenerator, List

from dashscope import MultiModalConversation

logger = logging.getLogger(__name__)

_KEYWORDS_REPORT = ["报告", "化验", "检验", "检查", "验血", "血常规", "尿常规", "生化", "结果单", "单子"]
_KEYWORDS_DRUG = ["药", "药品", "药物", "什么药", "药盒", "说明书", "处方", "片", "胶囊", "药名"]

_STREAM_DONE = object()


class VisionAnalysisService:

    def __init__(self, prompt_manager):
        self.prompt_manager = prompt_manager
        self._api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self._api_key:
            logger.warning("⚠️ 未找到 DASHSCOPE_API_KEY，影像分析功能将不可用")

    def _detect_image_type(self, question: str) -> str:
        q = question.lower()
        if any(kw in q for kw in _KEYWORDS_REPORT):
            return "image_report"
        if any(kw in q for kw in _KEYWORDS_DRUG):
            return "image_drug"
        return "image_general"

    def _build_messages(
        self,
        images: List[str],
        question: str,
        all_info: str,
        system_text: str,
        user_prefix: str,
    ) -> list:
        messages = []

        if system_text and system_text.strip():
            messages.append({
                "role": "system",
                "content": [{"text": system_text.strip()}]
            })

        user_content = []
        for img in images:
            url = img if img.startswith("data:") else f"data:image/jpeg;base64,{img}"
            user_content.append({"image": url})

        patient_context = f"患者信息：{all_info.strip()}" if all_info and all_info.strip() else ""
        user_text = "\n\n".join(filter(None, [patient_context, user_prefix, question])).strip()
        user_content.append({"text": user_text})

        messages.append({"role": "user", "content": user_content})
        return messages

    def _run_sync_stream(self, messages: list, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        def put(item):
            asyncio.run_coroutine_threadsafe(queue.put(item), loop)

        try:
            response = MultiModalConversation.call(
                model="qwen-vl-max",
                api_key=self._api_key,
                messages=messages,
                stream=True,
                incremental_output=True,
            )
            for chunk in response:
                if chunk.status_code != 200:
                    put(Exception(f"API 错误 {chunk.status_code}: {getattr(chunk, 'message', '')}"))
                    return
                try:
                    content_list = chunk.output.choices[0].message.content
                    for item in content_list:
                        text = item.get("text", "")
                        if text:
                            put(text)
                except (AttributeError, IndexError, KeyError):
                    continue

        except Exception as e:
            put(e)
        finally:
            put(_STREAM_DONE)

    async def analyze_stream(
        self, images: List[str], question: str, all_info: str
    ) -> AsyncGenerator[dict, None]:
        image_type = self._detect_image_type(question)
        logger.info(f"影像分析意图: {image_type}，图片数量: {len(images)}")

        if image_type == "image_report":
            system_text = self.prompt_manager.get("image_report_system") or _DEFAULT_REPORT_SYSTEM
            user_prefix = "请分析以下检验报告单图片。"
        elif image_type == "image_drug":
            system_text = self.prompt_manager.get("image_drug_system") or _DEFAULT_DRUG_SYSTEM
            user_prefix = "请识别以下药品包装照片并提供详细信息。"
        else:
            system_text = self.prompt_manager.get("image_general_system") or _DEFAULT_GENERAL_SYSTEM
            user_prefix = "请分析以下图片。"

        yield {
            "type": "thinking",
            "step": "Vision",
            "title": "🔍 正在分析图片...",
            "content": f"意图类型：{image_type}，共 {len(images)} 张图片，调用 Qwen VL 模型",
        }

        messages = self._build_messages(images, question, all_info, system_text, user_prefix)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        t = threading.Thread(
            target=self._run_sync_stream,
            args=(messages, queue, loop),
            daemon=True,
        )
        t.start()

        while True:
            item = await queue.get()
            if item is _STREAM_DONE:
                break
            if isinstance(item, Exception):
                logger.error(f"VL 模型调用失败: {item}", exc_info=False)
                yield {"type": "chunk", "content": f"图片分析失败，请稍后重试。（{type(item).__name__}: {item}）"}
                break
            yield {"type": "chunk", "content": item}

_DEFAULT_REPORT_SYSTEM = """\
你是一位三甲医院神经内科主任医师，正在阅读患者的检验报告单照片。

## 任务
请按以下步骤分析这张检验报告单：

### 第一步：OCR 识别
准确识别报告单上的所有文字和数值，以结构化表格形式列出：
- 检验项目名称、检测结果（含数值和单位）、参考范围、是否异常（用 ↑ 或 ↓ 标注）

### 第二步：异常指标解读
对所有超出参考范围的指标逐一解读：
- 该指标的临床意义、可能提示的疾病或状态、偏离程度评估（轻度/中度/重度）

### 第三步：综合分析
结合患者已知病情信息（如有），给出整体健康状况评估和进一步检查建议

## 安全约束
- 禁止给出确诊结论，使用"提示""可能""建议"等措辞
- 建议患者携带报告到相关科室就诊
- 如果图片模糊无法识别，明确告知用户"""

_DEFAULT_DRUG_SYSTEM = """\
你是一位临床药师，正在查看患者拍摄的药品包装照片。

## 任务
请按以下步骤分析这张药品照片：

### 第一步：基础识别
从包装上识别：药品通用名/商品名、规格、生产厂家、批准文号（如可见）

### 第二步：药品详细信息
基于识别出的药品，提供：适应症、用法用量、常见不良反应、禁忌症

### 第三步：用药安全提示
如果已知患者用药史，分析药物相互作用风险

## 安全约束
- 明确声明：药品使用请遵医嘱
- 如果无法从照片中准确识别药品，明确告知用户
- 禁止建议用户自行调整用药方案"""

_DEFAULT_GENERAL_SYSTEM = """\
你是一位三甲医院神经内科主任医师，请仔细分析用户上传的图片，结合患者病情信息给出专业回答。

## 安全约束
- 禁止给出确诊结论，使用"提示""可能""建议"等措辞
- 建议患者在专科医生指导下进一步评估"""
