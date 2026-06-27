"""Community identity — KALI's own anonymous device-id + magic-link account.

WS-3 Task 3.3. This is the backend identity layer the §4 CatalogClient consumes:
``device_id`` (anon) and ``creator_id`` (the signed-in account's ``auth.uid()``)
are PROVIDED here and wired into the client's install / publish / social seams.

Anti-pivot (§2 of the marketplace design spec, BINDING):
    * **Anonymous device-id** — a locally-persisted uuid4, no PII, no account.
      Used for browse / install / like / counters (``likes.device_or_user_id`` and
      ``installs.device_id`` in the §4 model). Generated once, reused thereafter.
    * **Optional magic-link KALI account** — email → Supabase OTP (``sign_in_with_otp``
      → ``verify_otp``). Its ``auth.uid()`` IS the ``creator_id``
      (``creators.id == auth.users.id``). Used for publish / rate / comment /
      cross-device attribution. NEVER Google/Apple OAuth or any per-platform social
      login. Self-declared socials (3.2) are display strings only.

Graceful degradation (same contract as CatalogClient): when Supabase is
unconfigured or supabase-py is unavailable, magic-link/session calls return
``None`` / ``{"status": "unconfigured"}`` and never raise. The device-id is
purely local and always works.

The Supabase Python auth surface used here (verified against current docs, not
training data): ``auth.sign_in_with_otp({"email": ...})``, ``auth.verify_otp(
{"email", "token", "type": "email"})``, ``auth.get_user()`` (server-verified),
``auth.get_session()`` (local, used as offline fallback), ``auth.set_session(
access_token, refresh_token)`` (rehydrate a persisted session), ``auth.sign_out()``.
"""

import json
import logging
import os
import uuid
from typing import Any

from kernel.runtime_paths import appdata_dir

logger = logging.getLogger(__name__)

# Local persistence file names (under appdata_dir()).
_DEVICE_ID_FILE = "community_device_id"
_SESSION_FILE = "community_session.json"

# OTP type for an email magic link (Supabase verify_otp `type`).
_OTP_TYPE_EMAIL = "email"

_UNCONFIGURED: dict[str, str] = {"status": "unconfigured"}

# Process-level memo for the device-id so repeated calls avoid disk reads. Reset
# by tests via monkeypatch; a fresh process re-reads it from disk on first call.
_DEVICE_ID_CACHE: str | None = None


def get_device_id() -> str:
    """Return the stable anonymous device-id, generating + persisting it once.

    The id is a uuid4 stored at ``appdata_dir()/community_device_id``. It is
    cached in-process and re-read from disk on a fresh process, so it is stable
    across calls AND across re-instantiation. It contains no PII and is never
    tied to ``auth.uid()`` — it identifies the device, not a person.

    Returns:
        The persisted device-id string.
    """
    global _DEVICE_ID_CACHE
    if _DEVICE_ID_CACHE:
        return _DEVICE_ID_CACHE

    store = appdata_dir() / _DEVICE_ID_FILE
    try:
        if store.exists():
            existing = store.read_text(encoding="utf-8").strip()
            if existing:
                _DEVICE_ID_CACHE = existing
                return existing
    except OSError as exc:
        logger.warning("Could not read device-id store %s: %s", store, exc)

    device_id = str(uuid.uuid4())
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(device_id, encoding="utf-8")
    except OSError as exc:
        # Persisting failed (read-only FS?). Still return a usable id for this
        # process; it just won't survive a restart.
        logger.warning("Could not persist device-id to %s: %s", store, exc)

    _DEVICE_ID_CACHE = device_id
    return device_id


