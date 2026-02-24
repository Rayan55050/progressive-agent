"""
Subscription monitor — tracks recurring payments and notifies before renewal.

Stores subscriptions in data/subscriptions.json.
Runs daily, sends reminders at 3 days, 1 day, and on renewal day.
Auto-advances next_renewal after expiry.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/subscriptions.json")


# Notification templates — bro-style
_REMINDER_3D = [
    "Бро, через 3 дня спишут {price} за {name}",
    "Хэдз ап — {name} ({price}) продлится через 3 дня",
    "Напоминаю: {name} — списание {price} через 3 дня",
]

_REMINDER_1D = [
    "Бро, завтра списание: {name} — {price}",
    "Завтра снимут {price} за {name}, имей в виду",
    "Хэдз ап на завтра: {name} ({price})",
]

_RENEWED = [
    "Подписка продлена: {name} — {price}. Следующее списание {next_date}",
    "{name} продлилась ({price}). Следующая оплата — {next_date}",
    "Бро, {name} ({price}) продлена. Следующий раз — {next_date}",
]


def _advance_renewal(renewal: date, cycle: str) -> date:
    """Advance renewal date to next period."""
    if cycle == "yearly":
        import calendar
        new_year = renewal.year + 1
        max_day = calendar.monthrange(new_year, renewal.month)[1]
        return renewal.replace(year=new_year, day=min(renewal.day, max_day))
    elif cycle == "weekly":
        return renewal + timedelta(weeks=1)
    else:  # monthly (default)
        month = renewal.month + 1
        year = renewal.year
        if month > 12:
            month = 1
            year += 1
        # Handle months with fewer days (e.g., Jan 31 → Feb 28)
        import calendar
        max_day = calendar.monthrange(year, month)[1]
        day = min(renewal.day, max_day)
        return renewal.replace(year=year, month=month, day=day)


def _format_price(price: float, currency: str) -> str:
    """Format price with currency symbol."""
    symbols = {"USD": "$", "EUR": "€", "UAH": "₴", "GBP": "£"}
    sym = symbols.get(currency.upper(), currency + " ")
    if currency.upper() in ("USD", "EUR", "GBP"):
        return f"{sym}{price:.0f}" if price == int(price) else f"{sym}{price:.2f}"
    return f"{price:.0f} {sym}" if price == int(price) else f"{price:.2f} {sym}"


class SubscriptionMonitor:
    """Monitors subscription renewals and sends reminders.

    Runs daily via APScheduler. Sends notifications:
    - 3 days before renewal
    - 1 day before renewal
    - On renewal day (marks as renewed, advances date)

    State persisted to data/subscriptions.json.
    """

    def __init__(
        self,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        user_id: str = "",
    ) -> None:
        self._notify = notify
        self._user_id = user_id
        self._subscriptions: list[dict[str, Any]] = []
        self._load_state()

    def _load_state(self) -> None:
        """Load subscriptions from disk."""
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._subscriptions = data.get("subscriptions", [])
                logger.info(
                    "Subscription monitor loaded: %d subscriptions",
                    len(self._subscriptions),
                )
        except Exception as e:
            logger.warning("Failed to load subscriptions: %s", e)

    def _save_state(self) -> None:
        """Persist subscriptions to disk."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {"subscriptions": self._subscriptions}
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save subscriptions: %s", e)

    def add(
        self,
        name: str,
        price: float,
        currency: str = "USD",
        cycle: str = "monthly",
        next_renewal: str | None = None,
        category: str = "",
    ) -> dict[str, Any]:
        """Add a new subscription.

        Args:
            name: Subscription name (e.g., "Claude Pro").
            price: Price per cycle.
            currency: USD, EUR, UAH, etc.
            cycle: monthly, yearly, weekly.
            next_renewal: Next renewal date (YYYY-MM-DD). Default: 30 days from now.
            category: Optional category (AI, hosting, etc.).

        Returns:
            The created subscription dict.
        """
        # Generate simple ID from name
        sub_id = name.lower().replace(" ", "_").replace("-", "_")

        # Check for duplicates
        for sub in self._subscriptions:
            if sub["id"] == sub_id:
                return {"error": f"Subscription '{name}' already exists"}

        if next_renewal:
            renewal_date = next_renewal
        else:
            renewal_date = (date.today() + timedelta(days=30)).isoformat()

        sub: dict[str, Any] = {
            "id": sub_id,
            "name": name,
            "price": price,
            "currency": currency.upper(),
            "cycle": cycle,
            "next_renewal": renewal_date,
            "category": category,
            "created": date.today().isoformat(),
            "notified_3d": False,
            "notified_1d": False,
        }
        self._subscriptions.append(sub)
        self._save_state()
        logger.info("Subscription added: %s (%s %.2f/%s)", name, currency, price, cycle)
        return sub

    def remove(self, name_or_id: str) -> bool:
        """Remove a subscription by name or ID."""
        key = name_or_id.lower().replace(" ", "_").replace("-", "_")
        for i, sub in enumerate(self._subscriptions):
            if sub["id"] == key or sub["name"].lower() == name_or_id.lower():
                removed = self._subscriptions.pop(i)
                self._save_state()
                logger.info("Subscription removed: %s", removed["name"])
                return True
        return False

    def list_all(self) -> list[dict[str, Any]]:
        """Return all subscriptions with days_left calculated."""
        today = date.today()
        result = []
        for sub in self._subscriptions:
            renewal = date.fromisoformat(sub["next_renewal"])
            days_left = (renewal - today).days
            entry = {**sub, "days_left": days_left}
            result.append(entry)
        # Sort by days_left (closest first)
        result.sort(key=lambda x: x["days_left"])
        return result

    def get_monthly_total(self) -> dict[str, float]:
        """Calculate total monthly cost per currency."""
        totals: dict[str, float] = {}
        for sub in self._subscriptions:
            currency = sub["currency"]
            price = sub["price"]
            cycle = sub["cycle"]
            # Normalize to monthly
            if cycle == "yearly":
                monthly = price / 12
            elif cycle == "weekly":
                monthly = price * 4.33
            else:
                monthly = price
            totals[currency] = totals.get(currency, 0) + monthly
        return totals

    async def check(self) -> None:
        """Daily check — send reminders and advance expired subscriptions."""
        if not self._subscriptions or not self._user_id:
            return

        today = date.today()
        changed = False

        for sub in self._subscriptions:
            try:
                renewal = date.fromisoformat(sub["next_renewal"])
                days_left = (renewal - today).days
                price_str = _format_price(sub["price"], sub["currency"])

                # Renewal day or past due — advance to next period
                # Loop to catch up if multiple periods overdue
                while days_left <= 0:
                    new_renewal = _advance_renewal(renewal, sub["cycle"])
                    renewal = new_renewal
                    days_left = (renewal - today).days

                if sub["next_renewal"] != renewal.isoformat():
                    text = random.choice(_RENEWED).format(
                        name=sub["name"],
                        price=price_str,
                        next_date=renewal.strftime("%d.%m.%Y"),
                    )
                    await self._notify(self._user_id, text)
                    logger.info(
                        "Subscription renewed: %s → next %s",
                        sub["name"],
                        renewal.isoformat(),
                    )
                    sub["next_renewal"] = renewal.isoformat()
                    sub["notified_3d"] = False
                    sub["notified_1d"] = False
                    changed = True

                # 1 day reminder
                elif days_left == 1 and not sub.get("notified_1d"):
                    text = random.choice(_REMINDER_1D).format(
                        name=sub["name"], price=price_str
                    )
                    await self._notify(self._user_id, text)
                    sub["notified_1d"] = True
                    changed = True
                    logger.info("Subscription 1-day reminder: %s", sub["name"])

                # 3 day reminder
                elif days_left == 3 and not sub.get("notified_3d"):
                    text = random.choice(_REMINDER_3D).format(
                        name=sub["name"], price=price_str
                    )
                    await self._notify(self._user_id, text)
                    sub["notified_3d"] = True
                    changed = True
                    logger.info("Subscription 3-day reminder: %s", sub["name"])
            except Exception as e:
                logger.error("Subscription check failed for %s: %s", sub.get("name", "?"), e)

        if changed:
            self._save_state()
