"""Tests for kernel.catalog.identity — WS-3 Task 3.3 identity layer.

KALI's OWN identity (anti-pivot, §2 of the marketplace design spec):
    * an ANONYMOUS, locally-persisted device-id (no PII, no account) used for
      browse / install / like / counters — ``likes.device_or_user_id`` and
      ``installs.device_id`` in the §4 model;
    * an OPTIONAL lightweight magic-link KALI account (email → Supabase OTP) used
      for publish / rate / comment / cross-device attribution — its ``auth.uid()``
      is the ``creator_id`` (``creators.id == auth.users.id``).

NO Google/Apple OAuth, ever. Self-declared socials (3.2) are display strings only.

No live Supabase: the auth surface (``supabase.auth.*``) is mocked. The
graceful-degradation contract mirrors CatalogClient — unconfigured returns
None / "unconfigured" and never raises. Tests NEVER touch the real %APPDATA%:
``appdata_dir`` is monkeypatched to a tmp path.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import kernel.catalog.identity as identity_mod
from kernel.catalog.identity import CommunityIdentity, get_device_id


@pytest.fixture(autouse=True)
def _tmp_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect appdata to a tmp dir AND reset the device-id memo per test.

    Patches ``appdata_dir`` everywhere the identity module looks it up, so no
    test can ever write to the real %APPDATA%/KALI. Also clears the module-level
    device-id cache so stability tests start from a clean slate.
    """
    monkeypatch.setattr(identity_mod, "appdata_dir", lambda: tmp_path)
    monkeypatch.setattr(identity_mod, "_DEVICE_ID_CACHE", None, raising=False)
    return tmp_path


# ===========================================================================
# get_device_id — stable, persisted, anonymous (no PII)
# ===========================================================================

