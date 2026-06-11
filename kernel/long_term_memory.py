"""Long-term memory module for KALI AI OS.

Extracts and stores facts about the user into the Database.
"""

import asyncio
import json
import logging

from kernel.database import Database
from kernel.llm_router import LLMRequest, LLMRouter

logger = logging.getLogger(__name__)


from kernel.models import LLMConfig

class LongTermMemory:
    """Manages persistent facts and context about the user."""

    def __init__(self, db: Database, llm_config: LLMConfig) -> None:
        self._db = db
        self._llm = LLMRouter(llm_config)

    # Facts are injected into EVERY prompt; without a cap they grow unbounded
    # over months of use (prompt bloat = cost + quality). Newest-first cap
    # until dedup/supersede lands (facts come ORDER BY timestamp DESC).
    MAX_INJECTED_FACTS = 50

    async def get_user_context_string(self) -> str:
        """Get recent stored facts formatted as a prompt context."""
        facts = await self._db.get_user_facts()
        if not facts:
            return ""

        context = "<UserFacts>\n"
        for f in facts[: self.MAX_INJECTED_FACTS]:
            context += f"- {f['topic']}: {f['fact']}\n"
        context += "</UserFacts>\n"
        return context

    async def maybe_extract_and_save_facts(self, transcript: str) -> None:
        """Asynchronously process transcript to extract user facts."""
        # We fire and forget this task so it doesn't block the main conversation
        asyncio.create_task(self._extract_facts_bg(transcript))

    async def _extract_facts_bg(self, transcript: str) -> None:
        """Background task to extract facts via LLM."""
        prompt = (
            "Analyze the following user utterance and extract any new permanent facts "
            "about the user (e.g. name, preferences, job, family, location).\n"
            "If there are no permanent facts, return an empty JSON array [].\n"
            "If there are facts, return a JSON array of objects with keys 'topic' and 'fact'.\n"
            "Output ONLY valid JSON.\n\n"
            f"User Utterance: {transcript}"
        )

        request = LLMRequest(
            text=prompt,
            context=[],
            available_tools=[],
            system_prompt="You are a JSON fact extractor. Output strictly JSON.",
        )
        
        try:
            # For extraction, a fast local model or gpt-4o-mini is best
            response = await self._llm.route(request)
            text = response.text.strip()
            
            # Clean markdown block if present
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            if not text or text == "[]":
                return
                
            facts = json.loads(text)
            for f in facts:
                topic = f.get("topic", "general")
                fact = f.get("fact", "")
                if fact:
                    await self._db.save_user_fact(topic, fact)
                    logger.info("Saved new user fact: %s -> %s", topic, fact)
        except Exception as e:
            logger.warning("Failed to extract facts: %s", e)
