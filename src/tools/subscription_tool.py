"""
Subscription management tools for Progressive Agent.

Three LLM-callable tools:
- subscription_add: add a new subscription
- subscription_list: show all subscriptions with days left
- subscription_remove: remove a subscription
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class SubscriptionAddTool:
    """Add a new recurring subscription to track."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="subscription_add",
            description=(
                "Добавить подписку для отслеживания. "
                "Бот будет напоминать за 3 дня, за 1 день и при продлении."
            ),
            parameters=[
                ToolParameter(
                    name="name",
                    type="string",
                    description="Название подписки (Claude Pro, ChatGPT Plus, Spotify, etc.)",
                    required=True,
                ),
                ToolParameter(
                    name="price",
                    type="number",
                    description="Цена за период (число)",
                    required=True,
                ),
                ToolParameter(
                    name="currency",
                    type="string",
                    description="Валюта: USD, EUR, UAH и т.д.",
                    required=False,
                    default="USD",
                ),
                ToolParameter(
                    name="cycle",
                    type="string",
                    description="Период оплаты",
                    required=False,
                    default="monthly",
                    enum=["monthly", "yearly", "weekly"],
                ),
                ToolParameter(
                    name="next_renewal",
                    type="string",
                    description="Дата следующего списания (YYYY-MM-DD). Если не указана — через 30 дней",
                    required=False,
                ),
                ToolParameter(
                    name="category",
                    type="string",
                    description="Категория (AI, hosting, entertainment, etc.)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        name = kwargs.get("name", "")
        price = kwargs.get("price")

        if not name:
            return ToolResult(success=False, error="Name is required")
        if price is None:
            return ToolResult(success=False, error="Price is required")

        try:
            price = float(price)
        except (TypeError, ValueError):
            return ToolResult(success=False, error=f"Invalid price: {price}")

        result = self._monitor.add(
            name=name,
            price=price,
            currency=kwargs.get("currency", "USD"),
            cycle=kwargs.get("cycle", "monthly"),
            next_renewal=kwargs.get("next_renewal"),
            category=kwargs.get("category", ""),
        )

        if "error" in result:
            return ToolResult(success=False, error=result["error"])

        return ToolResult(success=True, data=result)


class SubscriptionListTool:
    """List all tracked subscriptions with days remaining."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="subscription_list",
            description=(
                "Показать все подписки: название, цена, дней до списания, "
                "итого в месяц по валютам."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        subs = self._monitor.list_all()
        totals = self._monitor.get_monthly_total()

        if not subs:
            return ToolResult(
                success=True,
                data={"subscriptions": [], "message": "Нет отслеживаемых подписок"},
            )

        return ToolResult(
            success=True,
            data={
                "subscriptions": subs,
                "monthly_totals": totals,
                "count": len(subs),
            },
        )


class SubscriptionRemoveTool:
    """Remove a tracked subscription."""

    def __init__(self, monitor: Any) -> None:
        self._monitor = monitor

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="subscription_remove",
            description="Удалить подписку из отслеживания.",
            parameters=[
                ToolParameter(
                    name="name",
                    type="string",
                    description="Название подписки для удаления",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        name = kwargs.get("name", "")
        if not name:
            return ToolResult(success=False, error="Name is required")

        removed = self._monitor.remove(name)
        if removed:
            return ToolResult(success=True, data={"removed": name})
        return ToolResult(
            success=False,
            error=f"Subscription '{name}' not found",
        )
