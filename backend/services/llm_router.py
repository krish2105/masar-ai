"""Model routing with graceful degradation.

Requests are routed by **task class**, not by model preference: intent routing
wants the lowest time-to-first-token, Text-to-SQL wants codegen quality, and
grading is high-volume so it wants cheap. `config/models.yaml` declares an
ordered fallback chain per class.

The router walks that chain, skipping providers whose key is absent, whose
token bucket is exhausted, or which are serving a penalty from a recent 429. If
every cloud provider is unavailable it falls through to local Ollama and sets
`degraded_mode` on the response so the UI can badge it honestly.

The rule this enforces: **a user request never fails because a free tier ran
out.** Degrading visibly is always better than failing, and both are better than
degrading silently.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from backend.config.settings import get_model_config, get_settings
from backend.services.logging import get_logger
from backend.services.rate_limiter import Limits, RateLimiter

log = get_logger(__name__)


class AllProvidersFailed(RuntimeError):
    """Every provider in the chain failed, including the local fallback."""


@dataclass(slots=True)
class Completion:
    text: str
    provider: str
    model: str
    latency_ms: float
    tokens_in: int = 0
    tokens_out: int = 0
    degraded: bool = False
    """True when the answer came from a local model because cloud was unavailable."""

    attempts: list[dict[str, Any]] = field(default_factory=list)
    """Every provider tried and why it was skipped or failed — for the trace viewer."""

    cost_estimate_usd: float = 0.0

    def as_trace(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 1),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_estimate_usd": self.cost_estimate_usd,
            "degraded": self.degraded,
            "attempts": self.attempts,
        }


class LLMRouter:
    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        settings = get_settings()
        self.settings = settings
        self.config = get_model_config()
        self.providers: dict[str, dict] = self.config["providers"]
        self.task_classes: dict[str, dict] = self.config["task_classes"]
        self.limiter = rate_limiter or RateLimiter(settings.redis_url)
        self._warned: set[str] = set()

    # --------------------------------------------------------- availability --
    def _api_key(self, provider: str) -> str | None:
        spec = self.providers.get(provider, {})
        env_key = spec.get("env_key")
        if not env_key:
            return None
        return getattr(self.settings, env_key.lower(), None)

    def _is_local(self, provider: str) -> bool:
        return bool(self.providers.get(provider, {}).get("local"))

    def _configured(self, provider: str) -> bool:
        return self._is_local(provider) or bool(self._api_key(provider))

    async def _available(self, provider: str) -> tuple[bool, str]:
        if not self._configured(provider):
            return False, "no API key configured"
        if self._is_local(provider):
            return True, ""
        if await self.limiter.is_penalised(provider):
            return False, "serving penalty after a recent 429"
        limits = Limits.from_config(self.providers[provider].get("rate_limits"))
        state = await self.limiter.check(provider, limits)
        return state.allowed, state.reason

    # ------------------------------------------------------------- dispatch --
    def _litellm_model(self, provider: str, model: str) -> str:
        prefix = self.providers[provider]["litellm_prefix"]
        return f"{prefix}/{model}"

    async def _call(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
        json_mode: bool,
    ) -> tuple[str, int, int]:
        import litellm

        litellm.suppress_debug_info = True

        kwargs: dict[str, Any] = {
            "model": self._litellm_model(provider, model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        }
        if api_key := self._api_key(provider):
            kwargs["api_key"] = api_key
        if self._is_local(provider):
            kwargs["api_base"] = self.settings.ollama_base_url
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await litellm.acompletion(**kwargs)
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        return (
            text,
            int(getattr(usage, "prompt_tokens", 0) or 0),
            int(getattr(usage, "completion_tokens", 0) or 0),
        )

    async def complete(
        self,
        task_class: str,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float = 60.0,
        json_mode: bool = False,
    ) -> Completion:
        """Run a completion for `task_class`, walking its fallback chain."""
        spec = self.task_classes.get(task_class)
        if spec is None:
            raise KeyError(
                f"unknown task class {task_class!r}; known: {', '.join(self.task_classes)}"
            )

        temperature = spec.get("temperature", 0.0) if temperature is None else temperature
        max_tokens = spec.get("max_tokens", 1024) if max_tokens is None else max_tokens

        attempts: list[dict[str, Any]] = []
        started = time.perf_counter()

        for step in spec["chain"]:
            provider, model = step["provider"], step["model"]

            available, reason = await self._available(provider)
            if not available:
                attempts.append({"provider": provider, "model": model, "skipped": reason})
                if "no API key" in reason and provider not in self._warned:
                    self._warned.add(provider)
                    log.info("router.provider_unconfigured", provider=provider, task=task_class)
                continue

            attempt_started = time.perf_counter()
            try:
                text, tokens_in, tokens_out = await self._call(
                    provider,
                    model,
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    json_mode=json_mode,
                )
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                attempts.append({"provider": provider, "model": model, "error": message[:200]})
                if "429" in message or "rate" in message.lower():
                    await self.limiter.penalise(provider)
                log.warning(
                    "router.attempt_failed",
                    provider=provider,
                    model=model,
                    task=task_class,
                    error=message[:160],
                )
                continue

            await self.limiter.record(provider, tokens=tokens_in + tokens_out)
            latency = (time.perf_counter() - attempt_started) * 1000
            attempts.append(
                {
                    "provider": provider,
                    "model": model,
                    "ok": True,
                    "latency_ms": round(latency, 1),
                }
            )

            degraded = self._is_local(provider)
            if degraded:
                log.warning(
                    "router.degraded",
                    task=task_class,
                    detail="answered locally because no cloud provider was available",
                )

            return Completion(
                text=text,
                provider=provider,
                model=model,
                latency_ms=(time.perf_counter() - started) * 1000,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                degraded=degraded,
                attempts=attempts,
                cost_estimate_usd=0.0,  # free tier and local — shown anyway
            )

        raise AllProvidersFailed(
            f"every provider failed for task class {task_class!r}: {json.dumps(attempts)}"
        )

    async def complete_json(
        self,
        task_class: str,
        messages: list[dict[str, str]],
        *,
        retries: int = 1,
        **kwargs,
    ) -> tuple[dict[str, Any], Completion]:
        """Completion that must parse as JSON.

        Models wrap JSON in prose and code fences regardless of instruction, so
        the response is salvaged before being declared invalid. On a genuine
        parse failure the malformed output is fed back once — repair succeeds
        far more often than a blind retry.
        """
        last_error = ""
        for attempt in range(retries + 1):
            local_messages = list(messages)
            if attempt and last_error:
                local_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was not valid JSON ({last_error}). "
                            "Reply with valid JSON only — no prose, no code fences."
                        ),
                    }
                )

            completion = await self.complete(task_class, local_messages, json_mode=True, **kwargs)
            try:
                return _extract_json(completion.text), completion
            except ValueError as exc:
                last_error = str(exc)
                log.warning(
                    "router.json_parse_failed",
                    task=task_class,
                    attempt=attempt,
                    error=last_error[:120],
                )

        raise AllProvidersFailed(
            f"could not obtain valid JSON for task class {task_class!r}: {last_error}"
        )

    async def aclose(self) -> None:
        await self.limiter.aclose()


def _extract_json(text: str) -> dict[str, Any]:
    """Recover a JSON object from a model response."""
    candidate = text.strip()

    if candidate.startswith("```"):
        candidate = candidate.split("```", 2)[1] if candidate.count("```") >= 2 else candidate
        if candidate.lstrip().startswith(("json", "JSON")):
            candidate = candidate.lstrip()[4:]
        candidate = candidate.strip()

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost balanced braces.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise ValueError(f"unbalanced or malformed JSON: {exc}") from exc

    raise ValueError("no JSON object found in response")


_router: LLMRouter | None = None
_router_lock = asyncio.Lock()


async def get_router() -> LLMRouter:
    global _router
    async with _router_lock:
        if _router is None:
            _router = LLMRouter()
        return _router
