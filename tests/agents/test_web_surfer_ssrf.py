"""SSRF-guard tests for the web-surfer ``fetch_url`` script (WS-2 Task 2.8).

``agents/web-surfer/scripts/surf.py`` fetches a USER/VOICE-supplied ``--url``,
so — like the monitor template — it is a third-party-reachable SSRF path. These
tests assert that ``fetch_url`` routes egress through ``SandboxHttpClient`` (the
fail-closed guard: private-IP block + whitelist + redirect re-check) rather than
raw ``urllib.urlopen``:

- a private/loopback/link-local target is BLOCKED (no fetch, error returned);
- a public target is fetched and its text extracted.

DNS note: private IP *literals* are parsed by ``ipaddress`` without any DNS, so
SSRF-block tests need no network; the public-host test mocks the guard's
``_resolves_to_private`` (real public hosts resolve to a captive address here).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SURF_PATH = (
    Path(__file__).resolve().parents[2]
    / "agents" / "web-surfer" / "scripts" / "surf.py"
)


def _load_surf():
    """Import surf.py as a module from its on-disk path."""
    spec = importlib.util.spec_from_file_location("web_surfer_surf", _SURF_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def surf():
    return _load_surf()


def _mock_opener_open(body: bytes = b"<html><body>Hello World</body></html>"):
    """Mock for ``OpenerDirector.open`` — surf fetches via the guard's opener."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.url = "https://example.com/"
    mock_resp.headers.items.return_value = [("Content-Type", "text/html")]
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=mock_resp)


class TestSurfSsrfBlocked:
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1/admin",
            "http://localhost:8080/",
            "http://10.0.0.5/internal",
            "http://192.168.0.1/",
        ],
    )
    def test_private_url_blocked(self, surf, url):
        """A private/loopback target is blocked and never fetched."""
        with patch("urllib.request.OpenerDirector.open") as op:
            result = surf.fetch_url(url)
        assert "Error" in result
        op.assert_not_called()


class TestSurfPublicAllowed:
    def test_public_url_fetched(self, surf):
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open", _mock_opener_open()):
            result = surf.fetch_url("https://example.com/page")
        assert "Hello World" in result
        assert "Error" not in result


class TestSurfSearchAllowed:
    def test_search_uses_guard(self, surf):
        body = b"<html><body>Web Results foo bar</body></html>"
        with patch(
            "kernel.sandbox.http_client._resolves_to_private", return_value=False
        ), patch("urllib.request.OpenerDirector.open", _mock_opener_open(body=body)):
            result = surf.search_duckduckgo("iphone")
        assert "Web Results" in result
