# Статус проекта Progressive Agent

## Текущая фаза: Phase 3 — DONE ✅
## Последнее обновление: 2026-02-20

## Что работает

### Core (Phase 1 — DONE)
- Config (TOML + .env), LLM (FallbackProvider: proxy + API key), Reliable wrapper
- Agent (builder-паттерн), Router (keyword matching), Dispatcher (Native + XML)
- Memory (hybrid: vector + keyword + temporal decay + history restore)
- Cost tracker, Scheduler (APScheduler)
- Telegram channel (whitelist, draft updates, streaming, typing, files)

### Tools (42 шт.)
- **Search** (4): web_search (Tavily/SerpApi/Jina/Firecrawl), web_read, web_extract, web_research
- **File** (9): file_search, file_read, file_list, file_write, file_delete, file_open, file_send, file_pdf, file_copy
- **Email** (3): email_inbox, email_read, email_compose (Gmail OAuth2)
- **Monobank** (3): monobank_balance, monobank_transactions, monobank_rates
- **Obsidian** (4): obsidian_note, obsidian_search, obsidian_daily, obsidian_list
- **Browser** (5): browser_open, browser_action, browser_history, browser_bookmarks, browser_close
- **Twitch** (1): twitch_status (кто из стримеров онлайн)
- **YouTube** (5): youtube_search, youtube_info, youtube_summary (транскрипт+суммари), youtube_subscriptions (OAuth), youtube_liked (OAuth)
- **STT** (1): speech_to_text (faster-whisper, local)
- **CLI** (1): cli_exec (cmd/powershell/bash)
- **Git** (1): git (status, diff, log, add, commit, push, pull, fetch, checkout, branch, reset, clone, tag, stash, blame, show)
- **Agent Control** (1): agent_control (restart, update, health)
- **Subscription** (3): subscription_add, subscription_list, subscription_remove
- **Exchange Rates** (1): exchange_rates (PrivatBank + НБУ + конвертация, zero API keys)
- **System** (1): system (CPU, RAM, disk, processes, network — psutil)
- **Media** (1): media_download (yt-dlp, video/audio/info с 1000+ сайтов)

### Monitors (9)
- **EmailMonitor** — Gmail inbox, каждую 1 мин, persistent state, bro-style уведомления
- **ProxyMonitor** — CLIProxyAPI health check, каждые 2 мин, авто-рестарт
- **CryptoMonitor** — BTC через CoinGecko API, каждые 2 мин, уведомление при $500+ движении + Fear & Greed Index
- **MonobankMonitor** — транзакции, каждые 3 мин, пуш на новые списания/зачисления
- **SubscriptionMonitor** — подписки, daily check в 09:00, напоминания за 3/1 день + при продлении
- **NewsRadarMonitor** — крипто + AI новости каждые 4ч, 7 источников, LLM-фильтрация, дайджест в Telegram
- **TwitchMonitor** — Twitch Helix API, каждые 3 мин, пуш при старте стрима из списка
- **YouTubeMonitor** — YouTube Data API v3, каждые 30 мин, пуш при новом видео на каналах
- **MorningBriefingMonitor** — ежедневный дайджест в 08:00 (погода, BTC+FnG, курс UAH, email, подписки, задачи) — zero LLM tokens

### Skills (13 шт.)
- **Рабочие** (с реальными тулами): web_search, email, files, cli, crypto, finance (Monobank), obsidian, browser, twitch, youtube
- **Инструкции** (нужны API интеграции): ai_radar, content, skill_creator

### Prompt Architecture
- **prompts/TOOLS.md** — правила работы с инструментами, анти-галлюцинация, карта тулов
- **prompts/SELF_MAP.md** — самоосведомлённость: структура проекта, самодиагностика, самопочинка
- Порядок в system prompt: TOOLS → SELF_MAP → soul/personality → memories

### Безопасность и UX
- **Stranger troll mode** — чужие пользователи получают троллинг-ответы, без тулов/памяти/скиллов
- **Rate limiting** — 5 msg / 10 min на чужого, статические ответы при превышении
- **Owner notifications** — пуш при первом контакте от нового чужого (@username, ID, текст, ответ бота)
- **Startup notification** — при запуске бот отправляет статус в Telegram (LLM, tools, skills, monitors, history)
- **History restore** — после перезапуска бот восстанавливает последние 3 разговора (полный tool chain)

