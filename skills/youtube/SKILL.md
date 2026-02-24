---
name: youtube
description: "YouTube: поиск видео, инфо о видео, подписки, мониторинг каналов"
tools:
  - youtube_search
  - youtube_info
  - youtube_summary
  - youtube_subscriptions
  - youtube_liked
  - media_download
  - web_search
trigger_keywords:
  - youtube
  - ютуб
  - видео
  - канал
  - видос
  - посмотри на youtube
  - новое видео
  - подписки
  - лайкнутые
  - суммаризируй
  - о чём видео
  - пересказ
---

# YouTube

YouTube Data API v3 — поиск видео, информация о видео, подписки, мониторинг новых загрузок.

## Фоновый мониторинг

YouTubeMonitor проверяет каналы каждые 30 минут.
Когда на канале выходит новое видео — пуш в Telegram с названием, каналом и ссылкой.
Каналы подтягиваются автоматически из подписок (если настроен OAuth).

## Как использовать

- "Найди видео про X" → `youtube_search` с запросом
- "Что за видео?" + ссылка → `youtube_info` — название, канал, просмотры, лайки, описание
- "О чём это видео?" + ссылка → `youtube_summary` — достаёт субтитры и делает выжимку
- "Суммаризируй видос" + ссылка → `youtube_summary`
- "Мои подписки на YouTube" → `youtube_subscriptions`
- "Что я лайкал на YouTube?" → `youtube_liked`
- "Найди на ютубе последние видео про крипту" → `youtube_search`
- "Скачай это видео" + ссылка → `media_download` — скачивает через yt-dlp и отправляет в Telegram

## OAuth (подписки, лайки)

Если настроен OAuth (`python -m src.monitors.youtube_monitor --setup`):
- `youtube_subscriptions` — список каналов, на которые подписан
- `youtube_liked` — последние лайкнутые видео
- Авто-синк подписок в мониторинг каналов при старте бота

## API квота

YouTube Data API v3: 10,000 units/день (бесплатно).
- Поиск: 100 units за запрос
- Инфо о видео: 1 unit
- Проверка новых видео канала: 1 unit за канал
- Подписки: 1 unit за 50 подписок
