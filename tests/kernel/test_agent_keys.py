"""Tests for the agent credential registry."""
from kernel import agent_keys


def test_unconfigured_agent_reports_missing(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert agent_keys.agent_is_configured("telegram") is False
    assert set(agent_keys.agent_missing_keys("telegram")) == {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    }


def test_partial_keys_still_unconfigured(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert agent_keys.agent_is_configured("telegram") is False
    assert agent_keys.agent_missing_keys("telegram") == ["TELEGRAM_CHAT_ID"]


def test_all_keys_present_is_configured(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    assert agent_keys.agent_is_configured("telegram") is True
    assert agent_keys.agent_missing_keys("telegram") == []


def test_whitespace_only_key_is_unconfigured(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_API_KEY", "   ")
    assert agent_keys.agent_is_configured("notion") is False


def test_agent_without_requirements_is_configured() -> None:
    # weather/news/etc. need no key → never block the user.
    assert agent_keys.agent_is_configured("weather") is True
    assert agent_keys.agent_missing_keys("weather") == []


def test_allowed_keys_whitelist_is_complete() -> None:
    assert "TELEGRAM_BOT_TOKEN" in agent_keys.ALLOWED_AGENT_KEYS
    assert "NOTION_API_KEY" in agent_keys.ALLOWED_AGENT_KEYS
    assert "TODOIST_API_KEY" in agent_keys.ALLOWED_AGENT_KEYS
    assert "HA_TOKEN" in agent_keys.ALLOWED_AGENT_KEYS
    # never leak LLM/system keys into the agent whitelist
    assert "OPENAI_API_KEY" not in agent_keys.ALLOWED_AGENT_KEYS


def test_config_status_shape(monkeypatch) -> None:
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    status = agent_keys.all_agents_config_status()
    assert "telegram" in status and "notion" in status
    assert set(status["notion"]) == {"configured", "missing_keys", "required_keys"}
    assert status["notion"]["configured"] is False
