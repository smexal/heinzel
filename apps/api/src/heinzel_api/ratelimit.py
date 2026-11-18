"""Rate limits per client address, fixed windows in Valkey.

If Valkey is unreachable the limiter lets requests through and logs a warning: account
lockout still protects passwords, and a cache outage must not stop all logins.
"""

import logging
import threading
import time
from dataclasses import dataclass

import redis

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limit:
    name: str
    max_hits: int
    window_s: int


LOGIN = Limit("login", 20, 15 * 60)
PASSWORD_FORGOT = Limit("forgot", 5, 15 * 60)
TOKEN = Limit("token", 30, 15 * 60)


class RateLimiter:
    def hit(self, limit: Limit, key: str) -> int | None:
        """Count one hit. Returns None if allowed, else seconds until the window ends."""
        raise NotImplementedError


class ValkeyRateLimiter(RateLimiter):
    def __init__(self, url: str):
        self._client = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    def hit(self, limit: Limit, key: str) -> int | None:
        window = int(time.time() // limit.window_s)
        k = f"heinzel:rl:{limit.name}:{key}:{window}"
        try:
            pipe = self._client.pipeline()
            pipe.incr(k)
            pipe.expire(k, limit.window_s)
            count = pipe.execute()[0]
        except redis.RedisError as e:
            log.warning("rate limiter unavailable, allowing request: %s", e)
            return None
        if count > limit.max_hits:
            return limit.window_s - int(time.time() % limit.window_s)
        return None


class MemoryRateLimiter(RateLimiter):
    """Process-local limiter for tests."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def hit(self, limit: Limit, key: str) -> int | None:
        window = int(time.time() // limit.window_s)
        k = f"{limit.name}:{key}:{window}"
        with self._lock:
            self._counts[k] = self._counts.get(k, 0) + 1
            count = self._counts[k]
        return limit.window_s if count > limit.max_hits else None
