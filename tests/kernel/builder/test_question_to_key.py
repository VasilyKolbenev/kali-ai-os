"""Helper that maps a wizard question text to its config key.

Authoritative test — drift in either the helper or the question
strings in `_skill_questions` will fail this and force sync.
"""
from __future__ import annotations

import pytest

from kernel.builder.wizard import _question_to_key


@pytest.mark.parametrize(
    "question,expected",
    [
        # tracker
        ("Какая дневная цель?", "goal"),
        ("Как часто напоминать?", "interval"),
        ("Куда отправлять уведомления — голосом или в телеграм?", "notify_channel"),
        # reminder
        ("В какое время начинать и заканчивать?", "time_window"),
        # monitor
        ("Какой URL или сервис проверять?", "target"),
        ("Как часто проверять?", "interval"),
        # notifier
        ("При каком условии уведомлять?", "trigger"),
        ("Куда отправлять — голосом или в телеграм?", "notify_channel"),
        # logger
        ("Какие события записывать?", "categories"),
        # unknown question falls into the param_N bucket
        ("Что-то совершенно другое?", ""),
    ],
)
def test_question_to_key(question: str, expected: str) -> None:
    assert _question_to_key(question) == expected
