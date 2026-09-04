"""In-process sliding-window rate limiter (per authenticated identity).

Pure logic lives in :class:`SlidingWindowLimiter` so it is unit-testable in
isolation; the ASGI middleware keys requests by identity headers (org+user)
when present, falling back to the client IP. Disabled entirely when
``RATE_LIMIT_PER_MINUTE=0`` (the test suite disables it via pytest.ini).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """Allow at most ``limit`` events per ``window_seconds`` sliding window."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> bool:
        """Record an event for ``key``; return True if allowed, False if limited."""
        if self.limit <= 0:
            return True
        now = time.monotonic() if now is None else now
        events = self._events[key]
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(now)
        return True

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Seconds until the oldest recorded event leaves the window (>=1)."""
        now = time.monotonic() if now is None else now
        events = self._events[key]
        if not events:
            return 1
        elapsed = now - events[0]
        return max(1, int(self.window_seconds - elapsed) + 1)


def identity_key(scope) -> str:
    """Best-effort identity for a request: auth headers when present, else IP."""
    headers = scope.get("headers") or []
    raw = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in headers}
    org = raw.get("x-organization-id", "")
    user = raw.get("x-user-id", "")
    if org and user:
        return f"{org}:{user}"
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    """ASGI middleware applying a SlidingWindowLimiter to every request."""

    def __init__(self, app, limiter: SlidingWindowLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or self.limiter.limit <= 0:
            await self.app(scope, receive, send)
            return
        key = identity_key(scope)
        if not self.limiter.check(key):
            retry = self.limiter.retry_after(key)
            body = b'{"detail":"Rate limit exceeded"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(retry).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
