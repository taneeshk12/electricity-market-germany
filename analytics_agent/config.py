"""Agent configuration from environment variables (loaded from the project's .env).

The agent connects with its own read-only role (AGENT_DB_USER), never with the
pipeline's admin account. Secrets are kept out of reprs so they cannot leak into logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from src import config as pipeline_config  # noqa: F401  (loads .env as a side effect)


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or unsafe."""


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    statement_timeout_ms: int = 5_000
    max_rows: int = 500


@dataclass(frozen=True)
class LlmConfig:
    api_key: str = field(repr=False)
    model: str
    timeout_s: float = 30.0
    max_retries: int = 3
    # Reasoning models (e.g. gpt-oss) spend hidden reasoning tokens from this budget, so keep it generous.
    max_tokens: int = 4096
    reasoning_effort: str | None = None  # low | medium | high, only for models that support it


def get_db_config() -> DbConfig:
    """Connection settings for the read-only agent role."""
    user = os.getenv("AGENT_DB_USER", "emg_agent_ro")
    password = os.getenv("AGENT_DB_PASSWORD", "")
    if not password:
        raise ConfigError("AGENT_DB_PASSWORD is not set. Create the role with `make agent-role` first.")
    if user == os.getenv("POSTGRES_USER"):
        raise ConfigError("AGENT_DB_USER must not be the pipeline/admin user; use the read-only role.")
    return DbConfig(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=_int("POSTGRES_PORT", 5433),
        database=os.getenv("POSTGRES_DB", "electricity"),
        user=user,
        password=password,
        statement_timeout_ms=_int("AGENT_STATEMENT_TIMEOUT_MS", 5_000),
        max_rows=_int("AGENT_MAX_ROWS", 500),
    )


def get_llm_config() -> LlmConfig:
    """Groq settings. The model is configurable without code changes (GROQ_MODEL)."""
    api_key = os.getenv("GROQ_API_KEY", "")
    model = os.getenv("GROQ_MODEL", "")
    if not api_key:
        raise ConfigError("GROQ_API_KEY is not set (add it to .env).")
    if not model:
        raise ConfigError(
            "GROQ_MODEL is not set (e.g. a current model id from `python -m analytics_agent.cli --models`)."
        )
    return LlmConfig(
        api_key=api_key,
        model=model,
        timeout_s=float(os.getenv("GROQ_TIMEOUT_S", "30")),
        max_retries=_int("GROQ_MAX_RETRIES", 3),
        max_tokens=_int("GROQ_MAX_TOKENS", 4096),
        reasoning_effort=os.getenv("GROQ_REASONING_EFFORT") or None,
    )


MAX_SQL_CHARS: int = _int("AGENT_MAX_SQL_CHARS", 4_000)
MAX_QUESTION_CHARS: int = _int("AGENT_MAX_QUESTION_CHARS", 500)
