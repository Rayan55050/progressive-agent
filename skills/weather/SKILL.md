---
name: weather
description: "Погода: текущие условия и прогноз на 3 дня"
tools:
  - weather
trigger_keywords:
  - погода
  - weather
  - температура
  - дождь
  - снег
  - ветер
  - прогноз
  - forecast
  - мороз
  - жара
  - зонт
---

# Weather Skill

## Tool: `weather`
Returns current weather and 3-day forecast for any city.

### Parameters
- `city` (optional) — city name. Default: from config.

### Rules
1. If user asks about weather without specifying a city, use the default city
2. If user mentions a specific city, pass it to the tool
3. Present the result naturally, don't just dump raw data
4. If user asks "нужен ли зонт?" — check precipitation and answer directly
5. Always respond in the user's language