### Автозапуск (Windows)
- **start_silent.vbs** — невидимый запуск CLIProxyAPI + бота (проверяет дубли, логирует в data/bot_startup.log)
- **stop_agent.vbs** — остановка всех процессов
- **Startup shortcut** — ProgressiveAgent.lnk в Windows Startup → автозапуск при включении компа

## Phase 2 — Выполнено (всё)

1. ~~CryptoMonitor~~ — BTC трекер через CoinGecko, $500 threshold, bro-style
2. ~~Stranger troll mode~~ — троллинг чужих, rate limiting, owner notifications
3. ~~Автозапуск Windows~~ — start_silent.vbs + Startup shortcut
4. ~~Startup notification~~ — статус-сообщение в Telegram при запуске
5. ~~History restore~~ — восстановление контекста (полный tool chain, не plain text)
6. ~~Monobank~~ — 3 тула (баланс, транзакции, курсы) + MonobankMonitor (пуш на транзакции)
7. ~~Obsidian~~ — 4 тула (note, search, daily, list) + vault структура + шаблоны
8. ~~Browser~~ — 5 тулов (subprocess chrome + Playwright interaction) + stealth mode
9. ~~Anti-hallucination v3~~ — tool preamble FIRST, tool_choice=auto, history с tool chain
10. ~~Self-Map~~ — prompts/SELF_MAP.md, агент знает свою структуру и может самодиагностироваться

## Phase 3 — Мониторинг и контент (DONE ✅)

1. ~~Subscription monitor~~ — DONE (add/list/remove + daily reminders)
2. ~~NewsRadar monitor~~ — DONE (крипто + AI, 7 источников, LLM-фильтр, каждые 4ч)
3. ~~Twitch monitor~~ — DONE (Helix API, каждые 3 мин + twitch_status тул)
4. ~~YouTube monitor~~ — DONE (Data API v3, youtube_search + youtube_info + OAuth подписки/лайки, авто-синк каналов, мониторинг каждые 30 мин)

## Тесты
- 211 тестов проходят (test_config, test_core, test_skills, test_memory, test_telegram, test_files)

## Phase 4 — Контент и медиа (IN PROGRESS)

1. ~~Vision + Document parsing~~ — DONE (Claude Vision для фото/скриншотов/чеков, парсинг .pdf/.docx/.xlsx/.txt)
2. ~~Video notes (кружки)~~ — DONE (STT аудио + thumbnail через Vision, и свои и пересланные)
3. ~~Forwarded messages~~ — DONE (контекст "от кого" передаётся в Claude)
4. ~~Watchdog~~ — DONE (src/watchdog.py, авто-рестарт при крашах, crash loop protection)
5. ~~Email crash fix~~ — DONE (HTTP timeout 30s, asyncio timeout 60s, global crash handlers)
6. ~~Git tool~~ — DONE (first-class git operations: 16 операций, safety guards, always-available)
7. ~~Agent Control tool~~ — DONE (restart/update через watchdog exit codes, health status)
8. ~~Heartbeat Engine~~ — DONE (автономные задачи из HEARTBEAT.md, LLM-driven, configurable interval)
9. ~~Watchdog v2~~ — DONE (exponential backoff, health state JSON, self-update exit code 43, uptime tracking)
10. ~~Exchange rates tool~~ — DONE (PrivatBank cash + НБУ official + convert, zero API keys)
11. ~~System monitoring tool~~ — DONE (psutil: CPU, RAM, disk, processes, network, battery)
12. ~~Media download tool~~ — DONE (yt-dlp: video/audio/info с 1000+ сайтов, Telegram интеграция)
13. ~~Fear & Greed в CryptoMonitor~~ — DONE (alternative.me API, emoji-coded, в уведомлениях + briefing)
14. ~~MorningBriefingMonitor v2~~ — DONE (data-driven, zero LLM tokens: погода+крипто+курсы+email+подписки+задачи)

## Известные проблемы
- Skills без API = бесполезные web_search обёртки (AI radar, контент)
- Хостинг: бот работает только при включённом ПК (Oracle Cloud Free Tier в планах)
