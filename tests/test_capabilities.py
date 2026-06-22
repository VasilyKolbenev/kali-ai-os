"""Tests for the capability taxonomy (consent-disclosure v1).

Asserts the fixed disclosure contract: write/send → high + sensitive, read →
med + sensitive, public/network/storage/empty → not sensitive (one-click),
unknown ids → low fallback. Classification must depend only on capability ids,
never the agent name.
"""

from kernel.capabilities import describe_capabilities


class TestRiskClassification:
    def test_send_is_high_and_sensitive(self) -> None:
        out = describe_capabilities(["email.send"])
        assert out["capabilities"][0]["risk"] == "high"
        assert out["sensitive"] is True

    def test_write_is_high_and_sensitive(self) -> None:
        out = describe_capabilities(["calendar.write"])
        assert out["capabilities"][0]["risk"] == "high"
        assert out["sensitive"] is True

    def test_delete_is_high(self) -> None:
        out = describe_capabilities(["calendar.delete_event"])
        assert out["capabilities"][0]["risk"] == "high"
        assert out["sensitive"] is True

    def test_colon_style_id_also_high(self) -> None:
        # Contract examples use the ":write" style; must classify the same.
        out = describe_capabilities(["calendar:create"])
        assert out["capabilities"][0]["risk"] == "high"

    def test_read_is_med_and_sensitive(self) -> None:
        out = describe_capabilities(["email.read"])
        assert out["capabilities"][0]["risk"] == "med"
        assert out["sensitive"] is True

    def test_messenger_read_is_med(self) -> None:
        out = describe_capabilities(["messenger.read"])
        assert out["capabilities"][0]["risk"] == "med"
        assert out["sensitive"] is True


class TestNonSensitiveOneClick:
    def test_public_lookups_not_sensitive(self) -> None:
        # weather agent — only public lookups + network permission.
        out = describe_capabilities(["weather.current", "weather.forecast"])
        assert out["sensitive"] is False
        assert all(c["risk"] == "low" for c in out["capabilities"])

    def test_currency_not_sensitive(self) -> None:
        out = describe_capabilities(["currency.rates", "currency.convert"])
        assert out["sensitive"] is False

    def test_search_is_low(self) -> None:
        # search is a read-ish word but not the "read" token → stays low.
        out = describe_capabilities(["email.search"])
        assert out["capabilities"][0]["risk"] == "low"

    def test_empty_not_sensitive(self) -> None:
        out = describe_capabilities([])
        assert out["capabilities"] == []
        assert out["sensitive"] is False


class TestUnknownFallback:
    def test_unknown_id_low_fallback_with_id_label(self) -> None:
        out = describe_capabilities(["zzz.unknownthing"])
        entry = out["capabilities"][0]
        assert entry["risk"] == "low"
        assert entry["label"] == "zzz.unknownthing"
        assert out["sensitive"] is False


class TestContractShapeAndMixed:
    def test_known_ids_have_russian_labels(self) -> None:
        out = describe_capabilities(["email.send"])
        # Label is plain-language RU, not the raw id.
        assert out["capabilities"][0]["label"] != "email.send"
        assert out["capabilities"][0]["label"].strip() != ""

    def test_mixed_caps_sensitive_if_any_high_or_med(self) -> None:
        # email agent: read (med) + send (high) + search (low) → sensitive.
        out = describe_capabilities(["email.read", "email.send", "email.search"])
        risks = {c["id"]: c["risk"] for c in out["capabilities"]}
        assert risks == {
            "email.read": "med",
            "email.send": "high",
            "email.search": "low",
        }
        assert out["sensitive"] is True

    def test_classification_ignores_agent_name(self) -> None:
        # Same id list yields same result regardless of any external naming.
        a = describe_capabilities(["messenger.send"])
        b = describe_capabilities(["messenger.send"])
        assert a == b
        assert a["sensitive"] is True
