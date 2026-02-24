"""
Exchange rates tool — PrivatBank, NBU, and open exchange rates.

All FREE, no API keys needed.
- PrivatBank: cash/non-cash USD/EUR buy/sell rates
- NBU (National Bank of Ukraine): official rates for all currencies
- Open Exchange Rates: fallback global rates
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# PrivatBank API (no auth, free)
PRIVAT_URL = "https://api.privatbank.ua/p24api/pubinfo?exchange&coursid=5"
# NBU official rates (no auth, free)
NBU_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json"
# Open Exchange Rates (no auth for base rates)
OPEN_ER_URL = "https://open.er-api.com/v6/latest/USD"

_TIMEOUT = aiohttp.ClientTimeout(total=10)


class ExchangeRatesTool:
    """Get UAH exchange rates from Ukrainian banks and NBU."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="exchange_rates",
            description=(
                "Get current UAH exchange rates. "
                "Sources: PrivatBank (cash rates), NBU (official rate), open exchange rates. "
                "No API key needed. Supports USD, EUR, and other currencies. "
                "Actions: 'all' — full overview of USD/EUR rates from all sources; "
                "'nbu' — official NBU rate for specific currency; "
                "'convert' — convert amount between currencies."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'all' (overview), 'nbu' (official rate), 'convert'",
                    required=False,
                    enum=["all", "nbu", "convert"],
                ),
                ToolParameter(
                    name="currency",
                    type="string",
                    description="Currency code for 'nbu' action (e.g. 'USD', 'EUR', 'PLN', 'GBP')",
                    required=False,
                ),
                ToolParameter(
                    name="amount",
                    type="string",
                    description="Amount to convert (for 'convert' action, e.g. '100')",
                    required=False,
                ),
                ToolParameter(
                    name="from_currency",
                    type="string",
                    description="Source currency for conversion (e.g. 'USD')",
                    required=False,
                ),
                ToolParameter(
                    name="to_currency",
                    type="string",
                    description="Target currency for conversion (e.g. 'UAH')",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "all").strip().lower()

        try:
            if action == "all":
                return await self._all_rates()
            elif action == "nbu":
                currency = kwargs.get("currency", "USD").strip().upper()
                return await self._nbu_rate(currency)
            elif action == "convert":
                return await self._convert(kwargs)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error("Exchange rates error: %s", e)
            return ToolResult(success=False, error=f"Exchange rates error: {e}")

    async def _all_rates(self) -> ToolResult:
        """Fetch USD/EUR rates from PrivatBank + NBU."""
        lines: list[str] = ["💱 **Курсы валют (UAH)**\n"]

        # PrivatBank
        try:
            privat = await self._fetch_privat()
            if privat:
                lines.append("🏦 **ПриватБанк** (наличный курс):")
                for ccy, buy, sell in privat:
                    lines.append(f"  {ccy}: покупка {buy} / продажа {sell}")
                lines.append("")
        except Exception as e:
            lines.append(f"ПриватБанк: ошибка ({e})\n")

        # NBU
        try:
            nbu_usd = await self._fetch_nbu_single("USD")
            nbu_eur = await self._fetch_nbu_single("EUR")
            lines.append("🏛 **НБУ** (официальный курс):")
            if nbu_usd:
                lines.append(f"  USD: {nbu_usd:.4f}")
            if nbu_eur:
                lines.append(f"  EUR: {nbu_eur:.4f}")
            lines.append("")
        except Exception as e:
            lines.append(f"НБУ: ошибка ({e})\n")

        return ToolResult(success=True, data="\n".join(lines))

    async def _nbu_rate(self, currency: str) -> ToolResult:
        """Get NBU official rate for a specific currency."""
        rate = await self._fetch_nbu_single(currency)
        if rate is None:
            return ToolResult(
                success=False,
                error=f"Currency '{currency}' not found in NBU rates",
            )
        return ToolResult(
            success=True,
            data=f"🏛 НБУ: 1 {currency} = {rate:.4f} UAH",
        )

    async def _convert(self, kwargs: dict) -> ToolResult:
        """Convert between currencies using NBU rates."""
        amount_str = kwargs.get("amount", "").strip()
        from_ccy = kwargs.get("from_currency", "USD").strip().upper()
        to_ccy = kwargs.get("to_currency", "UAH").strip().upper()

        if not amount_str:
            return ToolResult(success=False, error="Amount is required for convert")

        try:
            amount = float(amount_str.replace(",", "."))
        except ValueError:
            return ToolResult(success=False, error=f"Invalid amount: {amount_str}")

        # Get rates relative to UAH
        from_rate = 1.0 if from_ccy == "UAH" else await self._fetch_nbu_single(from_ccy)
        to_rate = 1.0 if to_ccy == "UAH" else await self._fetch_nbu_single(to_ccy)

        if from_rate is None:
            return ToolResult(success=False, error=f"Unknown currency: {from_ccy}")
        if to_rate is None:
            return ToolResult(success=False, error=f"Unknown currency: {to_ccy}")

        # Convert via UAH
        uah_amount = amount * from_rate
        result = uah_amount / to_rate

        return ToolResult(
            success=True,
            data=f"💱 {amount:,.2f} {from_ccy} = **{result:,.2f} {to_ccy}**\n(Курс НБУ: {from_ccy}={from_rate:.4f}, {to_ccy}={to_rate:.4f})",
        )

    async def _fetch_privat(self) -> list[tuple[str, str, str]]:
        """Fetch PrivatBank cash exchange rates."""
        async with aiohttp.ClientSession() as session:
            async with session.get(PRIVAT_URL, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise ValueError(f"PrivatBank HTTP {resp.status}")
                data = await resp.json()

        results: list[tuple[str, str, str]] = []
        for item in data:
            ccy = item.get("ccy", "")
            if ccy in ("USD", "EUR"):
                buy = item.get("buy", "?")
                sale = item.get("sale", "?")
                results.append((ccy, buy, sale))
        return results

    async def _fetch_nbu_single(self, currency: str) -> float | None:
        """Fetch a single currency rate from NBU."""
        url = f"{NBU_URL}&valcode={currency}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if data and isinstance(data, list):
            return data[0].get("rate")
        return None
