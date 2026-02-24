"""
Weather Tool — current weather and forecast.

Primary: Open-Meteo API (fast, reliable, no API key).
Fallback: wttr.in (slower but more detailed).
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# WMO weather codes → descriptions
_WMO_CODES: dict[int, str] = {
    0: "Ясно", 1: "Преимущественно ясно", 2: "Переменная облачность",
    3: "Пасмурно", 45: "Туман", 48: "Изморозь",
    51: "Лёгкая морось", 53: "Морось", 55: "Сильная морось",
    61: "Небольшой дождь", 63: "Дождь", 65: "Сильный дождь",
    66: "Ледяной дождь", 67: "Сильный ледяной дождь",
    71: "Небольшой снег", 73: "Снег", 75: "Сильный снег",
    77: "Снежная крупа", 80: "Ливень", 81: "Сильный ливень",
    82: "Очень сильный ливень", 85: "Снегопад", 86: "Сильный снегопад",
    95: "Гроза", 96: "Гроза с градом", 99: "Сильная гроза с градом",
}


class WeatherTool:
    """Get current weather and short forecast."""

    def __init__(self, default_city: str = "") -> None:
        self._default_city = default_city

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="weather",
            description=(
                "Get current weather and 3-day forecast for a city. "
                "Free, no API key. Supports any city worldwide."
            ),
            parameters=[
                ToolParameter(
                    name="city",
                    type="string",
                    description="City name (e.g. 'London', 'New York', 'Tokyo'). Default: from config.",
                    required=False,
                ),
            ],
        )

    async def execute(self, city: str | None = None, **kwargs: Any) -> ToolResult:
        city = city or self._default_city

        # Try Open-Meteo first (fast, reliable)
        result = await self._open_meteo(city)
        if result.success:
            return result

        # Fallback to wttr.in
        logger.warning("Open-Meteo failed, trying wttr.in fallback")
        return await self._wttr_in(city)

    async def _open_meteo(self, city: str) -> ToolResult:
        """Get weather via Open-Meteo API (geocoding + forecast)."""
        try:
            async with aiohttp.ClientSession() as session:
                # Step 1: Geocode city name → lat/lon
                geo_url = (
                    f"https://geocoding-api.open-meteo.com/v1/search"
                    f"?name={city}&count=1&language=ru"
                )
                async with session.get(
                    geo_url, timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status != 200:
                        return ToolResult(success=False, error=f"Geocoding HTTP {resp.status}")
                    geo = await resp.json()

                results = geo.get("results")
                if not results:
                    return ToolResult(success=False, error=f"City '{city}' not found")

                loc = results[0]
                lat, lon = loc["latitude"], loc["longitude"]
                city_name = loc.get("name", city)
                country = loc.get("country", "")

                # Step 2: Get weather data
                weather_url = (
                    f"https://api.open-meteo.com/v1/forecast"
                    f"?latitude={lat}&longitude={lon}"
                    f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
                    f"weather_code,wind_speed_10m,wind_direction_10m,surface_pressure"
                    f"&daily=weather_code,temperature_2m_max,temperature_2m_min"
                    f"&timezone=auto&forecast_days=3"
                )
                async with session.get(
                    weather_url, timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status != 200:
                        return ToolResult(success=False, error=f"Weather HTTP {resp.status}")
                    data = await resp.json()

            current = data["current"]
            daily = data["daily"]

            temp = current["temperature_2m"]
            feels = current["apparent_temperature"]
            humidity = current["relative_humidity_2m"]
            wind = current["wind_speed_10m"]
            wind_dir = self._wind_direction(current["wind_direction_10m"])
            pressure = round(current["surface_pressure"])
            code = current["weather_code"]
            desc = _WMO_CODES.get(code, f"Код {code}")

            lines = [
                f"🌍 {city_name}, {country}",
                f"🌡 {temp}°C (ощущается как {feels}°C)",
                f"☁ {desc}",
                f"💧 Влажность: {humidity}%",
                f"💨 Ветер: {wind} км/ч {wind_dir}",
                f"📊 Давление: {pressure} гПа",
            ]

            # 3-day forecast
            dates = daily.get("time", [])
            maxes = daily.get("temperature_2m_max", [])
            mins = daily.get("temperature_2m_min", [])
            codes = daily.get("weather_code", [])

            if dates:
                lines.append("\n📅 Прогноз:")
                for i, date in enumerate(dates[:3]):
                    day_desc = _WMO_CODES.get(codes[i], "")
                    lines.append(f"  {date}: {mins[i]}..{maxes[i]}°C, {day_desc}")

            return ToolResult(success=True, data="\n".join(lines))

        except Exception as e:
            return ToolResult(success=False, error=f"Open-Meteo error: {e}")

    async def _wttr_in(self, city: str) -> ToolResult:
        """Fallback: get weather via wttr.in."""
        url = f"https://wttr.in/{city}?format=j1&lang=ru"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={"User-Agent": "progressive-agent/1.0"},
                ) as resp:
                    if resp.status != 200:
                        return ToolResult(success=False, error=f"wttr.in HTTP {resp.status}")
                    data = await resp.json()
        except Exception as e:
            return ToolResult(success=False, error=f"wttr.in failed: {e}")

        try:
            current = data["current_condition"][0]
            area = data.get("nearest_area", [{}])[0]
            city_name = area.get("areaName", [{}])[0].get("value", city)
            country = area.get("country", [{}])[0].get("value", "")

            temp_c = current["temp_C"]
            feels_like = current["FeelsLikeC"]
            humidity = current["humidity"]
            wind_kmph = current["windspeedKmph"]
            wind_dir = current.get("winddir16Point", "")
            pressure = current.get("pressure", "")

            lang_ru = current.get("lang_ru", [])
            desc = lang_ru[0]["value"] if lang_ru else current["weatherDesc"][0]["value"]

            lines = [
                f"🌍 {city_name}, {country}",
                f"🌡 {temp_c}°C (ощущается как {feels_like}°C)",
                f"☁ {desc}",
                f"💧 Влажность: {humidity}%",
                f"💨 Ветер: {wind_kmph} км/ч {wind_dir}",
                f"📊 Давление: {pressure} мбар",
            ]

            weather_list = data.get("weather", [])
            if weather_list:
                lines.append("\n📅 Прогноз:")
                for day in weather_list[:3]:
                    date = day["date"]
                    min_t = day["mintempC"]
                    max_t = day["maxtempC"]
                    hourly = day.get("hourly", [])
                    day_desc = ""
                    if len(hourly) > 4:
                        day_lang_ru = hourly[4].get("lang_ru", [])
                        day_desc = (
                            day_lang_ru[0]["value"]
                            if day_lang_ru
                            else hourly[4].get("weatherDesc", [{}])[0].get("value", "")
                        )
                    lines.append(f"  {date}: {min_t}..{max_t}°C, {day_desc}")

            return ToolResult(success=True, data="\n".join(lines))

        except (KeyError, IndexError) as e:
            return ToolResult(success=False, error=f"Parse error: {e}")

    @staticmethod
    def _wind_direction(degrees: float) -> str:
        """Convert wind degrees to compass direction."""
        dirs = ["С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ",
                "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ"]
        idx = round(degrees / 22.5) % 16
        return dirs[idx]
