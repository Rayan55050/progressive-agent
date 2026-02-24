"""
Morning Briefing Monitor — daily digest at configured hour.

Gathers data from multiple sources and sends a compact digest:
- Weather (Open-Meteo)
- Crypto (BTC price + Fear & Greed)
- Exchange rates (PrivatBank + NBU)
- Email (unread count)
- Subscriptions (upcoming renewals)
- Scheduled tasks

Calls APIs directly — no LLM tokens consumed.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Callable, Coroutine

import aiohttp

logger = logging.getLogger(__name__)

NotifyCallback = Callable[[str, str], Coroutine[Any, Any, None]]

# Open-Meteo geocoding + weather (free, no key)
_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes → emoji + description
_WMO: dict[int, str] = {
    0: "☀️ Ясно", 1: "🌤 Преим. ясно", 2: "⛅ Перем. облачность",
    3: "☁️ Пасмурно", 45: "🌫 Туман", 48: "🌫 Изморозь",
    51: "🌦 Лёгкая морось", 53: "🌧 Морось", 55: "🌧 Сильная морось",
    61: "🌧 Небольшой дождь", 63: "🌧 Дождь", 65: "🌧 Ливень",
    71: "🌨 Небольшой снег", 73: "🌨 Снег", 75: "❄️ Сильный снег",
    80: "🌧 Ливень", 95: "⛈ Гроза",
}

_TIMEOUT = aiohttp.ClientTimeout(total=10)


class MorningBriefingMonitor:
    """Sends a morning digest combining weather, crypto, rates, email, subs.

    Usage:
        monitor = MorningBriefingMonitor(
            notify=send_to_telegram,
            user_id="YOUR_TELEGRAM_ID",
            city="Your City",
        )
        # Register with scheduler:
        scheduler.add_job(monitor.send_briefing, trigger="cron", hour=8, minute=0)
    """

    def __init__(
        self,
        notify: NotifyCallback,
        user_id: str,
        city: str = "",
        crypto_monitor: Any | None = None,
        gmail_service: Any | None = None,
        sub_monitor: Any | None = None,
        scheduler_service: Any | None = None,
    ) -> None:
        self._notify = notify
        self._user_id = user_id
        self._city = city
        self._crypto = crypto_monitor
        self._gmail = gmail_service
        self._subs = sub_monitor
        self._scheduler = scheduler_service

    async def send_briefing(self) -> None:
        """Compose and send the morning briefing."""
        logger.info("Morning briefing starting...")
        sections: list[str] = []

        # Header
        from datetime import datetime
        now = datetime.now()
        weekdays_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        day_name = weekdays_ru[now.weekday()]
        sections.append(f"☀️ **Доброе утро!**\n📅 {day_name}, {now.strftime('%d.%m.%Y')}\n")

        # Weather
        weather = await self._fetch_weather()
        if weather:
            sections.append(weather)

        # Crypto
        crypto = await self._fetch_crypto()
        if crypto:
            sections.append(crypto)

        # Exchange rates
        rates = await self._fetch_rates()
        if rates:
            sections.append(rates)

        # Email
        email_info = await self._fetch_email()
        if email_info:
            sections.append(email_info)

        # Subscriptions
        sub_info = self._fetch_subscriptions()
        if sub_info:
            sections.append(sub_info)

        # Scheduled tasks
        task_info = self._fetch_tasks()
        if task_info:
            sections.append(task_info)

        if len(sections) <= 1:
            # Only header, nothing else worked
            sections.append("Все сервисы молчат, но ты проснулся — уже победа! 💪")

        briefing = "\n---\n".join(sections)

        # Truncate for Telegram
        if len(briefing) > 4000:
            briefing = briefing[:3950] + "\n\n... (обрезано)"

        try:
            await self._notify(self._user_id, briefing)
            logger.info("Morning briefing sent (%d chars)", len(briefing))
        except Exception as e:
            logger.error("Morning briefing send failed: %s", e)

    async def _fetch_weather(self) -> str | None:
        """Fetch weather from Open-Meteo."""
        try:
            async with aiohttp.ClientSession() as session:
                # Geocode
                async with session.get(
                    _GEO_URL,
                    params={"name": self._city, "count": "1", "language": "ru"},
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status != 200:
                        return None
                    geo = await resp.json()

                results = geo.get("results")
                if not results:
                    return None

                loc = results[0]
                lat, lon = loc["latitude"], loc["longitude"]
                city_name = loc.get("name", self._city)

                # Weather
                params = {
                    "latitude": str(lat),
                    "longitude": str(lon),
                    "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "timezone": "auto",
                    "forecast_days": "2",
                }
                async with session.get(_WEATHER_URL, params=params, timeout=_TIMEOUT) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            current = data["current"]
            daily = data.get("daily", {})

            temp = current["temperature_2m"]
            feels = current["apparent_temperature"]
            code = current["weather_code"]
            wind = current["wind_speed_10m"]
            desc = _WMO.get(code, f"Код {code}")

            line = f"🌡 **{city_name}**: {temp}°C (ощущается {feels}°C), {desc}, ветер {wind} км/ч"

            # Today's forecast
            maxes = daily.get("temperature_2m_max", [])
            mins = daily.get("temperature_2m_min", [])
            precip = daily.get("precipitation_probability_max", [])

            if maxes and mins:
                line += f"\n   Сегодня: {mins[0]}..{maxes[0]}°C"
                if precip and precip[0] and precip[0] > 30:
                    line += f" ☔ Вероятность осадков: {precip[0]}%"

            return line

        except Exception as e:
            logger.warning("Morning briefing weather failed: %s", e)
            return None

    async def _fetch_crypto(self) -> str | None:
        """Fetch BTC price + Fear & Greed."""
        try:
            parts: list[str] = []

            if self._crypto:
                status = await self._crypto.get_full_status()
                price = status.get("last_price")
                if price:
                    parts.append(f"₿ **BTC**: ${price:,.0f}")
                fg_val = status.get("fear_greed_value")
                fg_label = status.get("fear_greed_label")
                if fg_val is not None:
                    emoji = "😱" if fg_val < 25 else "😨" if fg_val < 40 else "😐" if fg_val < 60 else "😏" if fg_val < 75 else "🤑"
                    parts.append(f"Fear & Greed: {fg_val}/100 ({fg_label}) {emoji}")
            else:
                # Fetch directly if no crypto monitor
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://api.coingecko.com/api/v3/simple/price",
                        params={"ids": "bitcoin", "vs_currencies": "usd", "include_24hr_change": "true"},
                        timeout=_TIMEOUT,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            btc = data.get("bitcoin", {})
                            price = btc.get("usd")
                            change = btc.get("usd_24h_change")
                            if price:
                                sign = "+" if (change or 0) >= 0 else ""
                                chg = f" ({sign}{change:.1f}%)" if change else ""
                                parts.append(f"₿ **BTC**: ${price:,.0f}{chg}")

                    # Fear & Greed
                    async with session.get(
                        "https://api.alternative.me/fng/",
                        timeout=_TIMEOUT,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            items = data.get("data", [])
                            if items:
                                val = int(items[0]["value"])
                                cls = items[0]["value_classification"]
                                emoji = "😱" if val < 25 else "😨" if val < 40 else "😐" if val < 60 else "😏" if val < 75 else "🤑"
                                parts.append(f"Fear & Greed: {val}/100 ({cls}) {emoji}")

            return " | ".join(parts) if parts else None

        except Exception as e:
            logger.warning("Morning briefing crypto failed: %s", e)
            return None

    async def _fetch_rates(self) -> str | None:
        """Fetch PrivatBank + NBU exchange rates."""
        try:
            parts: list[str] = ["💱 **Курс UAH**:"]

            async with aiohttp.ClientSession() as session:
                # PrivatBank
                try:
                    async with session.get(
                        "https://api.privatbank.ua/p24api/pubinfo?exchange&coursid=5",
                        timeout=_TIMEOUT,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for item in data:
                                if item.get("ccy") == "USD":
                                    parts.append(f"Приват USD: {item['buy']}/{item['sale']}")
                                elif item.get("ccy") == "EUR":
                                    parts.append(f"EUR: {item['buy']}/{item['sale']}")
                except Exception:
                    pass

                # NBU
                try:
                    async with session.get(
                        "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json&valcode=USD",
                        timeout=_TIMEOUT,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data:
                                rate = data[0].get("rate")
                                if rate:
                                    parts.append(f"НБУ: {rate:.4f}")
                except Exception:
                    pass

            return " | ".join(parts) if len(parts) > 1 else None

        except Exception as e:
            logger.warning("Morning briefing rates failed: %s", e)
            return None

    async def _fetch_email(self) -> str | None:
        """Check unread email count."""
        if not self._gmail or not self._gmail.available:
            return None

        try:
            unread = await self._gmail.get_unread_count()
            if unread and unread > 0:
                return f"📧 Непрочитанных писем: **{unread}**"
            return "📧 Почта: всё прочитано ✅"
        except Exception as e:
            logger.warning("Morning briefing email failed: %s", e)
            return None

    def _fetch_subscriptions(self) -> str | None:
        """Check upcoming subscription renewals (next 7 days)."""
        if not self._subs:
            return None

        try:
            all_subs = self._subs.list_all()
            if not all_subs:
                return None

            today = date.today()
            upcoming: list[str] = []

            for sub in all_subs:
                try:
                    renewal = date.fromisoformat(sub["next_renewal"])
                    days_left = (renewal - today).days
                    if 0 <= days_left <= 7:
                        price = sub.get("price", "?")
                        currency = sub.get("currency", "")
                        upcoming.append(
                            f"  • {sub['name']}: {price} {currency} через {days_left} дн. ({renewal.strftime('%d.%m')})"
                        )
                except (ValueError, KeyError):
                    continue

            if upcoming:
                return "💳 **Подписки (7 дней)**:\n" + "\n".join(upcoming)
            return None

        except Exception as e:
            logger.warning("Morning briefing subscriptions failed: %s", e)
            return None

    def _fetch_tasks(self) -> str | None:
        """Check today's scheduled tasks."""
        if not self._scheduler:
            return None

        try:
            tasks = self._scheduler.list_tasks()
            if not tasks:
                return None

            today_tasks = []
            today = date.today()

            for task in tasks:
                # Check if task is for today
                next_run = task.get("next_run", "")
                if next_run and next_run.startswith(today.isoformat()):
                    today_tasks.append(f"  • {task.get('name', '?')} в {next_run[11:16]}")

            if today_tasks:
                return f"📋 **Задачи на сегодня** ({len(today_tasks)}):\n" + "\n".join(today_tasks)
            return None

        except Exception as e:
            logger.warning("Morning briefing tasks failed: %s", e)
            return None
