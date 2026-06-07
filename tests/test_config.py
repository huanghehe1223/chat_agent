from pathlib import Path

import pytest

from src.agent.config import ConfigError, load_config


def test_load_config_reads_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("MAX_AGENT_STEPS", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DEEPSEEK_API_KEY=test-key",
                "DEEPSEEK_BASE_URL=https://example.com/v1",
                "DEEPSEEK_MODEL=deepseek-test",
                "TAVILY_API_KEY=tavily-test",
                "MAX_AGENT_STEPS=7",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(env_file)

    assert config.deepseek_api_key == "test-key"
    assert config.deepseek_base_url == "https://example.com/v1"
    assert config.deepseek_model == "deepseek-test"
    assert config.tavily_api_key == "tavily-test"
    assert config.max_agent_steps == 7


def test_load_config_requires_deepseek_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("MAX_AGENT_STEPS=5", encoding="utf-8")

    with pytest.raises(ConfigError, match="DEEPSEEK_API_KEY"):
        load_config(env_file)


def test_load_config_validates_max_agent_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAX_AGENT_STEPS", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DEEPSEEK_API_KEY=test-key",
                "MAX_AGENT_STEPS=0",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="MAX_AGENT_STEPS"):
        load_config(env_file)