class CommunityIdentity:
    """KALI account session helper over Supabase magic-link auth (lazy + graceful).

    Wraps the Supabase auth client (constructed lazily, identical degradation
    contract to ``CatalogClient``). Exposes the magic-link flow and the signed-in
    account id (``auth.uid()`` == ``creator_id``). Also re-exports ``get_device_id``
    as a method so a single ``identity`` object is the one seam CatalogClient needs.
    """

    def __init__(self) -> None:
        self._url = os.environ.get("SUPABASE_URL", "")
        self._key = os.environ.get("SUPABASE_KEY", "")
        self._auth: Any = None
        self._configured = bool(self._url and self._key)
        self._init_attempted = False

    # ------------------------------------------------------------- device id

    def get_device_id(self) -> str:
        """Return the anonymous device-id (delegates to the module function)."""
        return get_device_id()

    # ------------------------------------------------------------- auth client

    def _get_auth(self) -> Any | None:
        """Lazily build the Supabase auth client; None when unavailable.

        Returns:
            The ``supabase.auth`` object, or None if Supabase is unconfigured or
            supabase-py is not installed.
        """
        if self._init_attempted:
            return self._auth

        self._init_attempted = True
        if not self._configured:
            logger.debug("Supabase not configured — community account offline")
            return None

        try:
            from supabase import create_client  # type: ignore[import-untyped]

            client = create_client(self._url, self._key)
            self._auth = client.auth
            self.restore_session()
        except ImportError:
            logger.warning("supabase-py not installed — community account offline")
        except Exception as exc:  # noqa: BLE001 — degrade on any init failure
            logger.error("Failed to init Supabase auth: %s", exc)

        return self._auth

    # ------------------------------------------------------------- magic link

    def request_magic_link(self, email: str) -> dict[str, str]:
        """Send a magic-link / OTP email via Supabase ``sign_in_with_otp``.

        Args:
            email: The destination email for the magic link.

        Returns:
            ``{"status": "sent"}`` on success, ``{"status": "unconfigured"}`` when
            Supabase is offline, or ``{"status": "error"}`` on a backend failure.

        Raises:
            ValueError: If ``email`` is empty.
        """
        if not email:
            raise ValueError("email is required for a magic link")

        auth = self._get_auth()
        if auth is None:
            return dict(_UNCONFIGURED)
        try:
            auth.sign_in_with_otp({"email": email})
            return {"status": "sent"}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("request_magic_link failed: %s", exc)
            return {"status": "error"}

    def verify_magic_link(self, email: str, token: str) -> dict[str, str]:
        """Exchange the emailed OTP for a session and persist it locally.

        Args:
            email: The email the OTP was sent to.
            token: The OTP code from the email.

        Returns:
            ``{"status": "signed_in"}`` on success, ``{"status": "unconfigured"}``
            offline, or ``{"status": "error"}`` on failure / invalid code.

        Raises:
            ValueError: If ``email`` or ``token`` is empty.
        """
        if not email or not token:
            raise ValueError("email and token are required to verify a magic link")

        auth = self._get_auth()
        if auth is None:
            return dict(_UNCONFIGURED)
        try:
            response = auth.verify_otp(
                {"email": email, "token": token, "type": _OTP_TYPE_EMAIL}
            )
            session = getattr(response, "session", None)
            if session is not None:
                self._persist_session(session)
            return {"status": "signed_in"}
        except Exception as exc:  # noqa: BLE001 — graceful degradation
            logger.error("verify_magic_link failed: %s", exc)
            return {"status": "error"}

    # --------------------------------------------------------------- session

    def current_account_id(self) -> str | None:
        """Return the signed-in account id (``auth.uid()`` == ``creator_id``).

        Prefers the server-verified ``get_user()`` (the trustworthy path), and
        falls back to the locally-cached ``get_session()`` user when the network
        call fails (offline). Returns None when signed out or unconfigured.

        Returns:
            The authenticated user's uuid, or None.
        """
        auth = self._get_auth()
        if auth is None:
            return None

        uid = self._uid_from_get_user(auth)
        if uid is not None:
            return uid
        return self._uid_from_session(auth)

    def is_signed_in(self) -> bool:
        """True when a KALI account session is active."""
        return self.current_account_id() is not None

    def restore_session(self) -> None:
        """Rehydrate a persisted session into the auth client via ``set_session``.

        No-op when there is no persisted session or no auth client. Failures are
        swallowed (a stale/expired token simply leaves the user signed out).
        """
        auth = self._auth
        if auth is None:
            return
        tokens = self._load_session()
        if not tokens:
            return
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token")
        if not access or not refresh:
            return
        try:
            auth.set_session(access, refresh)
        except Exception as exc:  # noqa: BLE001 — stale token → stay signed out
            logger.warning("Could not restore community session: %s", exc)

    def sign_out(self) -> dict[str, str]:
        """Sign out of the KALI account and clear the persisted session.

        Returns:
            ``{"status": "signed_out"}`` on success, or ``{"status":
            "unconfigured"}`` when Supabase is offline.
        """
        auth = self._get_auth()
        self._clear_session_file()
        if auth is None:
            return dict(_UNCONFIGURED)
        try:
            auth.sign_out()
        except Exception as exc:  # noqa: BLE001 — best-effort sign out
            logger.warning("sign_out backend call failed: %s", exc)
        return {"status": "signed_out"}

    # --------------------------------------------------------- internal helpers

    @staticmethod
    def _uid_from_get_user(auth: Any) -> str | None:
        """Server-verified uid via ``get_user()`` (None on absent / failure)."""
        try:
            response = auth.get_user()
        except Exception as exc:  # noqa: BLE001 — fall back to local session
            logger.debug("get_user failed, will try local session: %s", exc)
            return None
        user = getattr(response, "user", None)
        return getattr(user, "id", None) if user is not None else None

    @staticmethod
    def _uid_from_session(auth: Any) -> str | None:
        """Locally-cached uid via ``get_session()`` (offline fallback)."""
        try:
            session = auth.get_session()
        except Exception as exc:  # noqa: BLE001 — no session available
            logger.debug("get_session failed: %s", exc)
            return None
        user = getattr(session, "user", None) if session is not None else None
        return getattr(user, "id", None) if user is not None else None

    def _persist_session(self, session: Any) -> None:
        """Persist a session's tokens to appdata for later rehydration."""
        access = getattr(session, "access_token", None)
        refresh = getattr(session, "refresh_token", None)
        if not access or not refresh:
            return
        store = appdata_dir() / _SESSION_FILE
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            store.write_text(
                json.dumps({"access_token": access, "refresh_token": refresh}),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not persist community session: %s", exc)

    @staticmethod
    def _load_session() -> dict[str, str] | None:
        """Load persisted session tokens from appdata (None if absent/invalid)."""
        store = appdata_dir() / _SESSION_FILE
        try:
            if not store.exists():
                return None
            data = json.loads(store.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read community session: %s", exc)
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _clear_session_file() -> None:
        """Remove the persisted session file (best-effort)."""
        store = appdata_dir() / _SESSION_FILE
        try:
            store.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not clear community session file: %s", exc)
