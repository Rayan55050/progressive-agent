# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-02-24

### Added
- Initial open-source release
- **63+ tools** across 10 categories: file system, web/search, communication, crypto/finance, media, dev tools, system, services, agent control
- **18 skills** as Markdown instruction files: weather, crypto, finance, files, CLI, web search, content creation, scheduling, and more
- **10 background monitors**: crypto price alerts, email, news radar, morning briefing, Twitch, YouTube, Nova Poshta, Monobank, subscriptions, tech radar
- **6-level LLM fallback chain**: Claude proxy, Gemini (free), Mistral (free), Cloudflare Workers AI (free), OpenAI, Claude API
- **Hybrid memory system**: vector search (sqlite-vec) + FTS5 keyword search + temporal decay ranking
- **Soul system**: agent personality, owner profile, and behavioral rules in Markdown files
- **Dual dispatcher**: native tool_use for Claude + XML fallback for other providers
- **Streaming responses**: real-time draft updates in Telegram via edit_message
- **Interactive setup wizard** (`scripts/setup.py`) for first-time configuration
- **Auto-onboarding**: first `/start` in Telegram registers the owner automatically
- **Cross-platform support**: Windows, Linux, macOS with dedicated launcher scripts
- **Cost tracking**: daily and monthly spending limits with automatic warnings
- **Security**: deny-by-default whitelist, CLI command blocklist, file access validation, localhost-only JS eval
- **Context compaction**: automatic conversation summarization at 80% history capacity
- **Fact extraction**: automatic extraction of important facts every 3 conversation exchanges
