# Real API Integrations + New Features Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Connect Jarvis to real services (Google Calendar, Gmail, Telegram) and add features that differentiate from failed Rabbit R1: conversation memory, notification system, email agent, Telegram remote control.

**Lessons from Rabbit R1 applied:**
- No fake capabilities — every feature actually works
- Desktop-first (not limited hardware)
- Open plugin system instead of locked ecosystem
- Conversation memory — the AI remembers context
- Real integrations, not browser automation hacks

---

## Sub-project A: Conversation Memory + Notifications

### Task 1: Conversation Memory

The LLM Router currently has no persistent memory. Add conversation history storage so Jarvis remembers past interactions across sessions.

**Modify `kernel/llm_router.py`:**
- Add `ConversationMemory` class that stores/retrieves history from Database
- LLM Router injects recent history into every request

**Create `kernel/memory.py`:**
```python
"""Conversation memory — persistent context across sessions."""

import logging
from typing import Any

from kernel.database import Database

logger = logging.getLogger(__name__)

MAX_CONTEXT_TURNS = 20


class ConversationMemory:
    """Stores and retrieves conversation history for LLM context."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._session_context: list[dict[str, str]] = []

    def add_turn(self, role: str, content: str) -> None:
        self._session_context.append({"role": role, "content": content})
        if len(self._session_context) > MAX_CONTEXT_TURNS * 2:
            self._session_context = self._session_context[-MAX_CONTEXT_TURNS * 2:]

    def get_context(self, max_turns: int = MAX_CONTEXT_TURNS) -> list[dict[str, str]]:
        return self._session_context[-max_turns * 2:]

    def clear(self) -> None:
        self._session_context.clear()

    async def save_interaction(
        self, transcript: str, intent: str | None, agent: str | None,
        response: str, latency_ms: int,
    ) -> None:
        await self._db.save_conversation(
            transcript=transcript, intent=intent, agent=agent,
            response=response, latency_ms=latency_ms,
        )
```

**Create `tests/kernel/test_memory.py`**

Commit: `feat: conversation memory for persistent LLM context`

---

### Task 2: Notification System

Create a notification agent that can send desktop notifications and queue them for Telegram.

**Create `kernel/notifications.py`:**
```python
"""Cross-platform notification system."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)


@dataclass
class Notification:
    title: str
    message: str
    priority: str = "normal"  # low, normal, high, urgent
    source: str = "system"
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class NotificationManager:
    """Manages notifications — desktop, queue for Telegram, event bus."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._queue: list[Notification] = []
        self._handlers: list[Any] = []

    async def send(self, notification: Notification) -> None:
        self._queue.append(notification)
        await self._bus.publish(Event(
            topic="notification.new",
            source=notification.source,
            payload={
                "title": notification.title,
                "message": notification.message,
                "priority": notification.priority,
            },
        ))
        self._try_desktop_notification(notification)
        logger.info("Notification: %s — %s", notification.title, notification.message)

    def get_pending(self) -> list[Notification]:
        return list(self._queue)

    def clear_pending(self) -> None:
        self._queue.clear()

    def _try_desktop_notification(self, notification: Notification) -> None:
        try:
            from plyer import notification as desktop_notif
            desktop_notif.notify(
                title=notification.title,
                message=notification.message,
                timeout=5,
            )
        except ImportError:
            pass
        except Exception:
            logger.debug("Desktop notification failed (non-critical)")
```

Add `plyer>=2.1.0` to pyproject.toml.

Commit: `feat: notification system with desktop and event bus support`

---

## Sub-project B: Google Calendar + Gmail Integration

### Task 3: Google OAuth Helper

Create a shared Google OAuth module for Calendar and Gmail.

**Create `kernel/integrations/__init__.py`**
**Create `kernel/integrations/google_auth.py`:**
```python
"""Google OAuth 2.0 helper for Calendar and Gmail APIs."""

import json
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
        return CREDENTIALS_FILE.exists()

    def is_authenticated(self) -> bool:
        return TOKEN_FILE.exists()

    def get_credentials(self) -> Any:
        if self._credentials:
            return self._credentials

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request

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
                            "Download from console.cloud.google.com and save to data/google_credentials.json"
                        )
                    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
                    creds = flow.run_local_server(port=0)

                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                TOKEN_FILE.write_text(creds.to_json())

            self._credentials = creds
            return creds

        except ImportError:
            logger.warning("google-auth libraries not installed")
            raise
```

Add to pyproject.toml:
```
"google-auth>=2.35.0",
"google-auth-oauthlib>=1.2.0",
"google-api-python-client>=2.150.0",
```

