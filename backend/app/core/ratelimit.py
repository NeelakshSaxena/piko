"""In-process sliding-window rate limiter.

Per-process by design (single-instance self-hosting). A multi-instance deployment needs a shared
store; durable limits that must survive restarts (login lockout) live in the database instead.
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

MAX_KEYS = 50_000


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(
        self, bucket: str, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        """Record a hit. Returns (allowed, remaining, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                self._evict(now, window_seconds)
            hits = self._hits[(bucket, key)]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry = max(1, int(window_seconds - (now - hits[0])) + 1)
                return False, 0, retry
            hits.append(now)
            return True, limit - len(hits), 0

    def _evict(self, now: float, window_seconds: int) -> None:
        stale = [k for k, h in self._hits.items() if not h or now - h[-1] >= window_seconds]
        for k in stale:
            del self._hits[k]
