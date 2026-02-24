"""
Crypto monitor — background BTC price tracker.

Uses CoinGecko API (free, no auth needed) to track BTC price.
Pushes bro-style notification to Telegram when price moves $500+.

State (last known price) persisted to disk so bot restarts
don't cause missed or duplicate notifications.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

import aiohttp

logger = logging.getLogger(__name__)

# State file — survives restarts
STATE_FILE = Path("data/crypto_monitor_state.json")

# CoinGecko free API (no auth, ~30 req/min limit)
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_PARAMS = {
    "ids": "bitcoin",
    "vs_currencies": "usd",
    "include_24hr_change": "true",
    "include_24hr_vol": "true",
    "include_last_updated_at": "true",
}

# Fear & Greed Index (alternative.me, free, no auth)
FEAR_GREED_URL = "https://api.alternative.me/fng/"

# Notification templates
_PUMP_GREETINGS = [
    "Бро, биток полетел вверх!",
    "Йо, BTC растёт!",
    "Биток пампит!",
    "Зелёная свеча, бро!",
    "BTC на луну!",
]

_DUMP_GREETINGS = [
    "Бро, биток сыпется!",
    "Йо, BTC падает!",
    "Красная свеча, бро!",
    "Биток дампит!",
    "Бро, BTC вниз пошёл!",
]

_MEGA_PUMP = [
    "БИТОК РВЁТ КРЫШУ! 🚀",
    "BTC АБСОЛЮТНО БЕЗУМНЫЙ РОСТ! 🔥",
    "БРО, ЭТО ПАМП ВЕКА!",
]

_MEGA_DUMP = [
    "БИТОК КРАШИТСЯ! 📉",
    "BTC ПАДАЕТ ЖЁСТКО!",
    "БРО, КРАСНЫЙ ДЕНЬ!",
]


class CryptoMonitor:
    """Monitors BTC price via CoinGecko API.

    Runs as a scheduled job via APScheduler (every 1-2 min).
    When BTC price moves $500+ from last notification,
    pushes a bro-style notification to Telegram.

    State is persisted to disk so bot restarts don't lose track.
    """

    def __init__(
        self,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        user_id: str = "",
        threshold_usd: float = 500.0,
    ) -> None:
        self._notify = notify
        self._user_id = user_id
        self._threshold = threshold_usd
        self._last_notified_price: float | None = None
        self._last_price: float | None = None
        self._initialized = False
        self._consecutive_errors = 0
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._last_notified_price = data.get("last_notified_price")
                self._last_price = data.get("last_price")
                self._initialized = self._last_notified_price is not None
                if self._initialized:
                    logger.info(
                        "Crypto monitor state loaded: last notified at $%.0f",
                        self._last_notified_price,
                    )
        except Exception as e:
            logger.warning("Failed to load crypto monitor state: %s", e)

    def _save_state(self) -> None:
        """Persist current state to disk."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_notified_price": self._last_notified_price,
                "last_price": self._last_price,
                "updated_at": int(time.time()),
            }
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save crypto monitor state: %s", e)

    async def _fetch_price(self) -> dict[str, Any] | None:
        """Fetch current BTC price from CoinGecko."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    COINGECKO_URL,
                    params=COINGECKO_PARAMS,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        btc = data.get("bitcoin", {})
                        if "usd" in btc:
                            self._consecutive_errors = 0
                            return btc
                    elif resp.status == 429:
                        logger.warning("CoinGecko rate limited (429)")
                    else:
                        logger.warning("CoinGecko HTTP %d", resp.status)
        except aiohttp.ClientError as e:
            logger.warning("CoinGecko connection error: %s", e)
        except Exception as e:
            logger.error("CoinGecko fetch failed: %s", e)

        self._consecutive_errors += 1
        if self._consecutive_errors >= 10:
            logger.error(
                "CoinGecko unreachable for %d consecutive checks",
                self._consecutive_errors,
            )
        return None

    async def fetch_fear_greed(self) -> dict[str, Any] | None:
        """Fetch Crypto Fear & Greed Index (0-100).

        Returns dict with 'value', 'classification', 'timestamp' or None.
        Public method — also used by Morning Briefing monitor.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    FEAR_GREED_URL,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Fear & Greed API HTTP %d", resp.status)
                        return None
                    data = await resp.json()
                    items = data.get("data", [])
                    if items:
                        return {
                            "value": int(items[0]["value"]),
                            "classification": items[0]["value_classification"],
                            "timestamp": items[0].get("timestamp"),
                        }
        except Exception as e:
            logger.warning("Fear & Greed fetch failed: %s", e)
        return None

    def _format_notification(
        self,
        price: float,
        change_24h: float | None,
        move: float,
        fear_greed: dict[str, Any] | None = None,
    ) -> str:
        """Build bro-style notification for BTC price movement."""
        abs_move = abs(move)
        is_pump = move > 0

        # Pick greeting based on size of move
        if abs_move >= 2000:
            greeting = random.choice(_MEGA_PUMP if is_pump else _MEGA_DUMP)
        else:
            greeting = random.choice(_PUMP_GREETINGS if is_pump else _DUMP_GREETINGS)

        direction = "+" if is_pump else ""
        lines = [
            greeting,
            "",
            f"₿ BTC: ${price:,.0f} ({direction}{move:,.0f}$)",
        ]

        if change_24h is not None:
            sign = "+" if change_24h > 0 else ""
            lines.append(f"24ч: {sign}{change_24h:.1f}%")

        if fear_greed:
            val = fear_greed["value"]
            cls = fear_greed["classification"]
            emoji = "😱" if val < 25 else "😨" if val < 40 else "😐" if val < 60 else "😏" if val < 75 else "🤑"
            lines.append(f"Fear & Greed: {val}/100 ({cls}) {emoji}")

        lines.append("")
        lines.append(f"Движение: {direction}${abs_move:,.0f} с последнего уведомления")

        return "\n".join(lines)

    async def check(self) -> None:
        """Check BTC price and notify if significant movement detected."""
        btc = await self._fetch_price()
        if btc is None:
            return

        price = btc["usd"]
        change_24h = btc.get("usd_24h_change")
        self._last_price = price

        # First run — just record baseline, don't spam
        if not self._initialized:
            self._last_notified_price = price
            self._initialized = True
            self._save_state()
            logger.info("Crypto monitor initialized: BTC = $%.0f", price)
            return

        # Check if price moved enough from last notification
        move = price - self._last_notified_price  # type: ignore[operator]
        if abs(move) >= self._threshold:
            # Fetch Fear & Greed Index for the notification
            fear_greed = await self.fetch_fear_greed()
            text = self._format_notification(price, change_24h, move, fear_greed)

            if self._user_id:
                await self._notify(self._user_id, text)
                logger.info(
                    "Crypto alert sent: BTC $%.0f (move: %+.0f)",
                    price,
                    move,
                )

            # Update baseline to current price
            self._last_notified_price = price
            self._save_state()
        else:
            # Save last_price even without notification (for get_status)
            self._save_state()

    def get_status(self) -> dict[str, Any]:
        """Return current monitor status (for crypto skill queries)."""
        return {
            "last_price": self._last_price,
            "last_notified_price": self._last_notified_price,
            "threshold_usd": self._threshold,
            "initialized": self._initialized,
            "consecutive_errors": self._consecutive_errors,
        }

    async def get_full_status(self) -> dict[str, Any]:
        """Return status including Fear & Greed (async, for briefings)."""
        status = self.get_status()
        fg = await self.fetch_fear_greed()
        if fg:
            status["fear_greed_value"] = fg["value"]
            status["fear_greed_label"] = fg["classification"]
        return status
