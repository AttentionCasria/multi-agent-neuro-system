
import time
from typing import Optional


class TokenAggregator:


    def __init__(self, max_tokens: int = 20, max_wait_ms: int = 100):

        self.max_tokens = max_tokens
        self.max_wait = max_wait_ms / 1000.0
        self._buffer: list[str] = []
        self._last_flush: float = time.monotonic()


    def add(self, token: str) -> Optional[str]:
        self._buffer.append(token)
        if self._should_flush():
            return self._do_flush()
        return None

    def flush(self) -> Optional[str]:
        if not self._buffer:
            return None
        return self._do_flush()


    def _should_flush(self) -> bool:
        return (
            len(self._buffer) >= self.max_tokens
            or time.monotonic() - self._last_flush >= self.max_wait
        )

    def _do_flush(self) -> str:
        merged = "".join(self._buffer)
        self._buffer.clear()
        self._last_flush = time.monotonic()
        return merged