Commit: `feat: Google OAuth helper for Calendar and Gmail`

---

### Task 4: Google Calendar Agent (Real API)

**Update `agents/calendar/agent.py`** to use Google Calendar API when configured, fallback to local JSON.

Key changes:
- Try to import googleapiclient, if available + authenticated, use real API
- If not, fallback to local JSON (current behavior)
- `get_events` fetches from Google Calendar
- `create_event` creates in Google Calendar
- `delete_event` deletes from Google Calendar

Commit: `feat: Google Calendar integration with local fallback`

---

### Task 5: Email/Gmail Agent

**Create `agents/email/manifest.yaml`:**
```yaml
name: email
version: "1.0.0"
description: "Email management via Gmail API"
capabilities:
  - email.read
  - email.send
  - email.search
tools:
  - name: check_inbox
    description: "Check recent emails"
    parameters:
      count: { type: integer, description: "Number of emails to fetch (default 5)" }
  - name: read_email
    description: "Read a specific email"
    parameters:
      email_id: { type: string, description: "Email ID" }
  - name: send_email
    description: "Send an email"
    parameters:
      to: { type: string, description: "Recipient email" }
      subject: { type: string, description: "Subject" }
      body: { type: string, description: "Email body text" }
  - name: search_emails
    description: "Search emails by query"
    parameters:
      query: { type: string, description: "Search query" }
      count: { type: integer, description: "Max results" }
protocol: native
permissions:
  - network
```

**Create `agents/email/agent.py`** — Gmail API integration via google-api-python-client.

Commit: `feat: email/Gmail agent with inbox, send, search`

---

## Sub-project C: Telegram Bot Integration

### Task 6: Telegram Bot Agent

This is a bidirectional integration — Jarvis can send messages to Telegram AND receive commands from Telegram.

**Create `agents/telegram/manifest.yaml`:**
```yaml
name: telegram
version: "1.0.0"
description: "Telegram bot — remote control and notifications"
capabilities:
  - telegram.send
  - telegram.receive
  - telegram.notify
tools:
  - name: send_message
    description: "Send a message to Telegram"
    parameters:
      text: { type: string, description: "Message text" }
  - name: send_notification
    description: "Send a notification to Telegram"
    parameters:
      title: { type: string, description: "Notification title" }
      message: { type: string, description: "Notification body" }
protocol: native
permissions:
  - network
```

**Create `agents/telegram/agent.py`:**
- Uses `python-telegram-bot` library
- Bot token from env var `TELEGRAM_BOT_TOKEN`
- Chat ID from env var `TELEGRAM_CHAT_ID`
- `send_message` — sends text to configured chat
- `send_notification` — sends formatted notification
- Background polling for incoming commands (forward to kernel via stdout events)

Add to pyproject.toml: `"python-telegram-bot>=21.0"`

**Create `agents/telegram/bot_runner.py`:**
Separate script that runs the Telegram bot polling loop and forwards commands to the kernel via HTTP API.

Commit: `feat: Telegram bot agent with send/receive and notifications`

---

## Sub-project D: New Features (R1 lessons)

### Task 7: Weather Agent

Rabbit R1 couldn't even give weather — we'll have it. Free API, no auth needed.

**Create `agents/weather/manifest.yaml` + `agent.py`:**
- Uses Open-Meteo API (free, no key needed)
- `get_weather` — current weather for a city
- `get_forecast` — 3-day forecast

Commit: `feat: weather agent with Open-Meteo API`

---

### Task 8: Wire Everything into Kernel

- Add ConversationMemory to `kernel/main.py`
- Add NotificationManager to `kernel/main.py`
- Add notification forwarding to Telegram (if configured)
- Update CLAUDE.md with new agents and setup instructions
- Update `.env.example` with Google, Telegram env vars

Commit: `feat: wire memory, notifications, new agents into kernel`

---

### Task 9: Final Tests + Verification

- E2E tests for new agents
- Test conversation memory
- Test notification flow
- Lint + format
- Verify all 7+ new agents discovered by kernel

---

## Summary

After this sub-project:
- **Conversation Memory** — Jarvis remembers past conversations
- **Notifications** — desktop + Telegram
- **Google Calendar** — real events from your calendar
- **Gmail** — check inbox, send emails by voice
- **Telegram Bot** — remote control Jarvis from phone
- **Weather** — current weather + forecast (Open-Meteo)
- **8 agents total** (system, tasks, calendar, life-dashboard, smart-home, coding, email, telegram, weather = 9)
