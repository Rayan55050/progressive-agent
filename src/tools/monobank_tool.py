"""
Monobank API tools for Progressive Agent.

Provides three LLM-callable tools:
- monobank_balance: get account balances
- monobank_transactions: get recent transactions
- monobank_rates: get currency exchange rates

API docs: https://api.monobank.ua/docs/
Rate limit: 1 request per 60 seconds for personal endpoints.
Public endpoints (rates) have no auth requirement.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Monobank API base URL
MONO_API = "https://api.monobank.ua"

# Currency codes (ISO 4217 numeric)
CURRENCY_MAP = {
    980: "UAH",
    840: "USD",
    978: "EUR",
    826: "GBP",
    985: "PLN",
    203: "CZK",
    756: "CHF",
    392: "JPY",
    156: "CNY",
    949: "TRY",
    36: "AUD",
    124: "CAD",
}

# Account type mapping
ACCOUNT_TYPES = {
    "black": "Чёрная карта",
    "white": "Белая карта",
    "platinum": "Platinum",
    "iron": "Iron",
    "fop": "ФОП",
    "yellow": "Жёлтая карта",
    "eAid": "єПідтримка",
}

# MCC category descriptions (top categories)
MCC_CATEGORIES = {
    (4000, 4999): "Транспорт",
    (5200, 5299): "Стройматериалы",
    (5300, 5399): "Продукты",
    (5400, 5499): "Продукты",
    (5500, 5599): "Авто",
    (5600, 5699): "Одежда",
    (5700, 5799): "Мебель/дом",
    (5800, 5899): "Рестораны/кафе",
    (5900, 5999): "Аптеки/магазины",
    (6000, 6099): "Финансы",
    (7000, 7099): "Отели",
    (7200, 7299): "Услуги",
    (7800, 7999): "Развлечения",
    (8000, 8099): "Медицина",
    (8200, 8299): "Образование",
}


def _get_mcc_category(mcc: int) -> str:
    """Get human-readable category from MCC code."""
    for (low, high), name in MCC_CATEGORIES.items():
        if low <= mcc <= high:
            return name
    return ""


def _format_amount(amount: int, currency_code: int) -> str:
    """Format amount from kopecks to human-readable string."""
    currency = CURRENCY_MAP.get(currency_code, str(currency_code))
    value = amount / 100
    if value >= 0:
        return f"+{value:,.2f} {currency}"
    return f"{value:,.2f} {currency}"


def _format_balance(amount: int, currency_code: int) -> str:
    """Format balance from kopecks."""
    currency = CURRENCY_MAP.get(currency_code, str(currency_code))
    value = amount / 100
    return f"{value:,.2f} {currency}"


class MonobankService:
    """Shared Monobank API service.

    Handles API calls with rate limiting (1 req/60s for personal endpoints).
    Public endpoints (/bank/currency) have no rate limit.
    """

    def __init__(self, token: str) -> None:
        self._token = token
        self._last_personal_request: float = 0
        self._client_info: dict[str, Any] | None = None
        self._client_info_cached_at: float = 0
        self._rates_cache: list[dict] | None = None
        self._rates_cached_at: float = 0

    @property
    def available(self) -> bool:
        return bool(self._token)

    async def _request(
        self,
        endpoint: str,
        auth: bool = True,
    ) -> dict | list | None:
        """Make API request with rate limiting."""
        if auth:
            # Rate limit: 1 personal request per 60 seconds
            now = time.monotonic()
            elapsed = now - self._last_personal_request
            if elapsed < 60:
                wait = 60 - elapsed
                logger.info("Monobank rate limit: waiting %.0fs", wait)
                await asyncio.sleep(wait)
            self._last_personal_request = time.monotonic()

        headers = {}
        if auth:
            headers["X-Token"] = self._token

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{MONO_API}{endpoint}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        logger.warning("Monobank rate limited (429)")
                        return None
                    else:
                        text = await resp.text()
                        logger.error("Monobank API %d: %s", resp.status, text[:200])
                        return None
        except Exception as e:
            logger.error("Monobank API error: %s", e)
            return None

    async def get_client_info(self) -> dict[str, Any] | None:
        """Get client info (accounts list). Cached for 5 min."""
        now = time.monotonic()
        if self._client_info and (now - self._client_info_cached_at) < 300:
            return self._client_info

        data = await self._request("/personal/client-info")
        if data and isinstance(data, dict):
            self._client_info = data
            self._client_info_cached_at = time.monotonic()
            return data
        return self._client_info  # return stale cache if request failed

    async def get_statement(
        self,
        account_id: str = "0",
        days: int = 3,
    ) -> list[dict[str, Any]]:
        """Get account statement (transactions).

        Args:
            account_id: Account ID or "0" for default (black card).
            days: Number of days to look back (max 31).
        """
        days = min(days, 31)
        now = datetime.now(timezone.utc)
        from_ts = int((now - timedelta(days=days)).timestamp())
        to_ts = int(now.timestamp())

        data = await self._request(f"/personal/statement/{account_id}/{from_ts}/{to_ts}")
        if data and isinstance(data, list):
            return data
        return []

    async def get_rates(self) -> list[dict[str, Any]]:
        """Get currency exchange rates (public, no auth). Cached for 5 min."""
        now = time.monotonic()
        if self._rates_cache and (now - self._rates_cached_at) < 300:
            return self._rates_cache

        data = await self._request("/bank/currency", auth=False)
        if data and isinstance(data, list):
            self._rates_cache = data
            self._rates_cached_at = time.monotonic()
            return data
        return self._rates_cache or []


# ---------------------------------------------------------------------------
# Tool: monobank_balance
# ---------------------------------------------------------------------------


class MonobankBalanceTool:
    """Get Monobank account balances."""

    def __init__(self, service: MonobankService) -> None:
        self._mono = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="monobank_balance",
            description=(
                "Get Monobank account balances. Shows all accounts "
                "(cards) with current balance and credit limit if applicable."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._mono.available:
            return ToolResult(
                success=False,
                error="Monobank не настроен (нет API токена в .env)",
            )

        try:
            info = await self._mono.get_client_info()
            if not info:
                return ToolResult(success=False, error="Не удалось получить данные из Monobank")

            accounts = info.get("accounts", [])
            if not accounts:
                return ToolResult(success=True, data="Нет привязанных счетов")

            name = info.get("name", "")
            lines = []
            if name:
                lines.append(f"Клиент: {name}")
                lines.append("")

            for acc in accounts:
                currency_code = acc.get("currencyCode", 980)
                balance = acc.get("balance", 0)
                credit_limit = acc.get("creditLimit", 0)
                acc_type = acc.get("type", "unknown")
                masked_pan = acc.get("maskedPan", [""])[0] if acc.get("maskedPan") else ""
                iban = acc.get("iban", "")

                type_name = ACCOUNT_TYPES.get(acc_type, acc_type)
                bal_str = _format_balance(balance, currency_code)

                line = f"{type_name}"
                if masked_pan:
                    line += f" ({masked_pan})"
                line += f": {bal_str}"

                if credit_limit > 0:
                    limit_str = _format_balance(credit_limit, currency_code)
                    line += f" (кредитный лимит: {limit_str})"

                lines.append(line)

            return ToolResult(success=True, data="\n".join(lines))
        except Exception as e:
            logger.error("monobank_balance failed: %s", e)
            return ToolResult(success=False, error=f"Monobank error: {e}")


# ---------------------------------------------------------------------------
# Tool: monobank_transactions
# ---------------------------------------------------------------------------


class MonobankTransactionsTool:
    """Get recent Monobank transactions."""

    def __init__(self, service: MonobankService) -> None:
        self._mono = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="monobank_transactions",
            description=(
                "Get recent Monobank transactions for the default account. "
                "Shows amount, description, category, and cashback. "
                "Default: last 3 days. Max: 31 days."
            ),
            parameters=[
                ToolParameter(
                    name="days",
                    type="integer",
                    description="Number of days to look back (1-31, default 3)",
                    required=False,
                    default=3,
                ),
                ToolParameter(
                    name="account",
                    type="string",
                    description="Account ID (default '0' = чёрная карта)",
                    required=False,
                    default="0",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._mono.available:
            return ToolResult(
                success=False,
                error="Monobank не настроен (нет API токена в .env)",
            )

        days = min(int(kwargs.get("days", 3)), 31)
        account = str(kwargs.get("account", "0"))

        try:
            txns = await self._mono.get_statement(account_id=account, days=days)
            if not txns:
                return ToolResult(success=True, data=f"Нет транзакций за последние {days} дн.")

            lines = [f"Транзакции за последние {days} дн. ({len(txns)} шт.):", ""]

            total_expense = 0
            total_income = 0

            for tx in txns:
                amount = tx.get("amount", 0)
                currency_code = tx.get("currencyCode", 980)
                description = tx.get("description", "—")
                mcc = tx.get("mcc", 0)
                cashback = tx.get("cashbackAmount", 0)
                dt = datetime.fromtimestamp(tx.get("time", 0), tz=timezone.utc)
                date_str = dt.strftime("%d.%m %H:%M")

                if amount < 0:
                    total_expense += abs(amount)
                else:
                    total_income += amount

                amount_str = _format_amount(amount, currency_code)
                category = _get_mcc_category(mcc)

                line = f"{date_str}  {amount_str}  {description}"
                if category:
                    line += f"  [{category}]"
                if cashback > 0:
                    cb_str = _format_balance(cashback, currency_code)
                    line += f"  (кешбек: {cb_str})"

                lines.append(line)

            # Summary
            currency = CURRENCY_MAP.get(980, "UAH")
            lines.append("")
            lines.append(
                f"Итого: расходы {total_expense / 100:,.2f} {currency}, "
                f"доходы {total_income / 100:,.2f} {currency}"
            )

            return ToolResult(success=True, data="\n".join(lines))
        except Exception as e:
            logger.error("monobank_transactions failed: %s", e)
            return ToolResult(success=False, error=f"Monobank error: {e}")


# ---------------------------------------------------------------------------
# Tool: monobank_rates
# ---------------------------------------------------------------------------


class MonobankRatesTool:
    """Get Monobank currency exchange rates."""

    def __init__(self, service: MonobankService) -> None:
        self._mono = service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="monobank_rates",
            description=(
                "Get current currency exchange rates from Monobank. "
                "Shows buy/sell rates for major currencies vs UAH. "
                "Public API — no rate limit."
            ),
            parameters=[
                ToolParameter(
                    name="currency",
                    type="string",
                    description="Filter by currency code (USD, EUR). Empty = USD and EUR only.",
                    required=False,
                    default="",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        currency_filter = kwargs.get("currency", "").upper().strip()

        try:
            rates = await self._mono.get_rates()
            if not rates:
                return ToolResult(success=False, error="Не удалось получить курсы")

            # Build reverse currency map: name -> code
            name_to_code = {v: k for k, v in CURRENCY_MAP.items()}

            # Filter: only show rates vs UAH (currencyCodeB = 980)
            uah_rates = [
                r for r in rates
                if r.get("currencyCodeB") == 980
                and r.get("currencyCodeA") in CURRENCY_MAP
            ]

            if currency_filter:
                filter_code = name_to_code.get(currency_filter)
                if filter_code:
                    uah_rates = [
                        r for r in uah_rates
                        if r.get("currencyCodeA") == filter_code
                    ]
            else:
                # Default: only USD and EUR
                default_codes = {840, 978}  # USD, EUR
                uah_rates = [
                    r for r in uah_rates
                    if r.get("currencyCodeA") in default_codes
                ]

            if not uah_rates:
                return ToolResult(success=True, data="Нет курсов для указанной валюты")

            lines = ["Курсы Monobank:", ""]
            for r in uah_rates:
                code_a = r.get("currencyCodeA", 0)
                currency_name = CURRENCY_MAP.get(code_a, str(code_a))
                buy = r.get("rateBuy", 0)
                sell = r.get("rateSell", 0)
                cross = r.get("rateCross", 0)

                if buy and sell:
                    lines.append(f"{currency_name}/UAH: купить {buy:.2f} / продать {sell:.2f}")
                elif cross:
                    lines.append(f"{currency_name}/UAH: {cross:.2f} (кросс-курс)")

            dt = datetime.fromtimestamp(
                uah_rates[0].get("date", 0), tz=timezone.utc
            )
            lines.append("")
            lines.append(f"Обновлено: {dt.strftime('%d.%m.%Y %H:%M')} UTC")

            return ToolResult(success=True, data="\n".join(lines))
        except Exception as e:
            logger.error("monobank_rates failed: %s", e)
            return ToolResult(success=False, error=f"Monobank error: {e}")
