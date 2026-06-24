"""Tests for the action -> plain-language preview bridge (dry-run preview v1)."""

from kernel.action_preview import describe_action


def test_side_effecting_action_is_high_risk() -> None:
    r = describe_action("email", "send_email", {"to": "a@b.com"})
    assert r["risk"] == "high"
    assert r["agent"] == "email"
    assert r["action"] == "send_email"
    assert r["label"]  # non-empty plain-language description


def test_read_action_is_med_risk() -> None:
    assert describe_action("messenger", "read_messages")["risk"] == "med"


def test_public_lookup_is_low_risk() -> None:
    assert describe_action("weather", "get_weather")["risk"] == "low"


def test_unknown_action_falls_back_to_raw_name() -> None:
    r = describe_action("custom", "frobnicate")
    assert r["label"] == "frobnicate"  # no curated label -> show the raw action
    assert r["risk"] == "low"


def test_risk_from_token_on_unknown_action() -> None:
    # Token-based classification: a side-effect verb makes it high even when the
    # action is not in the curated label map.
    assert describe_action("x", "delete_thing")["risk"] == "high"
    assert describe_action("x", "create_thing")["risk"] == "high"


def test_known_action_gets_plain_language_label() -> None:
    r = describe_action("email", "send_email")
    assert r["label"] != "send_email"  # mapped to a plain-language RU label
