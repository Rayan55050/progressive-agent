"""
Monobank monitor — background transaction tracker.

Polls /personal/statement every N minutes.
Pushes bro-style notification to Telegram on new transactions.

State (last seen transaction ID) persisted to disk so bot restarts
don't cause missed or duplicate notifications.

Rate limit: Monobank allows 1 personal request per 60 seconds.
Monitor interval should be >= 2 minutes to leave room for user queries.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

from src.tools.monobank_tool import (
    ACCOUNT_TYPES,
    CURRENCY_MAP,
    MonobankService,
    _format_amount,
    _format_balance,
    _get_mcc_category,
)

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/monobank_monitor_state.json")

# Bro-style notification templates
_EXPENSE_GREETINGS = [
    "Бро, списание с карты!",
    "Йо, потратился!",
    "Деньги ушли, бро!",
    "Списание!",
]

_INCOME_GREETINGS = [
    "Бро, пополнение!",
    "Деньги пришли!",
    "Йо, на карту упало!",
    "Зачисление, бро!",
]

_BIG_EXPENSE_GREETINGS = [
    "Бро, серьёзная трата!",
    "Крупное списание!",
    "Ого, бро, солидная сумма ушла!",
]

_BIG_INCOME_GREETINGS = [
    "Бро, серьёзное пополнение!",
    "Крупное зачисление!",
    "Йо, бро, хорошая сумма пришла!",
]


class MonobankMonitor:
    """Monitors Monobank transactions and notifies on new ones.

    Runs as a scheduled job via APScheduler.
    Tracks last seen transaction time to avoid duplicates.
    State is persisted to disk.
    """

    def __init__(
        self,
        service: MonobankService,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        user_id: str = "",
    ) -> None:
        self._mono = service
        self._notify = notify
        self._user_id = user_id
        self._last_tx_time: int = 0
        self._initialized = False
        self._consecutive_errors = 0
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._last_tx_time = data.get("last_tx_time", 0)
                self._initialized = self._last_tx_time > 0
                if self._initialized:
                    logger.info(
                        "Monobank monitor state loaded: last tx at %d",
                        self._last_tx_time,
                    )
        except Exception as e:
            logger.warning("Failed to load monobank monitor state: %s", e)

    def _save_state(self) -> None:
        """Persist current state to disk."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_tx_time": self._last_tx_time,
                "updated_at": int(time.time()),
            }
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save monobank monitor state: %s", e)

    def _format_notification(self, tx: dict[str, Any]) -> str:
        """Build bro-style notification for a transaction."""
        amount = tx.get("amount", 0)
        currency_code = tx.get("currencyCode", 980)
        description = tx.get("description", "—")
        mcc = tx.get("mcc", 0)
        cashback = tx.get("cashbackAmount", 0)
        balance = tx.get("balance", 0)
        dt = datetime.fromtimestamp(tx.get("time", 0), tz=timezone.utc)

        abs_amount = abs(amount) / 100
        is_expense = amount < 0
        is_big = abs_amount >= 1000  # 1000+ UAH = big transaction

        # Pick greeting
        if is_expense:
            greeting = random.choice(
                _BIG_EXPENSE_GREETINGS if is_big else _EXPENSE_GREETINGS
            )
        else:
            greeting = random.choice(
                _BIG_INCOME_GREETINGS if is_big else _INCOME_GREETINGS
            )

        amount_str = _format_amount(amount, currency_code)
        balance_str = _format_balance(balance, currency_code)
        category = _get_mcc_category(mcc)
        date_str = dt.strftime("%d.%m %H:%M")

        lines = [greeting, ""]
        lines.append(f"Сумма: {amount_str}")
        lines.append(f"Описание: {description}")
        if category:
            lines.append(f"Категория: {category}")
        if cashback > 0:
            cb_str = _format_balance(cashback, currency_code)
            lines.append(f"Кешбек: {cb_str}")
        lines.append(f"Баланс: {balance_str}")
        lines.append(f"Время: {date_str}")

        return "\n".join(lines)

    async def check(self) -> None:
        """Check for new transactions and notify."""
        if not self._mono.available:
            return

        try:
            txns = await self._mono.get_statement(account_id="0", days=1)
        except Exception as e:
            self._consecutive_errors += 1
            logger.warning("Monobank monitor check failed: %s", e)
            if self._consecutive_errors >= 5:
                logger.error(
                    "Monobank unreachable for %d consecutive checks",
                    self._consecutive_errors,
                )
            return

        self._consecutive_errors = 0

        if not txns:
            if not self._initialized:
                self._initialized = True
                self._last_tx_time = int(time.time())
                self._save_state()
                logger.info("Monobank monitor initialized (no transactions)")
            return

        # Sort by time ascending
        txns.sort(key=lambda t: t.get("time", 0))

        # First run — just record baseline
        if not self._initialized:
            self._last_tx_time = txns[-1].get("time", 0)
            self._initialized = True
            self._save_state()
            logger.info(
                "Monobank monitor initialized: %d existing transactions, last at %d",
                len(txns),
                self._last_tx_time,
            )
            return

        # Find new transactions (after last seen)
        new_txns = [
            tx for tx in txns
            if tx.get("time", 0) > self._last_tx_time
        ]

        if not new_txns:
            return

        # Update last seen
        self._last_tx_time = new_txns[-1].get("time", 0)
        self._save_state()

        # Notify about each new transaction
        for tx in new_txns:
            text = self._format_notification(tx)
            if self._user_id:
                try:
                    await self._notify(self._user_id, text)
                except Exception as e:
                    logger.error("Failed to send monobank notification: %s", e)

        logger.info(
            "Monobank: %d new transaction(s) notified",
            len(new_txns),
        )

    def get_status(self) -> dict[str, Any]:
        """Return current monitor status."""
        return {
            "last_tx_time": self._last_tx_time,
            "initialized": self._initialized,
            "consecutive_errors": self._consecutive_errors,
        }
