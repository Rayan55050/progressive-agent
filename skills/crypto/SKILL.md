---
name: crypto
description: "Крипта: курсы BTC, анализ, новости, мониторинг цены"
tools:
  - web_search
  - web_extract
  - exchange_rates
trigger_keywords:
  - биткоин
  - bitcoin
  - btc
  - эфир
  - ethereum
  - eth
  - крипта
  - криптовалюта
  - курс крипты
  - crypto
  - токен
  - альткоин
---

# Крипта

Мониторинг BTC + веб-поиск для новостей и анализа.

## CryptoMonitor (фоновый)

Работает автоматически в фоне:
- Проверяет курс BTC через CoinGecko API каждые 2 минуты
- Пушит уведомление при движении $500+
- Состояние сохраняется между перезапусками

Мне НЕ нужно вызывать тулы для текущего курса — монитор сам уведомит.

## Курсы валют (exchange_rates)

Для UAH курсов (доллар/евро к гривне):
- **`exchange_rates`** — ПриватБанк + НБУ, бесплатно, мгновенно
- Используй когда спрашивают про крипту В ГРИВНАХ или про курс доллара в контексте крипты

## Когда использовать web_search

### Новости
- `"crypto news today"`, `"bitcoin news"` — topic: `news`, time_range: `day`
- Источники: CryptoSlate, The Block, CoinDesk

### Анализ
- `"BTC technical analysis"`, `"bitcoin прогноз"` — web_extract для статей
- Владелец трейдит на TradingView, понимает тех. анализ — говори на уровне

### Альткоины
- Для ETH, SOL и других: `"{coin} price today USD"` через web_search

## Формат ответа

Курс:
```
₿ BTC: $XX,XXX (+X.X%)
Ξ ETH: $X,XXX (+X.X%)
```

## NewsRadar (фоновый мониторинг новостей)

Помимо CryptoMonitor (цена BTC), работает NewsRadar:
- Проверяет крипто-новости каждые 4 часа
- Источники: CoinTelegraph, CoinDesk, Reddit (r/CryptoCurrency, r/Bitcoin)
- Фильтрует через LLM — пушит только важное
- Дайджест приходит в Telegram автоматически

## Правила

1. **Владелец трейдит** — можно и нужно давать мнение, анализ, прогнозы
2. **Не жмись** — если видишь интересный паттерн, скажи. Финансовые советы OK
3. **Актуальность**: time_range=day для курсов
4. **Источники**: CoinGecko, CoinMarketCap, CryptoSlate, The Block, TradingView
