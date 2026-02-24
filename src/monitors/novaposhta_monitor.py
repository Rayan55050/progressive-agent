"""
Nova Poshta parcel monitor — background tracker for active parcels.

Polls Nova Poshta API every 30 min. Pushes bro-style notification
to Telegram when parcel status changes.

State (tracked TTNs + last statuses) persisted to disk.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

import aiohttp

from src.tools.novaposhta_tool import (
    API_URL,
    DELIVERED_STATUSES,
    STATUS_MAP,
)

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/novaposhta_monitor_state.json")


class NovaPoshtaMonitor:
    """Monitors tracked Nova Poshta parcels for status changes.

    Runs as a scheduled job via APScheduler (every 30 min).
    When a parcel status changes, pushes notification to Telegram.

    Users add/remove parcels via Telegram commands.
    State is persisted to disk.
    """

    def __init__(
        self,
        api_key: str,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        user_id: str = "",
    ) -> None:
        self._api_key = api_key
        self._notify = notify
        self._user_id = user_id
        self._consecutive_errors = 0
        # parcels: {ttn: {name, status_code, last_status, added_at, price, ...}}
        self._parcels: dict[str, dict[str, Any]] = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load tracked parcels from disk."""
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._parcels = data.get("parcels", {})
                logger.info(
                    "Nova Poshta monitor loaded: %d parcels tracked",
                    len(self._parcels),
                )
        except Exception as e:
            logger.warning("Failed to load NovaPoshta monitor state: %s", e)

    def _save_state(self) -> None:
        """Persist tracked parcels to disk."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "parcels": self._parcels,
                "updated_at": int(time.time()),
            }
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save NovaPoshta monitor state: %s", e)

    def add_parcel(self, ttn: str, name: str = "", price: str = "") -> bool:
        """Add a parcel to tracking. Returns True if new, False if already tracked."""
        ttn = ttn.strip()
        if ttn in self._parcels:
            return False
        self._parcels[ttn] = {
            "name": name,
            "status_code": None,
            "last_status": "",
            "price": price,
            "added_at": int(time.time()),
        }
        self._save_state()
        logger.info("Nova Poshta: tracking TTN %s (%s)", ttn, name or "no name")
        return True

    def remove_parcel(self, ttn: str) -> bool:
        """Remove a parcel from tracking."""
        ttn = ttn.strip()
        if ttn in self._parcels:
            del self._parcels[ttn]
            self._save_state()
            return True
        return False

    def list_parcels(self) -> list[dict[str, Any]]:
        """List all tracked parcels with their last known status."""
        result = []
        for ttn, info in self._parcels.items():
            result.append({
                "ttn": ttn,
                "name": info.get("name", ""),
                "status": info.get("last_status", "Unknown"),
                "status_code": info.get("status_code"),
                "price": info.get("price", ""),
                "added_at": info.get("added_at"),
            })
        return result

    async def _fetch_statuses(self, ttns: list[str]) -> list[dict[str, Any]]:
        """Fetch statuses for multiple TTNs in one API call (up to 100)."""
        documents = [{"DocumentNumber": ttn, "Phone": ""} for ttn in ttns]
        payload = {
            "apiKey": self._api_key,
            "modelName": "TrackingDocument",
            "calledMethod": "getStatusDocuments",
            "methodProperties": {"Documents": documents},
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    API_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Nova Poshta API HTTP %d", resp.status)
                        return []
                    data = await resp.json()
                    if data.get("success"):
                        self._consecutive_errors = 0
                        return data.get("data", [])
                    else:
                        logger.warning("Nova Poshta API error: %s", data.get("errors"))
                        return []
        except aiohttp.ClientError as e:
            logger.warning("Nova Poshta connection error: %s", e)
        except Exception as e:
            logger.error("Nova Poshta fetch failed: %s", e)

        self._consecutive_errors += 1
        return []

    def _format_notification(
        self,
        ttn: str,
        name: str,
        old_status: str,
        new_status: str,
        new_code: int,
        item: dict[str, Any],
    ) -> str:
        """Build notification for status change."""
        emoji = self._status_emoji(new_code)
        title = f"{emoji} Нова Пошта"

        if name:
            title += f" — {name}"

        lines = [title, ""]

        lines.append(f"ТТН: {ttn}")
        lines.append(f"Статус: {new_status}")

        if old_status and old_status != new_status:
            lines.append(f"Попередній: {old_status}")

        # Warehouse info
        wh = item.get("WarehouseRecipient") or item.get("WarehouseRecipientAddress")
        if wh and new_code in {7, 8}:
            lines.append(f"Відділення: {wh}")

        # Scheduled delivery
        sched = item.get("ScheduledDeliveryDate")
        if sched and new_code not in DELIVERED_STATUSES:
            lines.append(f"Орієнтовна доставка: {sched}")

        # Payment info
        amount = item.get("AmountToPay") or item.get("DocumentCost")
        if amount and str(amount) != "0":
            lines.append(f"До сплати: {amount} грн")

        # Storage warning
        storage_days = item.get("DaysStorageCargo")
        if storage_days and int(storage_days) > 0:
            lines.append(f"Зберігається: {storage_days} дн.")

        # Delivered celebration
        if new_code in DELIVERED_STATUSES:
            lines.append("")
            lines.append("Посилку отримано!")

        return "\n".join(lines)

    @staticmethod
    def _status_emoji(code: int) -> str:
        """Pick emoji for status code."""
        if code in DELIVERED_STATUSES:
            return "\u2705"  # green check
        if code in {7, 8}:
            return "\U0001F4E6"  # package (arrived at warehouse)
        if code in {4, 5, 6, 41, 101}:
            return "\U0001F69A"  # truck (in transit)
        if code in {102, 103, 111}:
            return "\u274C"  # red X (cancelled/failed)
        if code == 1:
            return "\U0001F4DD"  # memo (created)
        return "\U0001F4E8"  # envelope

    async def check(self) -> None:
        """Check all tracked parcels for status changes."""
        if not self._parcels:
            return

        # Filter out parcels already delivered for 7+ days (auto-cleanup)
        self._cleanup_delivered()

        active_ttns = list(self._parcels.keys())
        if not active_ttns:
            return

        # Batch fetch (up to 100 per request)
        items = await self._fetch_statuses(active_ttns)
        if not items:
            return

        changed = False
        for item in items:
            ttn = item.get("Number", "")
            if ttn not in self._parcels:
                continue

            new_code = item.get("StatusCode")
            try:
                new_code = int(new_code) if new_code else 0
            except (ValueError, TypeError):
                new_code = 0

            new_status = STATUS_MAP.get(new_code, item.get("Status", "Unknown"))
            parcel = self._parcels[ttn]
            old_code = parcel.get("status_code")
            old_status = parcel.get("last_status", "")

            # Status changed?
            if old_code != new_code:
                parcel["status_code"] = new_code
                parcel["last_status"] = new_status

                if new_code in DELIVERED_STATUSES:
                    parcel["delivered_at"] = int(time.time())

                changed = True

                # Notify
                if self._user_id and old_code is not None:
                    name = parcel.get("name", "")
                    text = self._format_notification(
                        ttn, name, old_status, new_status, new_code, item
                    )
                    try:
                        await self._notify(self._user_id, text)
                        logger.info(
                            "Nova Poshta alert: TTN %s → %s (%d)",
                            ttn, new_status, new_code,
                        )
                    except Exception as e:
                        logger.error("Failed to send NovaPoshta notification: %s", e)
                elif old_code is None:
                    # First check — just record status silently
                    logger.info(
                        "Nova Poshta: TTN %s initial status: %s (%d)",
                        ttn, new_status, new_code,
                    )

        if changed:
            self._save_state()

    def _cleanup_delivered(self) -> None:
        """Remove parcels delivered more than 7 days ago."""
        now = int(time.time())
        week = 7 * 24 * 3600
        to_remove = []
        for ttn, info in self._parcels.items():
            delivered_at = info.get("delivered_at")
            if delivered_at and (now - delivered_at) > week:
                to_remove.append(ttn)
        for ttn in to_remove:
            del self._parcels[ttn]
            logger.info("Nova Poshta: auto-removed delivered TTN %s", ttn)
        if to_remove:
            self._save_state()

    def get_status(self) -> dict[str, Any]:
        """Return current monitor status."""
        return {
            "tracked_parcels": len(self._parcels),
            "consecutive_errors": self._consecutive_errors,
            "parcels": self.list_parcels(),
        }
