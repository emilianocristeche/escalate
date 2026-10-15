"""Hardening for the public deploy: env flags, rate limiting, read-only mode.

All settings come from environment variables and are read per request, so
tests (and a redeploy with new env vars) need no code changes.

  ESCALATE_READ_ONLY=true        reject every write (POST /tickets, resolve)
  ESCALATE_WRITE_RATE_LIMIT=10   max writes per client IP per window (0 = off)
  ESCALATE_RATE_WINDOW_SEC=60    window length for the limit above
  ESCALATE_TRUST_PROXY=true      take the client IP from X-Forwarded-For
                                 (set on Render/any reverse proxy; otherwise
                                 every request looks like it comes from the proxy)
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def read_only() -> bool:
    return env_flag("ESCALATE_READ_ONLY")


def client_ip(request: Request) -> str:
    """Client address used as the rate-limit key.

    Behind a proxy, the *last* X-Forwarded-For entry is the address the proxy
    itself saw. Earlier entries are whatever the client chose to send, so they
    are ignored (otherwise anyone could dodge the limit with a fake header).
    """
    if env_flag("ESCALATE_TRUST_PROXY"):
        xff = request.headers.get("x-forwarded-for", "")
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """In-memory sliding-window limiter, keyed by client IP.

    State lives in the process: fine for a single small instance (Render free
    tier). With several workers/instances each one counts separately, so the
    effective limit multiplies; a shared store (Redis) would be the next step.
    """

    _MAX_KEYS = 10_000  # bound memory if many distinct IPs show up

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def check(self, key: str, limit: int, window: float) -> None:
        if limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > self._MAX_KEYS:
                self._prune(now, window)
            q = self._hits[key]
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, math.ceil(window - (now - q[0])))
                raise HTTPException(
                    status_code=429,
                    detail="rate limit exceeded",
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)

    def _prune(self, now: float, window: float) -> None:
        for key in [k for k, q in self._hits.items() if not q or now - q[-1] >= window]:
            del self._hits[key]


write_limiter = RateLimiter()


def guard_write(request: Request) -> None:
    """FastAPI dependency for every endpoint that creates or changes data."""
    if read_only():
        raise HTTPException(status_code=403, detail="read-only demo: writes are disabled")
    limit = int(os.getenv("ESCALATE_WRITE_RATE_LIMIT", "10"))
    window = float(os.getenv("ESCALATE_RATE_WINDOW_SEC", "60"))
    write_limiter.check(client_ip(request), limit, window)
