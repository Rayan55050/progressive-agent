<p align="center">
  <h1 align="center">Progressive Agent</h1>
  <p align="center">
    <strong>Open-source personal AI assistant for Telegram — 63+ tools, 18 skills, hybrid memory, multi-provider LLM fallback</strong>
  </p>
  <p align="center">
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square" alt="Python 3.11+"></a>
    <a href="https://github.com/progressive-ai-community/progressive-agent/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License: MIT"></a>
    <a href="https://core.telegram.org/bots/api"><img src="https://img.shields.io/badge/Telegram-Bot%20API-26A5E4.svg?style=flat-square&logo=telegram" alt="Telegram Bot API"></a>
    <a href="https://docs.anthropic.com/"><img src="https://img.shields.io/badge/LLM-Claude%20%7C%20Gemini%20%7C%20GPT-8A2BE2.svg?style=flat-square" alt="Multi-LLM"></a>
  </p>
</p>

---

Progressive Agent is a fully async, privacy-first personal AI assistant that lives in Telegram. It combines the power of modern LLMs with 63+ tools, hybrid vector+keyword memory, background monitors, and a unique **Skills-as-Markdown** architecture where agent capabilities are defined in plain text files — not code.

Inspired by [OpenClaw](https://github.com/nicepkg/OpenClaw) and [ZeroClaw](https://github.com/nicepkg/ZeroClaw).

## Features

🧠 **Hybrid Memory** — Vector search (sqlite-vec) + FTS5 keyword search + temporal decay ranking. The agent remembers your conversations, preferences, and facts — locally, in SQLite.

🔧 **63+ Tools** — File operations, browser automation, CLI execution, email (Gmail API), crypto analytics, weather, YouTube/Twitch monitoring, image generation (DALL-E 3), TTS, OCR, QR codes, Reddit, GitHub, Wikipedia, PDF/CSV processing, and much more.

📋 **18 Skills** — Markdown instruction files (`skills/*/SKILL.md`) injected into the LLM system prompt. Skills define *how* the agent behaves for specific domains — weather forecasting, crypto analysis, file management, content creation, scheduling, and more. No code required to add new skills.

👁️ **10 Background Monitors** — Crypto price alerts, email checker, news radar, morning briefings, Twitch live notifications, YouTube new video alerts, Nova Poshta package tracking, Monobank transactions, subscription reminders, and tech radar — all running as APScheduler jobs with push notifications.

🔄 **6-Level LLM Fallback** — Claude (proxy) → Gemini (free) → Mistral (free) → Cloudflare Workers AI (free) → OpenAI → Claude API. The agent stays online even when your primary provider is down.

🎙️ **Voice & Media** — Speech-to-text (faster-whisper, local), text-to-speech (OpenAI + edge-tts), Shazam music recognition, video circles, image generation, background removal, EXIF reading, screenshots, and media download (yt-dlp).

🔒 **Privacy-First** — Everything runs on your machine. SQLite for memory, local STT, no cloud dependencies for core functionality. Deny-by-default security with Telegram user ID whitelist.

🌍 **Multi-Provider Search** — Tavily (with auto key rotation), SerpApi, Jina, Firecrawl — seamless fallback across search providers.

⚡ **Streaming Responses** — Real-time draft updates in Telegram via `edit_message`, so you see the response as it's being generated.

🏗️ **Soul System** — The agent's personality, owner profile, and behavioral rules live in `soul/` as Markdown files (`SOUL.md`, `OWNER.md`, `RULES.md`, `traits/`). Fully customizable without touching code.

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- At least one LLM API key (Claude, OpenAI, Gemini, or Mistral)

### Installation

```bash
# Clone the repository
git clone https://github.com/progressive-ai-community/progressive-agent.git
cd progressive-agent

# Install dependencies
uv sync
# or: pip install -e .

# Copy and fill in your environment variables
cp .env.example .env
# Edit .env with your API keys (see Configuration below)

# Run the agent
uv run python -m src.main
# or: python -m src.main
```

On first `/start` in Telegram, the agent will detect you as the owner and ask for your name, city, and interests to personalize its behavior.

### Running Tests

```bash
uv run pytest tests/ -v
```

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Telegram    │────>│  asyncio.Queue   │────>│     Agent       │
│  (aiogram 3) │     │  (unified queue) │     │  (orchestrator) │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                                                       │
                    ┌──────────┬───────────┬───────────┤
                    │          │           │           │
              ┌─────▼─────┐ ┌─▼────────┐ ┌▼────────┐ ┌▼──────────┐
              │  Router   │ │  Memory  │ │  Soul   │ │ Scheduler │
              │ (skill    │ │ (vector  │ │ (SOUL + │ │ (monitors │
              │  select)  │ │ +FTS5)   │ │ OWNER)  │ │  + cron)  │
              └─────┬─────┘ └──────────┘ └─────────┘ └───────────┘
                    │
              ┌─────▼─────┐     ┌──────────────┐
              │Dispatcher │────>│ LLM Provider │
              │(native +  │     │ (6-level     │
              │ XML dual) │     │  fallback)   │
              └─────┬─────┘     └──────────────┘
                    │
              ┌─────▼─────┐     ┌──────────────┐
              │   Tools   │────>│   Telegram   │
              │ (63+ exec)│     │ (streaming)  │
              └───────────┘     └──────────────┘
```

**Key patterns:**
- **Builder pattern** for Agent construction (`src/core/agent.py`)
- **asyncio.Queue pipeline** — all channels push messages into a single queue
- **Dual dispatcher** — native `tool_use` for Claude + XML fallback for other providers
- **Reliable wrapper** — automatic retries with exponential backoff and rate-limit handling

For the full architecture diagram, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Tools Overview

| Category | Tools |
|----------|-------|
| **File System** | File read/write/copy/move/delete, directory operations, PDF generation/reading, CSV/Excel analysis, document parsing (Word, Excel) |
| **Web & Search** | Multi-provider web search, browser automation, Reddit, Hacker News, Wikipedia |
| **Communication** | Email (Gmail API), Telegram media, contacts manager |
| **Crypto & Finance** | CoinGecko, DeFi Llama, DexScreener, Fear & Greed Index, Finnhub, exchange rates, Monobank |
| **Media** | Image generation (DALL-E 3), background removal, OCR, EXIF reader, TTS (OpenAI + edge-tts), STT (faster-whisper), Shazam, QR codes, screenshots, media download (yt-dlp) |
| **Dev Tools** | CLI execution (sandboxed), Git operations, GitHub API |
| **System** | System monitoring (CPU/RAM/disk), clipboard, speed test, scheduler |
| **Services** | Weather, Nova Poshta tracking, TMDB (movies/TV), DeepL translation, Alerts UA |
| **Agent** | Agent control, skill manager, orchestrator, goal tracking |

## Configuration

### Required Keys (`.env`)

| Key | Purpose | Where to get |
|-----|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot | [@BotFather](https://t.me/BotFather) |
| One LLM key (any): | | |
| `OPENAI_API_KEY` | OpenAI (GPT + embeddings + Whisper + DALL-E) | [platform.openai.com](https://platform.openai.com/api-keys) |
| `GEMINI_API_KEY` | Google Gemini (free 15 RPM) | [aistudio.google.com](https://aistudio.google.com/apikey) |
| `MISTRAL_API_KEY` | Mistral (free 1B tokens/month) | [console.mistral.ai](https://console.mistral.ai) |

### Optional Keys

| Key | Purpose | Free Tier |
|-----|---------|-----------|
| `TAVILY_API_KEY` | Web search | 1000 searches/month |
| `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID` | Workers AI (LLM fallback) | 10K neurons/day |
| `DEEPL_API_KEY` | Translation | 500K chars/month |
| `FINNHUB_API_KEY` | Stock/crypto data | 60 calls/min |
| `YOUTUBE_API_KEY` | YouTube monitor | 10K units/day |
| `TWITCH_CLIENT_ID` + `TWITCH_CLIENT_SECRET` | Twitch monitor | Unlimited |
| `TMDB_API_KEY` | Movies/TV info | Unlimited |
| `NOVAPOSHTA_API_KEY` | Package tracking | Unlimited |

See [`.env.example`](.env.example) for the full list with links.

### Agent Config (`config/agent.toml`)

```toml
[agent]
name = "Progressive Agent"
default_model = "claude-opus-4-6"
max_tokens = 16384

[telegram]
allowed_users = [123456789]  # Your Telegram user ID

[memory]
db_path = "data/memory.db"
embedding_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

[costs]
daily_limit_usd = 5.0
monthly_limit_usd = 50.0
```

## Adding New Skills

Skills are Markdown files — no Python required:

```
skills/
  my_skill/
    SKILL.md       # Instructions for the LLM
```

The agent's router automatically detects relevant skills and injects them into the system prompt. Write your instructions in natural language — the LLM follows them directly.

## Adding New Tools

Implement the Tool protocol:

```python
class MyTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="my_tool",
            description="Does something useful",
            parameters={...}
        )

    async def execute(self, **kwargs) -> ToolResult:
        # Your logic here
        return ToolResult(success=True, data="Done")
