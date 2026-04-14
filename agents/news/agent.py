"""News agent — top headlines and search via NewsAPI."""

import json
import logging
import os
import sys
import urllib.request
import urllib.parse
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent

logger = logging.getLogger(__name__)

BASE_URL = "https://newsapi.org/v2"


class NewsAgent(BaseAgent):
    """Agent for fetching news headlines and search results via NewsAPI."""

    def __init__(self) -> None:
        super().__init__()
        self._api_key = ""

    def get_name(self) -> str:
        """Return agent name."""
        return "news"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch action to appropriate handler.

        Args:
            action: Action name (top_headlines, search).
            args: Action arguments.

        Returns:
            Result dictionary.
        """
        self._api_key = os.environ.get("NEWS_API_KEY", "")
        if not self._api_key:
            return {"error": "Set NEWS_API_KEY in Settings to enable this agent"}

        if action == "top_headlines":
            return self._top_headlines(
                args.get("country", "ru"),
                args.get("category"),
            )
        elif action == "search":
            return self._search(args.get("query", ""))
        else:
            raise ValueError(f"Unknown action: {action}")

    def _api_call(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        """Make a NewsAPI GET call.

        Args:
            path: API path (e.g. '/top-headlines').
            params: Query parameters dict (apiKey will be added automatically).

        Returns:
            Parsed response dict, or dict with 'error' key on failure.
        """
        params["apiKey"] = self._api_key
        query_string = urllib.parse.urlencode(params)
        url = f"{BASE_URL}{path}?{query_string}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.read().decode()}"}
        except Exception as e:
            return {"error": str(e)}

    def _format_articles(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Extract article list from NewsAPI response.

        Args:
            raw: Raw NewsAPI response.

        Returns:
            Dict with articles list or error.
        """
        if "error" in raw:
            return raw
        if raw.get("status") != "ok":
            return {"error": raw.get("message", "NewsAPI error")}
        articles = [
            {
                "title": a.get("title"),
                "description": a.get("description"),
                "source": a.get("source", {}).get("name"),
                "url": a.get("url"),
                "published_at": a.get("publishedAt"),
            }
            for a in raw.get("articles", [])
        ]
        return {"articles": articles, "count": len(articles)}

    def _top_headlines(self, country: str = "ru", category: str | None = None) -> dict[str, Any]:
        """Fetch top headlines.

        Args:
            country: ISO 3166-1 alpha-2 country code (default 'ru').
            category: Optional category filter (e.g. 'technology', 'sports').

        Returns:
            Dict with articles list.
        """
        params: dict[str, str] = {"country": country, "pageSize": "10"}
        if category:
            params["category"] = category
        raw = self._api_call("/top-headlines", params)
        return self._format_articles(raw)

    def _search(self, query: str) -> dict[str, Any]:
        """Search news articles.

        Args:
            query: Search query string.

        Returns:
            Dict with articles list.
        """
        if not query:
            return {"error": "query is required"}
        params = {"q": query, "pageSize": "5", "sortBy": "publishedAt"}
        raw = self._api_call("/everything", params)
        return self._format_articles(raw)


if __name__ == "__main__":
    NewsAgent().run()
