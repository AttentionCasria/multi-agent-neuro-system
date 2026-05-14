

import asyncio
import traceback
from datetime import datetime, timezone
from enum import Enum


class ModelErrorCode(Enum):
    E1001 = ("E1001", "推理超时, 已达 120s 上限", True)
    E1002 = ("E1002", "模型拒绝回答", False)
    E1003 = ("E1003", "模型内存不足 (OOM)", True)
    E1099 = ("E1099", "未知错误", False)

    def __init__(self, code: str, default_message: str, retryable: bool):
        self.code = code
        self.default_message = default_message
        self.retryable = retryable


def classify_exception(exc: Exception) -> ModelErrorCode:
    if isinstance(exc, asyncio.TimeoutError):
        return ModelErrorCode.E1001
    if isinstance(exc, MemoryError):
        return ModelErrorCode.E1003
    exc_msg = str(exc).lower()
    if any(kw in exc_msg for kw in ("safety", "sensitive", "违禁", "安全拒绝", "内容违规")):
        return ModelErrorCode.E1002
    return ModelErrorCode.E1099


def build_error_event(exc: Exception, talk_id=None) -> dict:
    error_code = classify_exception(exc)
    return {
        "type": "error",
        "talkId": talk_id,
        "content": str(exc),
        "error": {
            "code": error_code.code,
            "message": error_code.default_message,
            "retryable": error_code.retryable,
            "detail": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
    }


def format_error_log(exc: Exception) -> str:
    return (
        f"异常类型: {type(exc).__name__} | "
        f"消息: {exc} | "
        f"堆栈:\n{traceback.format_exc()}"
    )
