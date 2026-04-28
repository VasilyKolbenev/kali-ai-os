"""In-memory session registry for multi-turn wizard flows."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class SessionNotFound(Exception):
    """Raised when a session_id is unknown or expired."""


@dataclass
class BuilderSession:
    """Tracks state of one builder flow from request to deploy.

    Attributes:
        session_id: Unique identifier for this session (128-bit UUID hex).
        request: Original user request text.
        intent_type: Type of builder flow, either "skill" or "agent".
        template: Optional template name selected for this flow.
        questions: Ordered list of clarifying questions to ask the user.
        answers: User-provided answers, parallel to questions.
        step: Current question index (0-based).
        spec: Final assembled spec dict, populated after all questions answered.
        created_at: Monotonic timestamp of session creation, used for TTL eviction.
    """

    session_id: str
    request: str
    intent_type: str  # "skill" | "agent"
    template: str | None
    name_hint: str | None = None  # NEW — populated by /builder/extract
    questions: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    step: int = 0
    spec: dict[str, Any] | None = None
    created_at: float = field(default_factory=lambda: time.monotonic())

    @property
    def is_complete(self) -> bool:
        return self.step >= len(self.questions)

    @property
    def current_question(self) -> str | None:
        if self.step < len(self.questions):
            return self.questions[self.step]
        return None


class SessionStore:
    """In-memory session store with TTL cleanup. Thread-safe via internal lock."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        """Initialise the store.

        Args:
            ttl_seconds: Seconds after creation before a session is evicted.
                Defaults to 1800 (30 minutes).
        """
        self._sessions: dict[str, BuilderSession] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def create(
        self,
        request: str,
        intent_type: str,
        template: str | None,
    ) -> str:
        """Create a new builder session and return its ID.

        Args:
            request: The original user request text.
            intent_type: Flow type, either "skill" or "agent".
            template: Optional template name to use for this flow.

        Returns:
            A 32-character hex string (128-bit UUID) identifying the new session.
        """
        sid = uuid.uuid4().hex  # 32 chars, 128 bits
        with self._lock:
            self._sessions[sid] = BuilderSession(
                session_id=sid,
                request=request,
                intent_type=intent_type,
                template=template,
            )
        return sid

    def get(self, session_id: str) -> BuilderSession:
        """Retrieve a live session by ID, evicting expired sessions first.

        Args:
            session_id: The session identifier returned by :meth:`create`.

        Returns:
            The :class:`BuilderSession` for the given ID.

        Raises:
            SessionNotFound: If the session_id is unknown or has been evicted.
        """
        with self._lock:
            self._evict_expired()
            if session_id not in self._sessions:
                raise SessionNotFound(session_id)
            return self._sessions[session_id]

    def delete(self, session_id: str) -> None:
        """Remove a session from the store.

        No-op if the session_id is unknown or already evicted.

        Args:
            session_id: The session identifier to remove.
        """
        with self._lock:
            self._sessions.pop(session_id, None)

    def _evict_expired(self) -> None:
        """Remove all sessions whose age exceeds the configured TTL."""
        now = time.monotonic()
        stale = [sid for sid, s in self._sessions.items() if now - s.created_at > self._ttl]
        for sid in stale:
            self._sessions.pop(sid, None)
            logger.debug("Evicted expired builder session: %s", sid)
