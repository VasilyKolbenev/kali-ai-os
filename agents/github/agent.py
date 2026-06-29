"""GitHub agent — repos, issues, PRs via GitHub REST API."""

import json
import logging
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from agents._base.agent_base import BaseAgent
from kernel.sandbox.http_client import HttpRequest, SandboxHttpClient, SandboxHttpError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.github.com"


class GitHubAgent(BaseAgent):
    """Agent for interacting with GitHub repositories, issues, and PRs."""

    def __init__(self) -> None:
        super().__init__()
        self._token = ""

    def get_name(self) -> str:
        """Return agent name."""
        return "github"

    def handle_action(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch action to appropriate handler.

        Args:
            action: Action name (my_repos, my_issues, my_prs, repo_status).
            args: Action arguments.

        Returns:
            Result dictionary.
        """
        self._token = os.environ.get("GITHUB_TOKEN", "")
        if not self._token:
            return {"error": "Set GITHUB_TOKEN in Settings to enable this agent"}

        if action == "my_repos":
            return self._my_repos()
        elif action == "my_issues":
            return self._my_issues()
        elif action == "my_prs":
            return self._my_prs()
        elif action == "repo_status":
            return self._repo_status(args.get("owner", ""), args.get("repo", ""))
        else:
            raise ValueError(f"Unknown action: {action}")

    def _api_call(self, path: str) -> Any:
        """Make a GitHub API GET call.

        Args:
            path: API path or full URL.

        Returns:
            Parsed response, or dict with 'error' key on failure.
        """
        url = path if path.startswith("https://") else f"{BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # Route egress through the SSRF/whitelist guard (private-IP block +
        # redirect re-check). Whitelist stays api.github.com so a caller-supplied
        # full URL can't exfiltrate to an arbitrary or private host.
        client = SandboxHttpClient("github", allowed_domains=["api.github.com"])
        try:
            resp = client.request(
                HttpRequest(url=url, method="GET", headers=headers, timeout=10.0)
            )
            return resp.json()
        except SandboxHttpError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    def _my_repos(self) -> dict[str, Any]:
        """List the authenticated user's repos sorted by last update.

        Returns:
            Dict with list of repos.
        """
        result = self._api_call("/user/repos?sort=updated&per_page=10")
        if isinstance(result, dict) and "error" in result:
            return result
        repos = [
            {
                "name": r.get("full_name"),
                "description": r.get("description"),
                "stars": r.get("stargazers_count"),
                "language": r.get("language"),
                "url": r.get("html_url"),
                "updated_at": r.get("updated_at"),
            }
            for r in result
        ]
        return {"repos": repos, "count": len(repos)}

    def _my_issues(self) -> dict[str, Any]:
        """List issues assigned to the authenticated user.

        Returns:
            Dict with list of issues.
        """
        result = self._api_call("/issues?filter=assigned&per_page=10")
        if isinstance(result, dict) and "error" in result:
            return result
        issues = [
            {
                "id": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "repo": i.get("repository", {}).get("full_name") if i.get("repository") else None,
                "url": i.get("html_url"),
                "created_at": i.get("created_at"),
            }
            for i in result
        ]
        return {"issues": issues, "count": len(issues)}

    def _my_prs(self) -> dict[str, Any]:
        """List open pull requests authored by the authenticated user.

        Returns:
            Dict with list of PRs.
        """
        result = self._api_call("/search/issues?q=is:pr+author:@me+is:open")
        if isinstance(result, dict) and "error" in result:
            return result
        items = result.get("items", []) if isinstance(result, dict) else []
        prs = [
            {
                "id": p.get("number"),
                "title": p.get("title"),
                "url": p.get("html_url"),
                "created_at": p.get("created_at"),
                "repository": p.get("repository_url", "").split("/repos/")[-1],
            }
            for p in items
        ]
        return {"prs": prs, "count": len(prs)}

    def _repo_status(self, owner: str, repo: str) -> dict[str, Any]:
        """Get repository information.

        Args:
            owner: Repository owner username or org.
            repo: Repository name.

        Returns:
            Dict with repo info.
        """
        if not owner or not repo:
            return {"error": "owner and repo are required"}
        result = self._api_call(f"/repos/{owner}/{repo}")
        if isinstance(result, dict) and "error" in result:
            return result
        return {
            "name": result.get("full_name"),
            "description": result.get("description"),
            "stars": result.get("stargazers_count"),
            "forks": result.get("forks_count"),
            "open_issues": result.get("open_issues_count"),
            "language": result.get("language"),
            "default_branch": result.get("default_branch"),
            "url": result.get("html_url"),
        }


if __name__ == "__main__":
    GitHubAgent().run()
