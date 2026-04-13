"""Tests for kernel.builder.intent_classifier."""

from __future__ import annotations

import pytest

from kernel.builder.intent_classifier import IntentResult, classify_intent


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------


def test_tracker_russian_otslezh() -> None:
    result = classify_intent("отслеживай мои расходы каждый день")
    assert result.type == "skill"
    assert result.template == "tracker"
    assert result.confidence >= 0.75


def test_tracker_russian_uchet() -> None:
    result = classify_intent("веди учёт калорий")
    assert result.type == "skill"
    assert result.template == "tracker"


def test_tracker_english_track() -> None:
    result = classify_intent("track my daily water intake")
    assert result.type == "skill"
    assert result.template == "tracker"


# ---------------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------------


def test_reminder_russian() -> None:
    result = classify_intent("напоминай мне пить воду каждые 2 часа")
    assert result.type == "skill"
    assert result.template == "reminder"


def test_reminder_english() -> None:
    result = classify_intent("remind me to take my pills at 8am")
    assert result.type == "skill"
    assert result.template == "reminder"


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------


def test_monitor_russian() -> None:
    result = classify_intent("мониторинг сервера каждые 5 минут")
    assert result.type == "skill"
    assert result.template == "monitor"


def test_monitor_english_check_every() -> None:
    result = classify_intent("check every hour if the site is down")
    assert result.type == "skill"
    assert result.template == "monitor"


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------


def test_notifier_russian() -> None:
    result = classify_intent("уведомляй меня когда температура выше 30")
    assert result.type == "skill"
    assert result.template == "notifier"


def test_notifier_english_alert() -> None:
    result = classify_intent("alert me when disk usage exceeds 90%")
    assert result.type == "skill"
    assert result.template == "notifier"


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------


def test_logger_russian_dnevnik() -> None:
    result = classify_intent("веди дневник моих тренировок")
    assert result.type == "skill"
    assert result.template == "logger"


def test_logger_russian_zhurnal() -> None:
    result = classify_intent("журнал ошибок для сервиса")
    assert result.type == "skill"
    assert result.template == "logger"


# ---------------------------------------------------------------------------
# Agent signals
# ---------------------------------------------------------------------------


def test_agent_api_mention() -> None:
    result = classify_intent("подключись к REST API биткоина и парсь цены")
    assert result.type == "agent"
    assert result.template is None


def test_agent_integration_mention() -> None:
    result = classify_intent("интегрируй с системой умного дома")
    assert result.type == "agent"


def test_agent_telegram() -> None:
    result = classify_intent("отправляй сообщения в telegram бот")
    assert result.type == "agent"


def test_agent_email() -> None:
    result = classify_intent("send me email notifications when a new order arrives")
    assert result.type == "agent"


def test_agent_crypto() -> None:
    result = classify_intent("отслеживай крипто курсы")
    # "крипт" is an agent signal — takes priority over tracker pattern
    assert result.type == "agent"


# ---------------------------------------------------------------------------
# Default / ambiguous
# ---------------------------------------------------------------------------


def test_ambiguous_defaults_to_skill() -> None:
    result = classify_intent("сделай что-нибудь полезное")
    assert result.type == "skill"
    assert result.confidence == pytest.approx(0.50)


def test_result_is_intent_result_dataclass() -> None:
    result = classify_intent("напоминай мне о встрече")
    assert isinstance(result, IntentResult)
    assert result.reason  # non-empty string
