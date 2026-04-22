"""In-memory session registry for multi-turn wizard flows."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class SessionNotFound(KeyError):
    """Raised when a session_id is unknown or expired."""


@dataclass
class BuilderSession:
    """Tracks state of one builder flow from request → deploy."""

    session_id: str
    request: str
    intent_type: str  # "skill" | "agent"
    template: str | None
    questions: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    step: int = 0
    spec: dict[str, Any] | None = None
    created_at: float = 0.0

    @property
    def is_complete(self) -> bool:
        return self.step >= len(self.questions)

    @property
    def current_question(self) -> str | None:
        if self.step < len(self.questions):
            return self.questions[self.step]
        return None


class SessionStore:
    """Thread-local in-memory session store with TTL cleanup."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._sessions: dict[str, BuilderSession] = {}
        self._ttl = ttl_seconds

    def create(
        self,
        request: str,
        intent_type: str,
        template: str | None,
    ) -> str:
        sid = uuid.uuid4().hex[:12]
        self._sessions[sid] = BuilderSession(
            session_id=sid,
            request=request,
            intent_type=intent_type,
            template=template,
            created_at=time.monotonic(),
        )
        return sid

    def get(self, session_id: str) -> BuilderSession:
        self._evict_expired()
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        return self._sessions[session_id]

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        stale = [sid for sid, s in self._sessions.items() if now - s.created_at > self._ttl]
        for sid in stale:
            del self._sessions[sid]
            logger.debug("Evicted expired builder session: %s", sid)
