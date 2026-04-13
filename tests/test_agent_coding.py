"""Tests for the coding agent with mocked Anthropic client."""

from unittest.mock import MagicMock, patch
import pytest


def _make_agent(api_key: str = "test-key") -> "CodingAgent":
    """Create a CodingAgent with a controlled ANTHROPIC_API_KEY."""
    import os
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": api_key}):
        from agents.coding.agent import CodingAgent
        return CodingAgent()


def _mock_response(text: str) -> MagicMock:
    """Build a minimal Anthropic messages.create() response mock."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


# ---------------------------------------------------------------------------
# explain_code
# ---------------------------------------------------------------------------

class TestExplainCode:
    def test_explain_code_returns_explanation_from_api(self) -> None:
        agent = _make_agent()
        expected = "This function adds two numbers."

        with patch("agents.coding.agent.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_response(expected)
            result = agent.handle_action("explain_code", {"code": "def add(a, b): return a+b", "language": "python"})

        assert result["explanation"] == expected

    def test_explain_code_passes_language_in_prompt(self) -> None:
        agent = _make_agent()

        with patch("agents.coding.agent.Anthropic") as mock_cls:
            mock_create = mock_cls.return_value.messages.create
            mock_create.return_value = _mock_response("ok")
            agent.handle_action("explain_code", {"code": "let x = 1;", "language": "javascript"})
            call_kwargs = mock_create.call_args
            messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages") or call_kwargs[0][2]
            assert "javascript" in messages[0]["content"]


# ---------------------------------------------------------------------------
# review_code
# ---------------------------------------------------------------------------

class TestReviewCode:
    def test_review_code_returns_review_from_api(self) -> None:
        agent = _make_agent()
        expected = "Looks good overall. Consider adding type hints."

        with patch("agents.coding.agent.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_response(expected)
            result = agent.handle_action("review_code", {"code": "def foo(): pass"})

        assert result["review"] == expected
        assert result["issues"] == []

    def test_review_code_includes_empty_issues_list(self) -> None:
        agent = _make_agent()

        with patch("agents.coding.agent.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_response("no issues")
            result = agent.handle_action("review_code", {"code": "x = 1", "language": "python"})

        assert "issues" in result
        assert isinstance(result["issues"], list)


# ---------------------------------------------------------------------------
# suggest_improvement
# ---------------------------------------------------------------------------

class TestSuggestImprovement:
    def test_suggest_improvement_returns_suggestion_from_api(self) -> None:
        agent = _make_agent()
        expected = "Use list comprehension instead of a loop."

        with patch("agents.coding.agent.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_response(expected)
            result = agent.handle_action("suggest_improvement", {"code": "result = []\nfor i in range(10):\n    result.append(i)"})

        assert result["suggestion"] == expected

    def test_suggest_improvement_passes_code_in_prompt(self) -> None:
        agent = _make_agent()
        snippet = "for i in range(10): pass"

        with patch("agents.coding.agent.Anthropic") as mock_cls:
            mock_create = mock_cls.return_value.messages.create
            mock_create.return_value = _mock_response("ok")
            agent.handle_action("suggest_improvement", {"code": snippet, "language": "python"})
            call_kwargs = mock_create.call_args
            messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages") or call_kwargs[0][2]
            assert snippet in messages[0]["content"]


# ---------------------------------------------------------------------------
# Fallback (no API key)
# ---------------------------------------------------------------------------

class TestFallbackWithoutApiKey:
    def _make_no_key_agent(self) -> "CodingAgent":
        import os
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            from importlib import reload
            import agents.coding.agent as mod
            reload(mod)
            return mod.CodingAgent()

    def test_explain_code_fallback_when_no_api_key(self) -> None:
        import os
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            from importlib import reload
            import agents.coding.agent as mod
            reload(mod)
            agent = mod.CodingAgent()
            result = agent.handle_action("explain_code", {"code": "x = 1\ny = 2", "language": "python"})
        assert "explanation" in result
        assert "v2" in result["explanation"]

    def test_review_code_fallback_when_no_api_key(self) -> None:
        import os
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            from importlib import reload
            import agents.coding.agent as mod
            reload(mod)
            agent = mod.CodingAgent()
            result = agent.handle_action("review_code", {"code": "x = 1"})
        assert "review" in result
        assert result["issues"] == []

    def test_suggest_improvement_fallback_when_no_api_key(self) -> None:
        import os
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            from importlib import reload
            import agents.coding.agent as mod
            reload(mod)
            agent = mod.CodingAgent()
            result = agent.handle_action("suggest_improvement", {"code": "x = 1"})
        assert "suggestions" in result
        assert isinstance(result["suggestions"], list)

    def test_unknown_action_raises_value_error(self) -> None:
        agent = _make_agent()
        with patch("agents.coding.agent.Anthropic"):
            with pytest.raises(ValueError, match="Unknown action"):
                agent.handle_action("nonexistent_action", {})
