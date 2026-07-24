"""Edge (per-client-IP) rate limiting on the chat endpoints.

Three properties matter, because this guard sits in front of the live chat path:

1. **Keying is spoof-resistant.** Behind our single Caddy hop the trustworthy
   client IP is the *rightmost* X-Forwarded-For entry. A client that forges the
   header must not be able to rotate the key and dodge the cap.
2. **It fails open and no-ops cleanly.** Disabled windows skip the limiter
   entirely; a limiter that allows (Redis down, or under budget) never raises.
3. **Over budget returns a real 429** with a Retry-After, not a 500 and not a
   broken stream.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api import rate_limit
from backend.services.rate_limiter import BucketState


def _request(headers: dict[str, str], peer: str = "5.6.7.8") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 12345),
    }
    return Request(scope)


class _FakeLimiter:
    """Stand-in for RateLimiter with a scripted check() and a record() counter."""

    def __init__(self, allowed: bool, reason: str = "") -> None:
        self._allowed = allowed
        self._reason = reason
        self.checked: list[str] = []
        self.recorded: list[str] = []

    async def check(self, key: str, limits) -> BucketState:  # noqa: ANN001
        self.checked.append(key)
        return BucketState(provider=key, allowed=self._allowed, reason=self._reason)

    async def record(self, key: str, *, tokens: int = 0) -> None:
        self.recorded.append(key)


class _Settings:
    def __init__(self, rpm: int, rpd: int) -> None:
        self.chat_rate_limit_rpm = rpm
        self.chat_rate_limit_rpd = rpd
        self.redis_url = "redis://unused"


@pytest.fixture
def wire(monkeypatch):
    """Inject a fake limiter + settings; return a helper to (re)configure them."""

    def _configure(*, allowed: bool = True, rpm: int = 12, rpd: int = 400, reason: str = ""):
        limiter = _FakeLimiter(allowed=allowed, reason=reason)
        monkeypatch.setattr(rate_limit, "_limiter", limiter)
        monkeypatch.setattr(rate_limit, "get_settings", lambda: _Settings(rpm, rpd))
        return limiter

    return _configure


# --- keying ----------------------------------------------------------------


def test_client_ip_prefers_x_real_ip_over_xff() -> None:
    # Caddy overwrites X-Real-IP with the true peer; it wins even if the client
    # also supplies a (forged) X-Forwarded-For.
    req = _request({"x-real-ip": "9.9.9.9", "x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    assert rate_limit._client_ip(req) == "9.9.9.9"


def test_client_ip_uses_rightmost_xff_when_no_real_ip() -> None:
    req = _request({"x-forwarded-for": "1.1.1.1, 2.2.2.2, 9.9.9.9"})
    assert rate_limit._client_ip(req) == "9.9.9.9"


def test_client_ip_ignores_a_forged_left_entry() -> None:
    # Client forges "1.2.3.4"; Caddy appends the real peer "9.9.9.9" on the right.
    req = _request({"x-forwarded-for": "1.2.3.4, 9.9.9.9"})
    assert rate_limit._client_ip(req) == "9.9.9.9"


def test_client_ip_falls_back_to_socket_peer() -> None:
    req = _request({}, peer="203.0.113.7")
    assert rate_limit._client_ip(req) == "203.0.113.7"


# --- no-op / fail-open -----------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_windows_are_a_noop(wire) -> None:
    limiter = wire(rpm=0, rpd=0)
    req = _request({"x-forwarded-for": "9.9.9.9"})
    assert await rate_limit.enforce_chat_rate_limit(req) is None
    assert limiter.checked == []  # limiter never consulted when disabled
    assert limiter.recorded == []


@pytest.mark.asyncio
async def test_under_budget_allows_and_records(wire) -> None:
    limiter = wire(allowed=True)
    req = _request({"x-forwarded-for": "1.2.3.4, 9.9.9.9"})
    await rate_limit.enforce_chat_rate_limit(req)  # no raise
    assert limiter.checked == ["edge:9.9.9.9"]
    assert limiter.recorded == ["edge:9.9.9.9"]  # counted against the real IP


# --- 429 path --------------------------------------------------------------


@pytest.mark.asyncio
async def test_over_budget_raises_429_with_minute_retry_after(wire) -> None:
    limiter = wire(allowed=False, reason="per-minute limit reached (12/12)")
    req = _request({"x-real-ip": "9.9.9.9"})
    with pytest.raises(HTTPException) as exc:
        await rate_limit.enforce_chat_rate_limit(req)
    assert exc.value.status_code == 429
    assert exc.value.detail["error"] == "rate_limited"
    retry = int(exc.value.headers["Retry-After"])
    assert 1 <= retry <= 60  # seconds to the top of the next minute
    assert limiter.recorded == []  # a rejected request is not recorded


def test_retry_after_seconds_windows() -> None:
    # Deterministic (injected clock): at epoch 1_000_000, next minute is +20s and
    # next UTC midnight is +36800s — so the daily window never collapses to a
    # misleading 60s, and the two branches are provably distinct.
    assert rate_limit._retry_after_seconds("per-minute limit reached", now=1_000_000) == 20
    assert rate_limit._retry_after_seconds("daily limit reached", now=1_000_000) == 36800
