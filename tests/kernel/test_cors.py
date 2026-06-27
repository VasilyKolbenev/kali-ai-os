"""Safe-by-default checks for the Python backend: host bind + CORS origins.

WS-2 Task 2.4 — verifies the FastAPI backend does not ship unsafe in-code
defaults (no wildcard CORS with credentials, loopback host bind by default)
while keeping env escape hatches (`KALI_HOST`, `KALI_CORS_ORIGINS`).
"""

import pytest

from kernel.main import _cors_origins, _resolve_host


class TestCorsOrigins:
    def test_default_origins_have_no_wildcard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KALI_CORS_ORIGINS", raising=False)
        origins = _cors_origins()
        assert "*" not in origins

    def test_default_origins_include_tauri_shell(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KALI_CORS_ORIGINS", raising=False)
        origins = _cors_origins()
        assert "tauri://localhost" in origins

    def test_default_origins_include_vite_dev(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KALI_CORS_ORIGINS", raising=False)
        origins = _cors_origins()
        assert "http://localhost:1420" in origins

    def test_env_override_replaces_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALI_CORS_ORIGINS", "http://localhost:9999")
        origins = _cors_origins()
        assert origins == ["http://localhost:9999"]


class TestResolveHost:
    def test_default_host_is_loopback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("KALI_HOST", raising=False)
        assert _resolve_host() == "127.0.0.1"

    def test_host_is_env_overridable_for_lan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALI_HOST", "0.0.0.0")
        assert _resolve_host() == "0.0.0.0"
