from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """Small process-local limiter for sensitive endpoints such as login."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            for expired_key in list(self._attempts):
                if not self._attempts[expired_key] or self._attempts[expired_key][-1] <= cutoff:
                    del self._attempts[expired_key]
            if key not in self._attempts and len(self._attempts) >= 10_000:
                return False, self.window_seconds
            attempts = self._attempts[key]
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - attempts[0])))
                return False, retry_after
            attempts.append(now)
        return True, 0


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def create_request_id() -> str:
    return secrets.token_hex(16)
