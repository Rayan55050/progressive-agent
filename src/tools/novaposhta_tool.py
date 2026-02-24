"""
Nova Poshta tool — track parcels, search warehouses, check delivery status.

Uses Nova Poshta API v2.0 (free, API key required).
Docs: https://developers.novaposhta.ua/documentation
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

API_URL = "https://api.novaposhta.ua/v2.0/json/"

# Status codes → human-readable Ukrainian/Russian descriptions
STATUS_MAP = {
    1: "Створено відправником (очікує відправки)",
    2: "Видалено",
    3: "Номер не знайдено",
    4: "В дорозі (в межах міста відправника)",
    5: "В дорозі до міста отримувача",
    6: "Прибув у місто отримувача",
    7: "Прибув на відділення отримувача",
    8: "Прибув у поштомат",
    9: "Отримано одержувачем",
    10: "Отримано, гроші відправлено",
    11: "Отримано, гроші зараховано відправнику",
    12: "Оформлення завершується",
    41: "Доставка в межах міста",
    101: "В дорозі до отримувача (кур'єр)",
    102: "Відмова відправника",
    103: "Відмова отримувача",
    104: "Зміна адреси (переадресація)",
    105: "Зберігання скасовано",
    106: "Отримано + створено зворотню доставку",
    111: "Доставку не виконано, отримувача не знайдено",
    112: "Дату доставки змінено отримувачем",
}

# Status codes considered "delivered"
DELIVERED_STATUSES = {9, 10, 11}

# Status codes considered "in transit"
IN_TRANSIT_STATUSES = {4, 5, 6, 41, 101}


class NovaPoshtaTool:
    """Track Nova Poshta parcels by TTN (tracking number).

    Actions:
    - track: get parcel status by TTN
    - warehouses: find nearby warehouses by city
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="novaposhta",
            description=(
                "Нова Пошта: відстежити посилку за ТТН, знайти відділення. "
                "action=track: статус посилки (ttn обов'язковий). "
                "action=warehouses: пошук відділень (city обов'язковий)."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: track (track parcel by TTN) or warehouses (find offices by city)",
                    required=True,
                    enum=["track", "warehouses"],
                ),
                ToolParameter(
                    name="ttn",
                    type="string",
                    description="Tracking number (ТТН) — 14-digit number. Required for action=track.",
                    required=False,
                ),
                ToolParameter(
                    name="city",
                    type="string",
                    description="City name (Ukrainian or Russian). Required for action=warehouses.",
                    required=False,
                ),
            ],
        )

    async def _api_call(
        self, model: str, method: str, properties: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Make a Nova Poshta API v2.0 call."""
        payload = {
            "apiKey": self._api_key,
            "modelName": model,
            "calledMethod": method,
            "methodProperties": properties,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    API_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Nova Poshta API HTTP %d", resp.status)
                        return None
                    data = await resp.json()
                    if not data.get("success"):
                        errors = data.get("errors", [])
                        logger.warning("Nova Poshta API error: %s", errors)
                        return {"success": False, "errors": errors}
                    return data
        except aiohttp.ClientError as e:
            logger.warning("Nova Poshta connection error: %s", e)
        except Exception as e:
            logger.error("Nova Poshta API call failed: %s", e)
        return None

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "").lower()

        try:
            if action == "track":
                return await self._track(kwargs)
            elif action == "warehouses":
                return await self._warehouses(kwargs)
            else:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Unknown action: {action}. Use: track, warehouses",
                )
        except Exception as exc:
            logger.error("NovaPoshtaTool error (%s): %s", action, exc)
            return ToolResult(success=False, data=None, error=str(exc))

    async def _track(self, kwargs: dict[str, Any]) -> ToolResult:
        ttn = kwargs.get("ttn", "").strip()
        if not ttn:
            return ToolResult(
                success=False, data=None, error="Missing required parameter: ttn"
            )

        data = await self._api_call(
            "TrackingDocument",
            "getStatusDocuments",
            {"Documents": [{"DocumentNumber": ttn, "Phone": ""}]},
        )

        if data is None:
            return ToolResult(
                success=False, data=None, error="Nova Poshta API unavailable"
            )

        if not data.get("success"):
            errors = data.get("errors", ["Unknown error"])
            return ToolResult(success=False, data=None, error=f"API error: {errors}")

        items = data.get("data", [])
        if not items:
            return ToolResult(
                success=False,
                data=None,
                error=f"TTN {ttn} not found",
            )

        item = items[0]
        status_code = item.get("StatusCode")
        status_text = STATUS_MAP.get(
            int(status_code) if status_code else 0,
            item.get("Status", "Unknown"),
        )

        result = {
            "ttn": ttn,
            "status_code": status_code,
            "status": status_text,
            "status_original": item.get("Status", ""),
            "scheduled_delivery": item.get("ScheduledDeliveryDate", ""),
            "actual_delivery": item.get("ActualDeliveryDate", ""),
            "cargo_description": item.get("CargoDescriptionString", ""),
            "cargo_type": item.get("CargoType", ""),
            "weight": item.get("DocumentWeight", ""),
            "cost": item.get("DocumentCost", ""),
            "announced_price": item.get("AnnouncedPrice", ""),
            "amount_to_pay": item.get("AmountToPay", ""),
            "city_sender": item.get("CitySender", ""),
            "city_recipient": item.get("CityRecipient", ""),
            "warehouse_sender": item.get("WarehouseSender", ""),
            "warehouse_recipient": item.get("WarehouseRecipient", ""),
            "recipient_address": item.get("WarehouseRecipientAddress", ""),
            "date_created": item.get("DateCreated", ""),
            "seats_amount": item.get("SeatsAmount", ""),
            "storage_days": item.get("DaysStorageCargo", ""),
            "storage_price": item.get("StoragePrice", ""),
            "tracking_update": item.get("TrackingUpdateDate", ""),
        }

        # Clean up empty values
        result = {k: v for k, v in result.items() if v not in ("", None, 0, "0")}

        return ToolResult(success=True, data=result)

    async def _warehouses(self, kwargs: dict[str, Any]) -> ToolResult:
        city = kwargs.get("city", "").strip()
        if not city:
            return ToolResult(
                success=False, data=None, error="Missing required parameter: city"
            )

        # First, find city ref
        city_data = await self._api_call(
            "Address",
            "getCities",
            {"FindByString": city, "Limit": "5"},
        )

        if not city_data or not city_data.get("success"):
            return ToolResult(
                success=False, data=None, error=f"City '{city}' not found"
            )

        cities = city_data.get("data", [])
        if not cities:
            return ToolResult(
                success=False, data=None, error=f"City '{city}' not found in Nova Poshta directory"
            )

        city_ref = cities[0]["Ref"]
        city_name = cities[0].get("Description", city)

        # Get warehouses for this city
        wh_data = await self._api_call(
            "Address",
            "getWarehouses",
            {"CityRef": city_ref, "Limit": "20"},
        )

        if not wh_data or not wh_data.get("success"):
            return ToolResult(
                success=False, data=None, error="Failed to fetch warehouses"
            )

        warehouses = []
        for wh in wh_data.get("data", [])[:20]:
            warehouses.append({
                "number": wh.get("Number", ""),
                "description": wh.get("Description", ""),
                "address": wh.get("ShortAddress", ""),
                "phone": wh.get("Phone", ""),
                "schedule": wh.get("Schedule", {}).get("Monday", ""),
                "type": wh.get("TypeOfWarehouse", ""),
            })

        return ToolResult(
            success=True,
            data={
                "city": city_name,
                "total_warehouses": len(warehouses),
                "warehouses": warehouses,
            },
        )
