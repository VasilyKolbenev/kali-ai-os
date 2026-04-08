"""Budget tracking with goals and subscription detection."""

import logging
from typing import Any

from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)


class BudgetManager:
    """Tracks spending against budget goals and detects subscriptions."""

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus
        self._goals: dict[str, float] = {}  # category -> monthly limit
        self._spending: dict[str, float] = {}  # category -> current month total

    def set_goal(self, category: str, monthly_limit: float) -> dict[str, Any]:
        """Set a monthly budget limit for a category.

        Args:
            category: Expense category name.
            monthly_limit: Maximum monthly spend in dollars.

        Returns:
            Confirmation dict with status, category, limit.
        """
        self._goals[category] = monthly_limit
        return {"status": "set", "category": category, "limit": monthly_limit}

    def get_goals(self) -> dict[str, Any]:
        """Get all budget goals with current spending status.

        Returns:
            Dict mapping category to limit, spent, remaining, percent.
        """
        result = {}
        for cat, limit in self._goals.items():
            spent = self._spending.get(cat, 0)
            result[cat] = {
                "limit": limit,
                "spent": spent,
                "remaining": limit - spent,
                "percent": round(spent / limit * 100) if limit else 0,
            }
        return result

    async def log_expense(self, amount: float, category: str) -> dict[str, Any]:
        """Log an expense and check against budget goals.

        Args:
            amount: Expense amount in dollars.
            category: Expense category name.

        Returns:
            Dict with logged amount, total, and optional warning/budget info.
        """
        self._spending[category] = self._spending.get(category, 0) + amount
        spent = self._spending[category]
        result: dict[str, Any] = {"logged": amount, "category": category, "total": spent}

        # Check budget warning
        if category in self._goals:
            limit = self._goals[category]
            pct = spent / limit * 100 if limit else 0
            result["budget_limit"] = limit
            result["budget_percent"] = round(pct)
            result["remaining"] = limit - spent

            if pct >= 100:
                result["warning"] = "over_budget"
                await self._bus.publish(Event(
                    topic="budget.alert",
                    source="budget-manager",
                    payload={"category": category, "level": "over", "percent": round(pct)},
                ))
            elif pct >= 80:
                result["warning"] = "approaching_limit"
                await self._bus.publish(Event(
                    topic="budget.alert",
                    source="budget-manager",
                    payload={"category": category, "level": "warning", "percent": round(pct)},
                ))

        return result

    def detect_subscriptions(self, spending_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect recurring expenses that look like subscriptions.

        Args:
            spending_history: List of expense dicts with 'amount' key.

        Returns:
            List of suspected subscriptions sorted by amount descending.
        """
        from collections import Counter
        amounts: Counter[float] = Counter()
        for entry in spending_history:
            amount = entry.get("amount", 0)
            if amount > 0:
                amounts[round(amount, 2)] += 1

        subs = []
        for amount, count in amounts.items():
            if count >= 2:
                subs.append({"amount": amount, "occurrences": count, "monthly_estimate": amount})

        return sorted(subs, key=lambda x: x["amount"], reverse=True)

    def reset_monthly(self) -> None:
        """Reset all monthly spending totals."""
        self._spending.clear()
