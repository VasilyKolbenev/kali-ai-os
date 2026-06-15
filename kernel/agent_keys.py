"""Single source of truth for agent credential requirements.

Agents read their secrets from environment variables (e.g. the Telegram agent
needs ``TELEGRAM_BOT_TOKEN``). This module maps each agent to the keys it needs
so the UI can show an honest status — «Работает» vs «Нужна настройка» — and so
the settings endpoint can accept exactly those keys and nothing else.

Only agents with SIMPLE token/key config are listed. Agents using full OAuth
(email/Gmail) are intentionally absent: they need a flow, not a pasted key, and
surface their own guidance instead.
"""
import os

# agent name → env var names that must ALL be set for the agent to function.
AGENT_REQUIRED_KEYS: dict[str, list[str]] = {
    "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    "messenger-hub": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    "notion": ["NOTION_API_KEY"],
    "todoist": ["TODOIST_API_KEY"],
    "smart-home": ["HA_URL", "HA_TOKEN"],
}

# Flattened whitelist — the settings endpoint accepts ONLY these env names from
# a request body, so a crafted payload can't set arbitrary environment vars.
ALLOWED_AGENT_KEYS: frozenset[str] = frozenset(
    key for keys in AGENT_REQUIRED_KEYS.values() for key in keys
)


def agent_is_configured(agent_name: str) -> bool:
    """True if every required key for the agent is present and non-empty.

    Agents with no key requirement are always considered configured.
    """
    required = AGENT_REQUIRED_KEYS.get(agent_name, [])
    return all(os.environ.get(k, "").strip() for k in required)


def agent_missing_keys(agent_name: str) -> list[str]:
    """Return the required keys that are not yet set for the agent."""
    required = AGENT_REQUIRED_KEYS.get(agent_name, [])
    return [k for k in required if not os.environ.get(k, "").strip()]


def all_agents_config_status() -> dict[str, dict[str, object]]:
    """Per-agent configuration status for the whole registry.

    Returns a mapping ``{agent: {"configured": bool, "missing_keys": [...],
    "required_keys": [...]}}`` for every agent that needs credentials.
    """
    return {
        name: {
            "configured": agent_is_configured(name),
            "missing_keys": agent_missing_keys(name),
            "required_keys": keys,
        }
        for name, keys in AGENT_REQUIRED_KEYS.items()
    }
