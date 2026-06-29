"""Notion agent — search, read, and create pages via Notion API."""

import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent
from kernel.sandbox.http_client import HttpRequest, SandboxHttpClient, SandboxHttpError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionAgent(BaseAgent):
    """Agent for interacting with Notion pages and databases."""

    def __init__(self) -> None:
        super().__init__()
        self._api_key = ""

    def get_name(self) -> str:
        """Return agent name."""
        return "notion"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch action to appropriate handler.

        Args:
            action: Action name (search, get_page, create_page).
            args: Action arguments.

        Returns:
            Result dictionary.
        """
        self._api_key = os.environ.get("NOTION_API_KEY", "")
        if not self._api_key:
            return {"error": "Set NOTION_API_KEY in Settings to enable this agent"}

        if action == "search":
            return self._search(args.get("query", ""))
        elif action == "get_page":
            return self._get_page(args.get("page_id", ""))
        elif action == "create_page":
            return self._create_page(
                args.get("title", ""),
                args.get("content", ""),
                args.get("database_id"),
            )
        else:
            raise ValueError(f"Unknown action: {action}")

    def _api_call(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        """Make a Notion API call.

        Args:
            method: HTTP method (GET, POST).
            path: API path (e.g. '/search').
            body: Optional request body for POST requests.

        Returns:
            Parsed response dict, or dict with 'error' key on failure.
        """
        url = f"{BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Notion-Version": NOTION_VERSION,
            "Accept": "application/json",
        }
        # Route egress through the SSRF/whitelist guard (private-IP block +
        # redirect re-check). Whitelist is api.notion.com only.
        client = SandboxHttpClient("notion", allowed_domains=["api.notion.com"])
        try:
            resp = client.request(
                HttpRequest(
                    url=url,
                    method=method,
                    headers=headers,
                    json_body=body,
                    timeout=10.0,
                )
            )
            return resp.json()
        except SandboxHttpError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def _search(self, query: str) -> dict[str, Any]:
        """Search Notion pages and databases.

        Args:
            query: Search query string.

        Returns:
            Dict with list of matching results.
        """
        result = self._api_call("POST", "/search", {"query": query, "page_size": 10})
        if "error" in result:
            return result
        items = []
        for obj in result.get("results", []):
            obj_type = obj.get("object", "")
            title = ""
            if obj_type == "page":
                props = obj.get("properties", {})
                title_prop = props.get("title") or props.get("Name") or {}
                title_parts = title_prop.get("title", []) if isinstance(title_prop, dict) else []
                title = "".join(p.get("plain_text", "") for p in title_parts)
            elif obj_type == "database":
                title_arr = obj.get("title", [])
                title = "".join(p.get("plain_text", "") for p in title_arr)
            items.append({"id": obj.get("id"), "type": obj_type, "title": title})
        return {"results": items, "count": len(items)}

    def _get_page(self, page_id: str) -> dict[str, Any]:
        """Get a Notion page by ID.

        Args:
            page_id: The Notion page UUID.

        Returns:
            Dict with page properties.
        """
        if not page_id:
            return {"error": "page_id is required"}
        result = self._api_call("GET", f"/pages/{page_id}")
        if "error" in result:
            return result
        props = result.get("properties", {})
        title_prop = props.get("title") or props.get("Name") or {}
        title_parts = title_prop.get("title", []) if isinstance(title_prop, dict) else []
        title = "".join(p.get("plain_text", "") for p in title_parts)
        return {
            "id": result.get("id"),
            "title": title,
            "url": result.get("url"),
            "created_time": result.get("created_time"),
            "last_edited_time": result.get("last_edited_time"),
        }

    def _create_page(self, title: str, content: str, database_id: str | None = None) -> dict[str, Any]:
        """Create a new Notion page.

        Args:
            title: Page title.
            content: Page text content.
            database_id: Optional parent database ID. If None, creates in workspace.

        Returns:
            Dict with new page id and url.
        """
        if not title:
            return {"error": "title is required"}

        if database_id:
            parent = {"database_id": database_id}
            properties: dict[str, Any] = {
                "Name": {"title": [{"text": {"content": title}}]}
            }
        else:
            return {"error": "database_id is required to create a page (workspace-root pages require integration bot to be added to a page)"}

        body: dict[str, Any] = {
            "parent": parent,
            "properties": properties,
        }
        if content:
            body["children"] = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": content}}]
                    },
                }
            ]

        result = self._api_call("POST", "/pages", body)
        if "error" in result:
            return result
        return {"id": result.get("id"), "url": result.get("url"), "created": True}


if __name__ == "__main__":
    NotionAgent().run()
