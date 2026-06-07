"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class AgentConfig:
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    tavily_api_key: str = ""
    max_agent_steps: int = 5
    request_timeout: float = 60.0


def load_config(env_file: str | Path = ".env", require_api_key: bool = True) -> AgentConfig:
    """Load configuration from a dotenv file and process environment.

    Values from the real process environment override values from the dotenv file.
    Reading a dotenv file here does not mutate ``os.environ``.
    """

    env_path = Path(env_file)
    file_values = dotenv_values(env_path) if env_path.exists() else {}

    values = {key: str(value) for key, value in file_values.items() if value is not None}
    values.update(os.environ)

    api_key = values.get("DEEPSEEK_API_KEY", "").strip()
    if require_api_key and not api_key:
        raise ConfigError("DEEPSEEK_API_KEY is required. Please set it in .env or the environment.")

    return AgentConfig(
        deepseek_api_key=api_key,
        deepseek_base_url=_get_str(values, "DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=_get_str(values, "DEEPSEEK_MODEL", "deepseek-chat"),
        tavily_api_key=values.get("TAVILY_API_KEY", "").strip(),
        max_agent_steps=_get_positive_int(values, "MAX_AGENT_STEPS", 5),
        request_timeout=_get_positive_float(values, "REQUEST_TIMEOUT", 60.0),
    )


def _get_str(values: dict[str, str], name: str, default: str) -> str:
    value = values.get(name, "").strip()
    return value or default


def _get_positive_int(values: dict[str, str], name: str, default: int) -> int:
    raw_value = values.get(name, "").strip()
    if not raw_value:
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc

    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0.")
    return value


def _get_positive_float(values: dict[str, str], name: str, default: float) -> float:
    raw_value = values.get(name, "").strip()
    if not raw_value:
        return default

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc

    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0.")
    return value
