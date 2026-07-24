"""Per-client-IP rate limiting for the expensive chat endpoints.

`POST /api/v1/chat` and `/chat/stream` both run the full agent graph — several
LLM calls per turn — against a shared free-tier budget. Without an edge cap, a
single client looping requests could exhaust the day's inference for every other
visitor before the router's own per-provider buckets have anything to skip.

This adds one cheap request-phase check, keyed by the caller's IP, in front of
those two routes. It is deliberately a FastAPI dependency rather than middleware:
a dependency resolves *before* the handler builds its response, so when it
rejects it returns a plain 429 and the SSE stream is simply never started —
there is no streaming response for it to interfere with.

It reuses the router's Redis limiter, which fails **open**: if Redis is down the
check allows the request and logs once. An abuse guard that takes chat offline
when its own dependency blips has inverted its purpose.
"""

from __future__ import annotations

import time

from fastapi import HTTPException, Request

from backend.config.settings import get_settings
from backend.services.logging import get_logger
from backend.services.rate_limiter import Limits, RateLimiter

log = get_logger(__name__)

# One limiter per process, sharing the same Redis as the provider buckets. Keyed
# under "edge:<ip>" so it never collides with the router's "<provider>" keys.
_limiter: RateLimiter | None = None


def _edge_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(get_settings().redis_url)
    return _limiter


def _client_ip(request: Request) -> str:
    """The caller's IP, correct behind exactly one trusted proxy (our Caddy).

    Prefer ``X-Real-IP``: the Caddyfile sets ``header_up X-Real-IP {remote_host}``,
    which *overwrites* the header with the true TCP peer on every request, so a
    client cannot spoof it — it is a single value we control, with none of the
    ordering ambiguity of ``X-Forwarded-For`` (multiple entries, or a folded vs.
    separate header line). Fall back to the *rightmost* XFF entry (the one Caddy
    appends is trustworthy even if the client forged left entries), then to the
    socket peer for a direct hit that never transited Caddy.
    """
    real = request.headers.get("x-real-ip")
    if real and real.strip():
        return real.strip()

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]

    return request.client.host if request.client else "unknown"


def _retry_after_seconds(reason: str, now: int | None = None) -> int:
    """How long until the tripped window resets, for the Retry-After header.

    The per-minute and per-day windows are fixed calendar windows, so the reset
    is deterministic: the top of the next minute, or the next UTC midnight. A
    daily-exhausted client told to retry in 60s would just 429 again for hours.
    ``now`` is injectable so the two branches can be tested without wall-clock
    flakiness near a window boundary.
    """
    now = int(time.time()) if now is None else now
    if "daily" in reason:
        return max(1, 86400 - now % 86400)
    return max(1, 60 - now % 60)


async def enforce_chat_rate_limit(request: Request) -> None:
    """Reject a caller that has exceeded its per-IP chat budget with a 429.

    No-op when both windows are disabled (either set to 0). Fail-open on any
    limiter/Redis error, inherited from ``RateLimiter.check``.
    """
    settings = get_settings()
    limits = Limits(
        rpm=settings.chat_rate_limit_rpm or None,
        rpd=settings.chat_rate_limit_rpd or None,
    )
    if limits.unlimited:
        return

    ip = _client_ip(request)
    key = f"edge:{ip}"

    state = await _edge_limiter().check(key, limits)
    if not state.allowed:
        log.info("edge_rate_limit.blocked", client=ip, reason=state.reason)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "message": "Too many requests from this client — please wait a moment and try again.",
                "reason": state.reason,
            },
            headers={"Retry-After": str(_retry_after_seconds(state.reason))},
        )

    # check() then record() is not atomic, so a simultaneous burst from one IP
    # can overshoot the per-minute cap by roughly its own concurrency. That is
    # fine here: the persistent daily counter is the real budget bound, and a box
    # this size saturates on graph work long before the LLM budget. The rpm cap
    # is a burst smoother, deliberately best-effort, not a hard gate.
    await _edge_limiter().record(key)
