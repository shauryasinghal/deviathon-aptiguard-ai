"""Small in-process sliding-window limiter for login failures (single-instance prototype).

Multi-instance deployments need a shared store (e.g. Redis); documented in docs/security-review.md.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class FailureLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window: int, now: float) -> deque[float]:
        q = self._events[key]
        while q and now - q[0] > window:
            q.popleft()
        return q

    def retry_after(self, key: str, limit: int, window: int) -> int:
        """Seconds until another attempt is allowed (0 = allowed)."""
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, window, now)
            return int(window - (now - q[0])) + 1 if len(q) >= limit else 0

    def fail(self, key: str) -> None:
        with self._lock:
            self._events[key].append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


login_limiter = FailureLimiter()
