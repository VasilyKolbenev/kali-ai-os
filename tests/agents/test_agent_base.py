"""Tests for agent base class."""

from agents._base.agent_base import BaseAgent


class ConcreteTestAgent(BaseAgent):
    """Concrete agent for testing base class."""

    def get_name(self) -> str:
        return "test"

    def handle_action(self, action: str, args: dict) -> dict:
        if action == "greet":
            return {"message": f"Hello, {args.get('name', 'World')}!"}
        raise ValueError(f"Unknown action: {action}")


class TestBaseAgent:
    def test_handle_initialize(self) -> None:
        agent = ConcreteTestAgent()
        result = agent.handle_request(
            {"jsonrpc": "2.0", "method": "initialize", "params": {"config": {}}, "id": 1}
        )
        assert result["result"]["status"] == "ok"

    def test_handle_health(self) -> None:
        agent = ConcreteTestAgent()
        result = agent.handle_request({"jsonrpc": "2.0", "method": "health", "params": {}, "id": 2})
        assert result["result"]["status"] == "healthy"
        assert "uptime_s" in result["result"]

    def test_handle_execute(self) -> None:
        agent = ConcreteTestAgent()
        result = agent.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "execute",
                "params": {"action": "greet", "args": {"name": "Jarvis"}},
                "id": 3,
            }
        )
        assert result["result"]["message"] == "Hello, Jarvis!"

    def test_handle_unknown_method(self) -> None:
        agent = ConcreteTestAgent()
        result = agent.handle_request(
            {"jsonrpc": "2.0", "method": "unknown", "params": {}, "id": 4}
        )
        assert "error" in result

    def test_handle_execute_unknown_action(self) -> None:
        agent = ConcreteTestAgent()
        result = agent.handle_request(
            {
                "jsonrpc": "2.0",
                "method": "execute",
                "params": {"action": "nonexistent", "args": {}},
                "id": 5,
            }
        )
        assert "error" in result
