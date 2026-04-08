"""Tests for budget manager."""

import pytest

from kernel.budget import BudgetManager
from kernel.event_bus import EventBus


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def budget(bus: EventBus) -> BudgetManager:
    return BudgetManager(bus)


class TestBudgetManager:
    def test_set_goal(self, budget: BudgetManager) -> None:
        result = budget.set_goal("food", 500)
        assert result["limit"] == 500

    async def test_log_expense(self, budget: BudgetManager) -> None:
        budget.set_goal("food", 500)
        result = await budget.log_expense(100, "food")
        assert result["total"] == 100
        assert result["remaining"] == 400

    async def test_budget_warning_at_80(self, budget: BudgetManager, bus: EventBus) -> None:
        received = []

        async def handler(e):
            received.append(e)

        bus.subscribe("budget.alert", handler)
        budget.set_goal("food", 100)
        await budget.log_expense(85, "food")
        assert len(received) == 1
        assert received[0].payload["level"] == "warning"

    async def test_budget_over(self, budget: BudgetManager, bus: EventBus) -> None:
        received = []

        async def handler(e):
            received.append(e)

        bus.subscribe("budget.alert", handler)
        budget.set_goal("food", 100)
        await budget.log_expense(110, "food")
        assert received[0].payload["level"] == "over"

    def test_detect_subscriptions(self, budget: BudgetManager) -> None:
        history = [
            {"amount": 15.99}, {"amount": 15.99}, {"amount": 15.99},
            {"amount": 9.99}, {"amount": 9.99},
            {"amount": 42.50},
        ]
        subs = budget.detect_subscriptions(history)
        assert len(subs) == 2
        assert subs[0]["amount"] == 15.99
