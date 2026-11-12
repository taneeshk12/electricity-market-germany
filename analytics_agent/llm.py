"""Thin Groq chat-completions wrapper that returns validated JSON.

Uses JSON mode (`response_format={"type": "json_object"}`); the caller validates the
shape with pydantic. Transient failures (rate limit, timeout, connection, 5xx) are
retried with exponential backoff, honouring `retry-after`. Permanent failures
(bad key, unknown model, bad request) fail fast. The API key is never logged.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import groq

from analytics_agent.config import LlmConfig

logger = logging.getLogger(__name__)

TRANSIENT = (groq.RateLimitError, groq.APITimeoutError, groq.APIConnectionError, groq.InternalServerError)


class LLMError(RuntimeError):
    """The LLM call failed (message is safe to show)."""


class LLMOutputError(LLMError):
    """The LLM answered, but not with the expected JSON."""


@dataclass
class LLMResponse:
    data: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    model: str


class JsonLLM(Protocol):
    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> LLMResponse: ...


def _retry_after(exc: Exception, default: float) -> float:
    response = getattr(exc, "response", None)
    try:
        return min(float(response.headers.get("retry-after")), 30.0)  # type: ignore[union-attr]
    except (AttributeError, TypeError, ValueError):
        return default


def parse_json_object(content: str | None) -> dict[str, Any]:
    if not content or not content.strip():
        raise LLMOutputError("empty response from the model")
    text = content.strip()
    if text.startswith("```"):  # tolerate fenced output
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"model did not return valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise LLMOutputError("model returned JSON that is not an object")
    return data


class GroqLLM:
    """JSON-mode chat completion against Groq."""

    def __init__(self, cfg: LlmConfig, client: Any | None = None, sleep=time.sleep) -> None:
        self.cfg = cfg
        # max_retries=0: retries are handled here so behaviour is explicit and testable.
        self.client = client or groq.Groq(api_key=cfg.api_key, timeout=cfg.timeout_s, max_retries=0)
        self._sleep = sleep

    def complete_json(self, system: str, user: str, *, max_tokens: int = 1024) -> LLMResponse:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(1, self.cfg.max_retries + 2):
            started = time.perf_counter()
            try:
                resp = self.client.chat.completions.create(
                    model=self.cfg.model,
                    messages=messages,
                    temperature=0,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
            except TRANSIENT as exc:
                if attempt > self.cfg.max_retries:
                    raise LLMError(f"Groq unavailable after {attempt} attempts ({type(exc).__name__})") from exc
                wait = _retry_after(exc, 2.0**attempt)
                logger.warning("Groq %s, retry %d in %.1fs", type(exc).__name__, attempt, wait)
                self._sleep(wait)
                continue
            except groq.AuthenticationError as exc:
                raise LLMError("Groq rejected the API key (check GROQ_API_KEY)") from exc
            except groq.NotFoundError as exc:
                raise LLMError(f"Groq model not found: {self.cfg.model} (check GROQ_MODEL)") from exc
            except groq.APIStatusError as exc:
                raise LLMError(f"Groq request failed with HTTP {exc.status_code}") from exc

            latency = (time.perf_counter() - started) * 1000
            choice = resp.choices[0] if resp.choices else None
            data = parse_json_object(choice.message.content if choice else None)
            usage = getattr(resp, "usage", None)
            return LLMResponse(
                data=data,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                latency_ms=round(latency, 1),
                model=getattr(resp, "model", self.cfg.model),
            )
        raise AssertionError("unreachable")
