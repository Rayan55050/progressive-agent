# Development Plan

## Phase 1 — Core + MVP [DONE]

The foundation: a working Telegram bot that thinks, remembers, and searches.

- Agent core with Builder pattern and reliable LLM wrapper
- Hybrid memory: SQLite + vector search + FTS5 + temporal decay
- Telegram channel: text, voice, streaming, draft updates, whitelist
- Speech-to-text via Whisper
- Web search via Tavily (multi-provider)
- Router + Dispatcher (native tool_use + XML fallback)
- Soul system: personality, owner profile, rules, traits
- Cost tracker, scheduler, TOML config

## Phase 2 — Daily Utility [DONE]

Making the agent genuinely useful every day.

- Email tools (read, send, draft) + Gmail OAuth2
- File management (9 tools: search, read, write, delete, PDF, copy, open, send)
- CLI execution tool with security hardening
- 6-level LLM fallback chain (Claude proxy, Gemini, Mistral, Cloudflare, OpenAI, Claude API)
- Crypto monitor (BTC price alerts via CoinGecko)
- News radar monitor (daily AI/tech digest)
- Morning briefing monitor
- Subscription tracker with renewal reminders
- Auto-start on Windows boot (watchdog + heartbeat)
- 63+ tools including free APIs: DefiLlama, DexScreener, Wikipedia, TMDB, and more

## Phase 3 — Advanced Monitoring & Finance [NEXT]

The agent proactively brings you information you care about.

- Extended crypto tools: multi-coin tracking, technical indicators, DeFi analytics
- Financial tracker: Monobank API integration, expense categorization, budget goals
- Twitch monitor: live stream notifications
- YouTube monitor: new uploads from subscriptions, video summarization
- Enhanced AI radar: GitHub trending, Reddit, curated tech news

## Phase 4 — Content Engine & Dashboard

The agent creates content and gets a proper admin interface.

- Content pipeline: research, write, SEO optimize, publish
- Image generation via DALL-E 3
- Skill creator: agent can build its own skills at runtime
- Web dashboard: FastAPI + React admin panel with real-time metrics

## Phase 5 — Business Modules & Polish

Production-grade polish and specialized business tools.

- Business automation modules
- Performance optimization and caching
- Comprehensive test suite and CI/CD
- Open-source release preparation (documentation, examples, guides)
- Plugin system foundation
