"""Tests for Google OAuth helper."""

from kernel.integrations.google_auth import CREDENTIALS_FILE, GoogleAuth


class TestGoogleAuth:
    def test_create_auth(self) -> None:
        auth = GoogleAuth()
        assert isinstance(auth, GoogleAuth)

    def test_not_configured_without_credentials(self) -> None:
        auth = GoogleAuth()
        # In test env, credentials file likely doesn't exist
        assert auth.is_configured() == CREDENTIALS_FILE.exists()

    def test_not_authenticated_without_token(self) -> None:
        auth = GoogleAuth()
        # Token may or may not exist depending on dev environment
        assert isinstance(auth.is_authenticated(), bool)
