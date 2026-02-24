---
name: ai_radar
description: "AI-новости: модели, инструменты, тренды в ИИ"
tools:
  - web_search
  - web_extract
  - web_research
trigger_keywords:
  - ai новости
  - новости ии
  - искусственный интеллект
  - нейросети
  - llm
  - gpt
  - claude
  - gemini
  - что нового в ai
  - ai news
  - новая модель
  - anthropic
  - openai
  - google ai
---

# AI Radar

Мониторинг новостей и трендов в мире искусственного интеллекта.

## Стратегия поиска

### Последние новости
- `"AI news today"` (topic: news, time_range: day)
- `"artificial intelligence news this week"` (topic: news, time_range: week)

### Новые модели
- `"new AI model release 2026"` (topic: news)
- `"Claude Anthropic update"`, `"GPT OpenAI update"`, `"Gemini Google update"`

### Инструменты и продукты
- `"AI tools launch"` (topic: news, time_range: week)
- `"AI automation tools new"` (topic: general)

### Глубокий анализ
Если просят ресёрч — используй `web_research` для комплексного анализа темы.

## Источники (приоритет)
- The Verge, TechCrunch, Ars Technica
- Anthropic Blog, OpenAI Blog
- Habr.com (русскоязычный)
- Twitter/X через поиск

## Формат ответа

Новости — блоками с эмодзи-маркерами:
```
🔥 *Название*
Краткое описание + [ссылка](url)

📌 *Название*
Описание + [ссылка](url)
```

## NewsRadar (фоновый мониторинг)

Работает автоматически каждые 4 часа:
- Источники: Hacker News, HuggingFace Daily Papers, Reddit (r/LocalLLaMA, r/MachineLearning), GitHub Trending
- Фильтрует через LLM — пушит только реально важное
- Дайджест приходит в Telegram автоматически

Когда владелец спрашивает про AI-новости — я могу дополнить свежим поиском через web_search.

## Правила

1. **Релевантность для владельца**: фокус на агентах, автоматизации, Claude, инструментах (уточняется по OWNER.md)
2. **Без хайпа**: факты, не спекуляции
3. **Практичность**: если модель/тул может быть полезен владельцу — отметь это
4. **Язык**: если нашёл на русском — отвечай на русском, на английском — переведи ключевые моменты
