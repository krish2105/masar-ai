"""Per-provider token buckets backed by Redis.

Free tiers publish limits per minute and per day. Discovering them by receiving
a 429 mid-demo works, but it costs a round trip and a visible stall every time.
Tracking consumption locally lets the router skip an exhausted provider before
spending the request.

Redis is the store because buckets must be shared across worker processes — two
uvicorn workers each believing they have the full 30 RPM would produce 60.

Redis being unavailable is not fatal. The limiter fails **open**, allowing the
request and logging once. A rate limiter that takes the system down when its own
dependency is missing has inverted its purpose.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import redis.asyncio as aioredis

from backend.services.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class Limits:
    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None

    @classmethod
    def from_config(cls, config: dict | None) -> Limits:
        if not config:
            return cls()
        return cls(
            rpm=config.get("rpm"),
            rpd=config.get("rpd"),
            tpm=config.get("tpm"),
            tpd=config.get("tpd"),
        )

    @property
    def unlimited(self) -> bool:
        return not any((self.rpm, self.rpd, self.tpm, self.tpd))


@dataclass(slots=True)
class BucketState:
    provider: str
    allowed: bool
    reason: str = ""
    usage: dict[str, int] | None = None


class RateLimiter:
    """Fixed-window counters, one per provider and window.

    A fixed window can allow a burst across a boundary — up to 2× the nominal
    rate in the worst case. That is the correct trade here: free-tier limits are
    themselves approximate, the router has a fallback chain when one provider
    refuses, and a sliding-window log would cost more Redis round trips per
    request than the problem justifies.
    """

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url
        self._client: aioredis.Redis | None = None
        self._degraded = False

    async def _redis(self) -> aioredis.Redis | None:
        if self._degraded:
            return None
        if self._client is None:
            try:
                self._client = aioredis.from_url(
                    self.redis_url,
                    socket_connect_timeout=2,
                    # Bound per-command reads too. Without this a Redis that
                    # accepts the connection but stops answering (fsync stall,
                    # paused free-tier instance) would hang mget/execute forever
                    # — turning "fail open on a Redis blip" into a chat outage.
                    socket_timeout=2,
                    decode_responses=True,
                )
                await self._client.ping()
            except Exception as exc:
                log.warning(
                    "rate_limiter.degraded",
                    error=f"{type(exc).__name__}: {exc}",
                    detail="Redis unavailable — failing open, provider limits unenforced",
                )
                self._degraded = True
                self._client = None
        return self._client

    @staticmethod
    def _keys(provider: str) -> tuple[str, str]:
        now = time.time()
        minute = int(now // 60)
        day = int(now // 86400)
        return f"masar:rl:{provider}:m:{minute}", f"masar:rl:{provider}:d:{day}"

    async def check(self, provider: str, limits: Limits) -> BucketState:
        """Would a request to `provider` be within its published limits?"""
        if limits.unlimited:
            return BucketState(provider=provider, allowed=True, reason="unlimited")

        client = await self._redis()
        if client is None:
            return BucketState(provider=provider, allowed=True, reason="limiter degraded")

        minute_key, day_key = self._keys(provider)
        try:
            minute_count, day_count = await client.mget(minute_key, day_key)
            # Coerce inside the try: a timed-out read OR a corrupt/non-numeric
            # counter both fail open here, rather than a ValueError escaping as a
            # 500 on whatever request happens to be holding the limiter.
            minute_used = int(minute_count or 0)
            day_used = int(day_count or 0)
        except Exception as exc:
            log.warning("rate_limiter.read_failed", error=str(exc)[:100])
            return BucketState(provider=provider, allowed=True, reason="limiter error")

        usage = {"rpm_used": minute_used, "rpd_used": day_used}

        if limits.rpm is not None and minute_used >= limits.rpm:
            return BucketState(
                provider=provider,
                allowed=False,
                reason=f"per-minute limit reached ({minute_used}/{limits.rpm})",
                usage=usage,
            )
        if limits.rpd is not None and day_used >= limits.rpd:
            return BucketState(
                provider=provider,
                allowed=False,
                reason=f"daily limit reached ({day_used}/{limits.rpd})",
                usage=usage,
            )
        return BucketState(provider=provider, allowed=True, usage=usage)

    async def record(self, provider: str, *, tokens: int = 0) -> None:
        """Count a request that was actually sent."""
        client = await self._redis()
        if client is None:
            return

        minute_key, day_key = self._keys(provider)
        try:
            pipe = client.pipeline()
            pipe.incr(minute_key)
            pipe.expire(minute_key, 120)
            pipe.incr(day_key)
            pipe.expire(day_key, 172800)
            if tokens:
                pipe.incrby(f"{minute_key}:tok", tokens)
                pipe.expire(f"{minute_key}:tok", 120)
                pipe.incrby(f"{day_key}:tok", tokens)
                pipe.expire(f"{day_key}:tok", 172800)
            await pipe.execute()
        except Exception as exc:
            log.warning("rate_limiter.record_failed", error=str(exc)[:100])

    async def penalise(self, provider: str, *, seconds: int = 60) -> None:
        """Mark a provider unusable after a 429 the local count did not predict.

        Published limits and enforced limits differ. When the provider says no,
        believe the provider over the configuration.
        """
        client = await self._redis()
        if client is None:
            return
        try:
            await client.setex(f"masar:rl:{provider}:penalty", seconds, "1")
            log.warning("rate_limiter.penalised", provider=provider, seconds=seconds)
        except Exception:
            pass

    async def is_penalised(self, provider: str) -> bool:
        client = await self._redis()
        if client is None:
            return False
        try:
            return bool(await client.exists(f"masar:rl:{provider}:penalty"))
        except Exception:
            return False

    async def usage_report(self, providers: list[str]) -> dict[str, dict[str, int]]:
        """Current consumption, for /health and the trace viewer."""
        client = await self._redis()
        if client is None:
            return {}
        report: dict[str, dict[str, int]] = {}
        for provider in providers:
            minute_key, day_key = self._keys(provider)
            try:
                minute_count, day_count = await client.mget(minute_key, day_key)
                report[provider] = {
                    "rpm_used": int(minute_count or 0),
                    "rpd_used": int(day_count or 0),
                }
            except Exception:
                continue
        return report

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
