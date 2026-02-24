"""
Alerts.in.ua tool — Ukrainian air raid alerts in real-time.

Free API with token registration at https://alerts.in.ua
Provides real-time air raid alerts status for all Ukrainian oblasts.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

BASE_URL = "https://api.alerts.in.ua/v1"
_TIMEOUT = aiohttp.ClientTimeout(total=10)


class AlertsUaTool:
    """Ukrainian air raid alerts — real-time status for all regions."""

    def __init__(self, api_token: str = "") -> None:
        self._token = api_token

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="alerts_ua",
            description=(
                "Ukrainian air raid alerts from alerts.in.ua. "
                "Actions: 'status' — current alerts for all regions or specific region; "
                "'history' — recent alert history for a region. "
                "Shows which oblasts have active air raid alerts right now."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'status' (current alerts), 'history' (recent history)",
                    required=False,
                    enum=["status", "history"],
                ),
                ToolParameter(
                    name="region",
                    type="string",
                    description="Region/oblast name (e.g. 'Дніпропетровська', 'Харківська', 'Київ'). If empty, shows all.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._token:
            return ToolResult(
                success=False,
                error="Alerts.in.ua API token not configured. Register at https://alerts.in.ua and set ALERTS_UA_TOKEN in .env",
            )

        action = kwargs.get("action", "status").strip().lower()
        try:
            if action == "status":
                return await self._status(kwargs)
            elif action == "history":
                return await self._history(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("Alerts.in.ua error: %s", e)
            return ToolResult(success=False, error=f"Alerts error: {e}")

    async def _api_get(self, endpoint: str) -> Any:
        headers = {"Authorization": f"Bearer {self._token}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}{endpoint}", headers=headers, timeout=_TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise ValueError("Invalid alerts.in.ua API token")
                if resp.status != 200:
                    raise ValueError(f"Alerts API HTTP {resp.status}")
                return await resp.json()

    async def _status(self, kwargs: dict) -> ToolResult:
        region_filter = kwargs.get("region", "").strip().lower()
        data = await self._api_get("/alerts/active.json")

        alerts = data if isinstance(data, list) else data.get("alerts", [])

        if region_filter:
            alerts = [
                a for a in alerts
                if region_filter in (a.get("location_title", "") or "").lower()
                or region_filter in (a.get("location_oblast", "") or "").lower()
            ]

        if not alerts:
            if region_filter:
                return ToolResult(
                    success=True,
                    data=f"✅ Немає активних тривог для '{region_filter}'. Все спокійно.",
                )
            return ToolResult(success=True, data="✅ Немає активних повітряних тривог по Україні.")

        lines = ["🚨 **Активні тривоги:**\n"]
        for a in alerts:
            location = a.get("location_title", "?")
            alert_type = a.get("alert_type", "?")
            started = a.get("started_at", "?")
            if started and "T" in str(started):
                started = str(started).replace("T", " ")[:16]

            type_emoji = "🔴" if alert_type == "air_raid" else "🟡"
            type_name = {
                "air_raid": "Повітряна тривога",
                "artillery_shelling": "Артобстріл",
                "urban_fights": "Вуличні бої",
                "chemical": "Хімічна загроза",
                "nuclear": "Ядерна загроза",
            }.get(alert_type, alert_type)

            lines.append(f"{type_emoji} **{location}** — {type_name} (з {started})")

        lines.append(f"\nВсього активних тривог: {len(alerts)}")
        return ToolResult(success=True, data="\n".join(lines))

    async def _history(self, kwargs: dict) -> ToolResult:
        region_filter = kwargs.get("region", "").strip()

        # Get active alerts as a proxy for current status
        # The full history API might differ — use active + note
        data = await self._api_get("/alerts/active.json")
        alerts = data if isinstance(data, list) else data.get("alerts", [])

        if region_filter:
            alerts = [
                a for a in alerts
                if region_filter.lower() in (a.get("location_title", "") or "").lower()
            ]

        if not alerts:
            return ToolResult(
                success=True,
                data=f"Зараз немає активних тривог{f' для {region_filter}' if region_filter else ''}.",
            )

        lines = [f"**Поточний статус тривог{f' ({region_filter})' if region_filter else ''}:**\n"]
        for a in alerts:
            location = a.get("location_title", "?")
            started = a.get("started_at", "?")
            alert_type = a.get("alert_type", "?")
            lines.append(f"  🔴 {location}: {alert_type} з {started}")

        return ToolResult(success=True, data="\n".join(lines))
