"""Email agent — Gmail API integration."""

import base64
import os
import sys
from email.mime.text import MIMEText
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent


class EmailAgent(BaseAgent):
    """Agent for managing email via Gmail API."""

    def __init__(self) -> None:
        super().__init__()
        self._service: Any = None
        self._try_gmail_auth()

    def _try_gmail_auth(self) -> None:
        """Try to connect to Gmail API."""
        try:
            from kernel.integrations.google_auth import GoogleAuth

            auth = GoogleAuth()
            if auth.is_configured() and auth.is_authenticated():
                from googleapiclient.discovery import build

                creds = auth.get_credentials()
                self._service = build("gmail", "v1", credentials=creds)
        except Exception:
            self._service = None

    def get_name(self) -> str:
        return "email"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle email actions: check_inbox, send_email, search_emails.

        Args:
            action: Action name to execute.
            args: Action arguments.

        Returns:
            Action result dictionary.

        Raises:
            ValueError: If action is unknown.
        """
        if action == "check_inbox":
            return self._check_inbox(args)
        elif action == "send_email":
            return self._send_email(args)
        elif action == "search_emails":
            return self._search_emails(args)
        else:
            raise ValueError(f"Unknown action: {action}")

    def _check_inbox(self, args: dict[str, Any]) -> dict[str, Any]:
        """Fetch recent inbox messages.

        Args:
            args: Dictionary with optional 'count' key (default 5).

        Returns:
            Dictionary with emails list, count, and source or error.
        """
        count = args.get("count", 5)

        if not self._service:
            return {
                "emails": [],
                "count": 0,
                "error": "Gmail not configured. Set up Google OAuth first.",
            }

        try:
            results = (
                self._service.users()
                .messages()
                .list(userId="me", maxResults=count, labelIds=["INBOX"])
                .execute()
            )
            messages = results.get("messages", [])

            emails = []
            for msg_ref in messages:
                msg = (
                    self._service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_ref["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    )
                    .execute()
                )
                headers = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                emails.append(
                    {
                        "id": msg_ref["id"],
                        "subject": headers.get("Subject", "(no subject)"),
                        "from": headers.get("From", "unknown"),
                        "date": headers.get("Date", ""),
                        "snippet": msg.get("snippet", ""),
                    }
                )

            return {"emails": emails, "count": len(emails), "source": "gmail"}
        except Exception as e:
            return {"emails": [], "count": 0, "error": str(e)}

    def _send_email(self, args: dict[str, Any]) -> dict[str, Any]:
        """Send an email via Gmail.

        Args:
            args: Dictionary with 'to', 'subject', and 'body' keys.

        Returns:
            Dictionary with status, recipient, and subject or error message.
        """
        to = args.get("to", "")
        subject = args.get("subject", "")
        body = args.get("body", "")

        if not self._service:
            return {"status": "error", "message": "Gmail not configured"}
        if not to:
            return {"status": "error", "message": "Recipient email required"}

        try:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            self._service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return {"status": "sent", "to": to, "subject": subject}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _search_emails(self, args: dict[str, Any]) -> dict[str, Any]:
        """Search emails by Gmail query.

        Args:
            args: Dictionary with 'query' and optional 'count' keys.

        Returns:
            Dictionary with emails list, count, query, or error.
        """
        query = args.get("query", "")
        count = args.get("count", 5)

        if not self._service:
            return {"emails": [], "count": 0, "error": "Gmail not configured"}

        try:
            results = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, maxResults=count)
                .execute()
            )
            messages = results.get("messages", [])

            emails = []
            for msg_ref in messages:
                msg = (
                    self._service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_ref["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    )
                    .execute()
                )
                headers = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                emails.append(
                    {
                        "id": msg_ref["id"],
                        "subject": headers.get("Subject", "(no subject)"),
                        "from": headers.get("From", "unknown"),
                        "date": headers.get("Date", ""),
                        "snippet": msg.get("snippet", ""),
                    }
                )

            return {"emails": emails, "count": len(emails), "query": query}
        except Exception as e:
            return {"emails": [], "count": 0, "error": str(e)}


if __name__ == "__main__":
    EmailAgent().run()