```

Register it in the agent builder and it's immediately available.

## Project Structure

```
progressive-agent/
├── config/              # TOML configuration files
├── docs/                # Architecture, roadmap, status
├── prompts/             # System prompt templates
├── scripts/             # Utility scripts
├── skills/              # Skill definitions (Markdown)
│   ├── weather/SKILL.md
│   ├── crypto/SKILL.md
│   ├── finance/SKILL.md
│   └── ...              # 18 skills total
├── soul/                # Agent personality
│   ├── SOUL.md          # Core personality
│   ├── OWNER.md         # Owner profile
│   ├── RULES.md         # Behavioral rules
│   └── traits/          # Additional traits
├── src/
│   ├── channels/        # Telegram (+ future channels)
│   ├── core/            # Agent, LLM, dispatcher, config, router
│   ├── memory/          # Hybrid vector + FTS5 memory
│   ├── monitors/        # Background jobs (10 monitors)
│   └── tools/           # Tool implementations (53 files)
├── tests/               # Test suite
├── .env.example         # Environment template
├── pyproject.toml       # Dependencies & project metadata
└── CLAUDE.md            # AI development instructions
```

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-tool`)
3. Follow the existing code style (async/await, type hints, logging)
4. Add tests for new functionality
5. Submit a pull request

See [`CLAUDE.md`](CLAUDE.md) for development guidelines and zone-of-responsibility rules.

## License

[MIT](LICENSE) — use it, fork it, build on it.

## Credits

Built by [Progressive AI](https://progressiveai.me) — AI Automation Expert.

Inspired by [OpenClaw](https://github.com/nicepkg/OpenClaw) and [ZeroClaw](https://github.com/nicepkg/ZeroClaw).
