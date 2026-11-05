"""Sliding-window rate limiter (SEC-API-02).

In-memory and per-process: perfect for one instance and for the tests. For a
multi-instance deployment swap `_hits` for Redis (INCR + EXPIRE / sorted sets);
the interface (`hit`) stays the same. Documented in docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import get_settings


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        """Register a hit. Returns None if allowed, else seconds until retry."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= window_seconds:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(window_seconds - (now - q[0])) + 1)
            q.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    """Client IP. X-Forwarded-For is only honoured behind a *known* number of proxies,
    otherwise any client could spoof it to dodge rate limits / poison audit logs."""
    n = get_settings().trusted_proxy_count
    if n > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= n:
            return parts[-n]
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit_attr: str, window_seconds: int):
    """FastAPI dependency factory. `limit_attr` is read lazily from settings."""

    def dependency(request: Request) -> None:
        s = get_settings()
        if not s.rate_limit_enabled:
            return
        retry = limiter.hit(f"{name}:{client_ip(request)}", getattr(s, limit_attr), window_seconds)
        if retry is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests. Please try again later.",
                headers={"Retry-After": str(retry)},
            )

    return dependency
