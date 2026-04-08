"""Google OAuth 2.0 helper for Calendar and Gmail APIs."""

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]
TOKEN_FILE = Path("data/google_token.json")
CREDENTIALS_FILE = Path("data/google_credentials.json")


class GoogleAuth:
    """Manages Google OAuth tokens for API access."""

    def __init__(self) -> None:
        self._credentials: Any = None

    def is_configured(self) -> bool:
        """Check if Google credentials file exists."""
        return CREDENTIALS_FILE.exists()

    def is_authenticated(self) -> bool:
        """Check if we have a valid token."""
        return TOKEN_FILE.exists()

    def get_credentials(self) -> Any:
        """Get or refresh Google OAuth credentials.

        Returns:
            Valid Google OAuth credentials object.

        Raises:
            FileNotFoundError: If credentials file is missing and no token exists.
        """
        if self._credentials and self._credentials.valid:
            return self._credentials

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_FILE.exists():
                    raise FileNotFoundError(
                        "Google credentials not found. "
                        "Download from console.cloud.google.com "
                        "and save to data/google_credentials.json"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                creds = flow.run_local_server(port=0)

            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(creds.to_json())

        self._credentials = creds
        return creds
