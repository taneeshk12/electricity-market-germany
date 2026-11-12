"""Groq wrapper: retries, fail-fast errors, JSON parsing – with a fake Groq client."""

from __future__ import annotations

from types import SimpleNamespace

import groq
import httpx
import pytest

from analytics_agent.config import LlmConfig
from analytics_agent.llm import GroqLLM, LLMError, LLMOutputError, parse_json_object

CFG = LlmConfig(api_key="gsk_secret_key", model="test-model", max_retries=2)
REQ = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _resp(content: str | None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        model="test-model",
    )


def _status_error(cls, code: int, headers=None):
    return cls("err", response=httpx.Response(code, request=REQ, headers=headers or {}), body=None)


class FakeGroq:
    def __init__(self, *outcomes) -> None:
        self.outcomes, self.kwargs = list(outcomes), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _llm(*outcomes):
    sleeps: list[float] = []
    fake = FakeGroq(*outcomes)
    return GroqLLM(CFG, client=fake, sleep=sleeps.append), fake, sleeps


def test_success_uses_json_mode_and_reports_usage() -> None:
    llm, fake, _ = _llm(_resp('{"answerable": true, "sql": "SELECT 1"}'))
    r = llm.complete_json("sys", "user")
    assert r.data == {"answerable": True, "sql": "SELECT 1"}
    assert (r.prompt_tokens, r.completion_tokens) == (11, 7)
    kw = fake.kwargs[0]
    assert kw["response_format"] == {"type": "json_object"} and kw["temperature"] == 0 and kw["model"] == "test-model"


def test_rate_limit_is_retried_honouring_retry_after() -> None:
    llm, fake, sleeps = _llm(_status_error(groq.RateLimitError, 429, {"retry-after": "3"}), _resp('{"a": 1}'))
    assert llm.complete_json("s", "u").data == {"a": 1}
    assert sleeps == [3.0] and len(fake.kwargs) == 2


def test_timeout_retries_then_gives_up() -> None:
    llm, fake, sleeps = _llm(*[groq.APITimeoutError(request=REQ)] * 3)
    with pytest.raises(LLMError, match="unavailable after 3 attempts"):
        llm.complete_json("s", "u")
    assert len(sleeps) == 2


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (_status_error(groq.AuthenticationError, 401), "API key"),
        (_status_error(groq.NotFoundError, 404), "model not found"),
        (_status_error(groq.BadRequestError, 400), "HTTP 400"),
    ],
)
def test_permanent_errors_fail_fast_without_leaking_key(exc, message) -> None:
    llm, fake, sleeps = _llm(exc)
    with pytest.raises(LLMError, match=message) as info:
        llm.complete_json("s", "u")
    assert sleeps == [] and "gsk_secret_key" not in str(info.value)


@pytest.mark.parametrize("content", [None, "", "   ", "not json", "[1, 2]"])
def test_invalid_output(content) -> None:
    llm, *_ = _llm(_resp(content))
    with pytest.raises(LLMOutputError):
        llm.complete_json("s", "u")


def test_fenced_json_is_tolerated() -> None:
    assert parse_json_object('```json\n{"x": 1}\n```') == {"x": 1}


def test_config_repr_hides_key() -> None:
    assert "gsk_secret_key" not in repr(CFG)


def _json_validate_failed():
    body = {"error": {"code": "json_validate_failed", "failed_generation": "max completion tokens reached"}}
    return groq.BadRequestError("err", response=httpx.Response(400, request=REQ), body=body)


def test_json_validate_failed_is_retried_once() -> None:
    llm, fake, _ = _llm(_json_validate_failed(), _resp('{"answer": "ok"}'))
    assert llm.complete_json("s", "u").data == {"answer": "ok"}
    assert len(fake.kwargs) == 2


def test_json_validate_failed_twice_reports_code() -> None:
    llm, *_ = _llm(_json_validate_failed(), _json_validate_failed())
    with pytest.raises(LLMError, match="json_validate_failed"):
        llm.complete_json("s", "u")


def test_reasoning_budget_and_effort_are_sent() -> None:
    cfg = LlmConfig(api_key="k", model="m", max_tokens=4096, reasoning_effort="low")
    fake = FakeGroq(_resp('{"a": 1}'))
    GroqLLM(cfg, client=fake).complete_json("s", "u")
    assert fake.kwargs[0]["max_tokens"] == 4096 and fake.kwargs[0]["reasoning_effort"] == "low"


def test_reasoning_effort_omitted_by_default() -> None:
    fake = FakeGroq(_resp('{"a": 1}'))
    GroqLLM(CFG, client=fake).complete_json("s", "u")
    assert "reasoning_effort" not in fake.kwargs[0]
