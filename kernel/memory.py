"""Conversation memory — persistent context across sessions."""

import logging

from kernel.database import Database

logger = logging.getLogger(__name__)

MAX_CONTEXT_TURNS = 20


class ConversationMemory:
    """Stores and retrieves conversation history for LLM context."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._session_context: list[dict[str, str]] = []

    def add_turn(self, role: str, content: str) -> None:
        """Add a conversation turn to memory."""
        self._session_context.append({"role": role, "content": content})
        if len(self._session_context) > MAX_CONTEXT_TURNS * 2:
            self._session_context = self._session_context[-MAX_CONTEXT_TURNS * 2 :]

    def get_context(self, max_turns: int = MAX_CONTEXT_TURNS) -> list[dict[str, str]]:
        """Get recent conversation context for LLM."""
        return self._session_context[-max_turns * 2 :]

    def clear(self) -> None:
        """Clear session context."""
        self._session_context.clear()

    async def save_interaction(
        self,
        transcript: str,
        intent: str | None = None,
        agent: str | None = None,
        response: str = "",
        latency_ms: int = 0,
    ) -> None:
        """Persist interaction to database."""
        await self._db.save_conversation(
            transcript=transcript,
            intent=intent,
            agent=agent,
            response=response,
            latency_ms=latency_ms,
        )