class TestDeviceId:
    def test_returns_a_uuid_string(self, _tmp_appdata: Path) -> None:
        device_id = get_device_id()
        assert isinstance(device_id, str)
        # uuid4 canonical form: 36 chars, 4 dashes.
        assert len(device_id) == 36
        assert device_id.count("-") == 4

    def test_is_stable_across_calls_in_process(self, _tmp_appdata: Path) -> None:
        first = get_device_id()
        second = get_device_id()
        assert first == second

    def test_is_persisted_to_appdata(self, _tmp_appdata: Path) -> None:
        device_id = get_device_id()
        store = _tmp_appdata / "community_device_id"
        assert store.exists()
        assert store.read_text(encoding="utf-8").strip() == device_id

    def test_survives_reinstantiation_reading_same_store(
        self, _tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # First "process" generates + persists it.
        original = get_device_id()
        # Simulate a fresh process: clear the in-memory memo, read again.
        monkeypatch.setattr(identity_mod, "_DEVICE_ID_CACHE", None, raising=False)
        reread = get_device_id()
        assert reread == original

    def test_does_not_regenerate_when_file_present(
        self, _tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _tmp_appdata / "community_device_id"
        store.write_text("preexisting-device-id-value", encoding="utf-8")
        monkeypatch.setattr(identity_mod, "_DEVICE_ID_CACHE", None, raising=False)
        assert get_device_id() == "preexisting-device-id-value"


# ===========================================================================
# Helpers — a mock supabase auth surface
# ===========================================================================

def _identity_with_auth(auth: MagicMock | None) -> CommunityIdentity:
    """A configured CommunityIdentity whose Supabase auth is the given mock.

    When ``auth`` is None the identity behaves as if Supabase is unconfigured.
    """
    ident = CommunityIdentity()
    if auth is None:
        ident._configured = False
        ident._auth = None
    else:
        ident._configured = True
        ident._auth = auth
    ident._init_attempted = True
    return ident


def _auth_with_user(uid: str | None) -> MagicMock:
    """Mock auth whose get_user()/get_session() expose the given uid (or None)."""
    auth = MagicMock()
    if uid is None:
        # signed-out: get_user raises / returns no user, get_session returns None
        auth.get_user.return_value = None
        auth.get_session.return_value = None
    else:
        user = MagicMock()
        user.id = uid
        user_resp = MagicMock()
        user_resp.user = user
        auth.get_user.return_value = user_resp
        session = MagicMock()
        session.user = user
        auth.get_session.return_value = session
    return auth


# ===========================================================================
# request_magic_link — calls Supabase OTP with the email
# ===========================================================================

class TestRequestMagicLink:
    def test_calls_sign_in_with_otp_with_email(self) -> None:
        auth = MagicMock()
        ident = _identity_with_auth(auth)

        result = ident.request_magic_link("vasily@example.com")

        assert auth.sign_in_with_otp.called
        payload = auth.sign_in_with_otp.call_args[0][0]
        assert payload["email"] == "vasily@example.com"
        assert result["status"] == "sent"

    def test_unconfigured_when_supabase_offline(self) -> None:
        ident = _identity_with_auth(None)
        result = ident.request_magic_link("x@example.com")
        assert result == {"status": "unconfigured"}

    def test_graceful_when_otp_call_raises(self) -> None:
        auth = MagicMock()
        auth.sign_in_with_otp.side_effect = RuntimeError("smtp down")
        ident = _identity_with_auth(auth)

        result = ident.request_magic_link("x@example.com")

        # degrade, never raise
        assert result["status"] in ("error", "unconfigured")

    def test_rejects_empty_email(self) -> None:
        auth = MagicMock()
        ident = _identity_with_auth(auth)
        with pytest.raises(ValueError):
            ident.request_magic_link("")


# ===========================================================================
# session / account-id — exposes auth.uid() when signed in, else None
# ===========================================================================

class TestSession:
    def test_current_account_id_when_signed_in(self) -> None:
        ident = _identity_with_auth(_auth_with_user("uid-123"))
        assert ident.current_account_id() == "uid-123"
        assert ident.is_signed_in() is True

    def test_current_account_id_none_when_signed_out(self) -> None:
        ident = _identity_with_auth(_auth_with_user(None))
        assert ident.current_account_id() is None
        assert ident.is_signed_in() is False

    def test_current_account_id_none_when_unconfigured(self) -> None:
        ident = _identity_with_auth(None)
        assert ident.current_account_id() is None
        assert ident.is_signed_in() is False

    def test_falls_back_to_local_session_when_get_user_raises(self) -> None:
        # get_user() hits the network (server-verified) and may fail offline;
        # fall back to the locally-cached session's user id.
        auth = _auth_with_user("uid-from-session")
        auth.get_user.side_effect = RuntimeError("network down")
        ident = _identity_with_auth(auth)
        assert ident.current_account_id() == "uid-from-session"

    def test_account_id_is_graceful_when_both_paths_raise(self) -> None:
        auth = MagicMock()
        auth.get_user.side_effect = RuntimeError("down")
        auth.get_session.side_effect = RuntimeError("down")
        ident = _identity_with_auth(auth)
        assert ident.current_account_id() is None


# ===========================================================================
# verify_otp + session persistence (token survives re-instantiation)
# ===========================================================================

class TestVerifyAndPersist:
    def test_verify_otp_calls_supabase_and_persists_session(
        self, _tmp_appdata: Path
    ) -> None:
        auth = MagicMock()
        session = MagicMock()
        session.access_token = "acc-tok"
        session.refresh_token = "ref-tok"
        verify_resp = MagicMock()
        verify_resp.session = session
        auth.verify_otp.return_value = verify_resp

        ident = _identity_with_auth(auth)
        result = ident.verify_magic_link("vasily@example.com", "123456")

        assert auth.verify_otp.called
        verify_payload = auth.verify_otp.call_args[0][0]
        assert verify_payload["email"] == "vasily@example.com"
        assert verify_payload["token"] == "123456"
        assert result["status"] == "signed_in"
        # the session tokens are persisted to appdata for rehydration
        store = _tmp_appdata / "community_session.json"
        assert store.exists()
        saved = json.loads(store.read_text(encoding="utf-8"))
        assert saved["access_token"] == "acc-tok"
        assert saved["refresh_token"] == "ref-tok"

    def test_persisted_session_is_rehydrated_via_set_session(
        self, _tmp_appdata: Path
    ) -> None:
        # A prior sign-in left a session file.
        store = _tmp_appdata / "community_session.json"
        store.write_text(
            json.dumps({"access_token": "acc", "refresh_token": "ref"}),
            encoding="utf-8",
        )
        auth = _auth_with_user("uid-rehydrated")
        ident = _identity_with_auth(auth)

        ident.restore_session()

        assert auth.set_session.called
        args = auth.set_session.call_args
        # access + refresh tokens passed through (positional or kwargs)
        passed = list(args[0]) + list(args[1].values())
        assert "acc" in passed
        assert "ref" in passed

    def test_sign_out_clears_persisted_session(self, _tmp_appdata: Path) -> None:
        store = _tmp_appdata / "community_session.json"
        store.write_text(
            json.dumps({"access_token": "a", "refresh_token": "r"}),
            encoding="utf-8",
        )
        auth = MagicMock()
        ident = _identity_with_auth(auth)

        ident.sign_out()

        assert auth.sign_out.called
        assert not store.exists()

    def test_sign_out_unconfigured_is_noop(self) -> None:
        ident = _identity_with_auth(None)
        # must not raise even when offline / no session file
        assert ident.sign_out() == {"status": "unconfigured"}
