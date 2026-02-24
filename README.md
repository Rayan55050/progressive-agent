<p align="center">
  <img src="https://img.shields.io/badge/🤖-Progressive_Agent-black?style=for-the-badge&labelColor=000" alt="Progressive Agent" height="60">
</p>

<p align="center">
  <strong>Your personal AI assistant that lives in Telegram.<br>63+ tools. 18 skills. 10 monitors. Hybrid memory. Runs on your machine.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"></a>
  <a href="https://core.telegram.org/bots/api"><img src="https://img.shields.io/badge/Telegram-Bot_API-26A5E4?style=flat-square&logo=telegram&logoColor=white" alt="Telegram"></a>
  <a href="https://docs.anthropic.com/"><img src="https://img.shields.io/badge/LLM-Claude_|_GPT_|_Gemini-8A2BE2?style=flat-square" alt="Multi-LLM"></a>
</p>

---

## What is this?

Progressive Agent is a **fully async, privacy-first personal AI assistant** for Telegram. Not a chatbot — an agent that **actually does things**: browses the web, manages files, monitors crypto prices, checks your email, tracks packages, generates images, recognizes songs, and 60+ more capabilities.

Everything runs **locally on your machine**. Your data stays yours.

> **Built for personal use.** One owner, one bot, full control. The agent learns your name, preferences, and habits — and adapts to you over time.

---

## How It Works

```
You (Telegram)
 │
 ▼
┌─────────────────────────────────────────────────────────┐
│                    PROGRESSIVE AGENT                     │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  Router   │  │  Memory  │  │   Soul   │  │Scheduler│ │
│  │ (skill   │  │ (vector  │  │(SOUL.md  │  │(10 bg   │ │
│  │ matching)│  │ +keyword │  │ OWNER.md │  │monitors)│ │
│  │          │  │ +decay)  │  │ RULES.md)│  │         │ │
│  └────┬─────┘  └──────────┘  └──────────┘  └─────────┘ │
│       │                                                  │
│  ┌────▼──────────────────┐  ┌──────────────────────────┐│
│  │      Dispatcher       │  │    LLM Provider          ││
│  │ (native tool_use +   │──│ Claude → Gemini → Mistral ││
│  │  XML fallback)        │  │ → Cloudflare → OpenAI    ││
│  └────┬──────────────────┘  └──────────────────────────┘│
│       │                                                  │
│  ┌────▼──────────────────┐                               │
│  │    63+ Tools          │  ← execute, get result, loop │
│  │ (Python, async, API)  │                               │
│  └───────────────────────┘                               │
└─────────────────────────────────────────────────────────┘
 │
 ▼
You (Telegram) ← streaming response with draft updates
```

**The loop:** Message → load memories → build system prompt → route to skill → call LLM → execute tools → loop until done → save to memory → respond.

---

## Features

| | Feature | Description |
|---|---------|-------------|
| 🔧 | **63+ Tools** | File ops, browser automation, CLI, email, crypto, weather, YouTube, image gen, TTS, OCR, and much more |
| 📋 | **18 Skills** | Markdown files injected into the LLM prompt. Add new skills without writing code |
| 👁️ | **10 Monitors** | Background jobs: crypto alerts, email, news digest, Twitch, YouTube, morning briefing |
| 🧠 | **Hybrid Memory** | Vector search (sqlite-vec) + FTS5 keyword + temporal decay. Remembers everything locally |
| 🔄 | **6-Level Fallback** | Claude → Gemini (free) → Mistral (free) → Cloudflare (free) → OpenAI → Claude API |
| 🎙️ | **Voice & Media** | Local STT, TTS video circles, Shazam, DALL-E 3, background removal, OCR, screenshots |
| 🔒 | **Privacy-First** | Everything on your machine. SQLite memory. Local STT. Deny-by-default security |
| 🏗️ | **Soul System** | Personality, rules, traits — all in Markdown. The agent has character, not just functions |
| ⚡ | **Streaming** | Real-time draft updates in Telegram via `edit_message` |
| 🤖 | **Self-Aware** | Knows its own codebase, can read logs, diagnose issues, even fix bugs |

---

## Tools (63+)

<details>
<summary><b>📁 File System (9 tools)</b></summary>

`file_read` · `file_write` · `file_list` · `file_search` · `file_delete` · `file_copy` · `file_open` · `file_send` · `file_pdf`

PDF generation, document parsing (Word, Excel, CSV), directory operations.
</details>

<details>
<summary><b>🌐 Web & Search (4 tools)</b></summary>

`web_search` · `web_reader` · `web_extract` · `web_research`

Multi-provider: Tavily (with auto key rotation), SerpApi, Jina, Firecrawl.
</details>

<details>
<summary><b>💰 Crypto & DeFi (4 tools, all FREE)</b></summary>

`coingecko` · `defi_llama` · `dex_screener` · `fear_greed`

Prices for 10K+ coins, TVL, DEX pairs, yield pools, Fear & Greed Index. Zero API keys needed.
</details>

<details>
<summary><b>💵 Finance (6 tools)</b></summary>

`monobank_balance` · `monobank_transactions` · `monobank_rates` · `exchange_rates` · `finnhub` · `subscription_*`

Bank balance, transactions, UAH/USD/EUR rates (PrivatBank + NBU), stock data, subscription tracking.
</details>

<details>
<summary><b>🎨 Media & Vision (9 tools)</b></summary>

`image_gen` · `bg_remove` · `ocr` · `diagram` · `exif` · `tts` · `stt` · `shazam` · `audio_capture`

DALL-E 3 generation, AI background removal (local), text recognition, Mermaid diagrams, EXIF/GPS reading, text-to-speech video circles, local Whisper STT, Shazam song recognition, system audio capture.
</details>

<details>
<summary><b>🖥️ System & Dev (6 tools)</b></summary>

`cli_exec` · `git` · `system` · `screenshot` · `clipboard` · `speedtest`

Execute any shell command, Git operations (16 commands), CPU/RAM/disk monitoring, screenshots, clipboard access, internet speed test.
</details>

<details>
<summary><b>🌍 Knowledge & Social (6 tools, all FREE)</b></summary>

`wikipedia` · `tmdb` · `github` · `hackernews` · `reddit` · `ukrpravda`

Wikipedia (3 languages), movies/TV (TMDB), GitHub trending, Hacker News, Reddit, Ukrainian news RSS.
</details>

<details>
<summary><b>🇺🇦 Ukraine-specific (5 tools)</b></summary>

`novaposhta` · `alerts_ua` · `prozorro` · `datagov` · `exchange_rates`

Nova Poshta tracking, air raid alerts, government procurement (Prozorro), open data (80K+ datasets), currency rates.
</details>

<details>
<summary><b>📧 Communication (4 tools)</b></summary>

`email_inbox` · `email_read` · `email_compose` · `contact`

Gmail (OAuth2), contact management (add/list/remove/update).
</details>

<details>
<summary><b>🔮 Browser (5 tools)</b></summary>

`browser_open` · `browser_action` · `browser_close` · `browser_history` · `browser_bookmarks`

Playwright-based automation: click, fill, scroll, screenshot, eval JS. Chrome history & bookmarks.
</details>

<details>
<summary><b>📊 Data & Docs (4 tools)</b></summary>

`csv_analyst` · `pdf_tool` · `deepl` · `qr_code`

CSV/Excel analysis with pandas + matplotlib charts, PDF text/merge/split, DeepL translation, QR code generation.
</details>

<details>
<summary><b>🤖 Agent (6 tools)</b></summary>

`agent_control` · `skill_manager` · `goal` · `multi_agent` · `media_download` · `scheduler_*`

Self-restart, runtime skill CRUD, long-running background goals, parallel sub-agents, yt-dlp media download, reminders & scheduling.
</details>

---

## Skills (18)

Skills are **Markdown instruction files** — not code. They get injected into the LLM system prompt when triggered by keywords.

```
skills/
├── weather/SKILL.md      # "какая погода?" → weather tool instructions
├── crypto/SKILL.md       # "биткоин" → CoinGecko + DeFi tools
├── finance/SKILL.md      # "баланс" → Monobank + exchange rates
├── email/SKILL.md        # "проверь почту" → Gmail API
├── browser/SKILL.md      # "открой сайт" → Playwright
├── files/SKILL.md        # "создай файл" → file operations
├── cli/SKILL.md          # "запусти команду" → shell execution
├── youtube/SKILL.md      # "найди видео" → YouTube API
├── twitch/SKILL.md       # "кто стримит?" → Twitch API
├── obsidian/SKILL.md     # "запиши мысль" → Obsidian vault
├── web_search/SKILL.md   # "найди в интернете" → multi-provider search
├── scheduler/SKILL.md    # "напомни через час" → APScheduler
├── content/SKILL.md      # "напиши пост" → content creation
├── image_gen/SKILL.md    # "нарисуй" → DALL-E 3
├── tts/SKILL.md          # "скажи голосом" → TTS + video circles
├── novaposhta/SKILL.md   # "где посылка?" → Nova Poshta API
├── ai_radar/SKILL.md     # AI/ML news and trends
└── skill_creator/SKILL.md # meta: create new skills at runtime
```

**Adding a new skill** = create a folder + write a SKILL.md file. No Python needed. The router auto-detects it.

---

## Monitors (10 background jobs)

| Monitor | Interval | What it does |
|---------|----------|--------------|
| **CryptoMonitor** | 2 min | BTC price via CoinGecko, alerts on $500+ movement + Fear & Greed Index |
| **NewsRadarMonitor** | 4 hours | Crypto + AI + Ukraine news from 10+ sources, LLM-filtered digest |
| **MorningBriefingMonitor** | Daily 08:00 | Weather + crypto + UAH rate + email + subscriptions — zero LLM tokens |
| **SubscriptionMonitor** | Daily 09:00 | Reminders 3 days / 1 day before renewal |
| **EmailMonitor** | 1 min | Gmail inbox, push on new emails |
| **TwitchMonitor** | 3 min | Twitch Helix API, push when streamers go live |
| **YouTubeMonitor** | 30 min | YouTube Data API, push on new videos |
| **NovaPoshtaMonitor** | 30 min | Package status changes |
| **ProxyMonitor** | 2 min | LLM proxy health check + auto-restart |
| **HeartbeatEngine** | 30 min | Autonomous tasks from HEARTBEAT.md |

---

## The Prompt Architecture

This is the core innovation — **how the agent thinks**.

```
┌──────────────────────────────────────────────────────┐
│                  SYSTEM PROMPT                        │
│                                                       │
│  1. prompts/TOOLS.md          ← Tool instructions    │
│     "Call tools, don't narrate"                       │
│     Anti-hallucination rules                          │
│     Map of all 63+ tools                              │
│     "specialized tool > web_search"                   │
│                                                       │
│  2. prompts/SELF_MAP.md       ← Self-awareness       │
│     Project structure, self-diagnosis,                │
│     self-repair capabilities                          │
│                                                       │
│  3. soul/SOUL.md              ← Who am I             │
│     soul/OWNER.md             ← Who is the owner     │
│     soul/RULES.md             ← How to behave        │
│     soul/traits/*.md          ← 11 personality traits │
│                                                       │
│  4. Relevant memories         ← From hybrid search   │
│                                                       │
│  5. AGENTS.md                 ← Self-improvement log  │
│                                                       │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
│  6. Active Skill instructions ← If skill matched     │
│     (e.g., crypto/SKILL.md)                           │
└──────────────────────────────────────────────────────┘
```

**Order matters.** Tool instructions go FIRST — before personality. This ensures the LLM calls tools instead of just talking about them.

---

## Quick Start

### Prerequisites

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- At least one LLM API key (Claude, OpenAI, Gemini, or Mistral)

### Installation

```bash
# Clone
git clone https://github.com/progressive-ai-community/progressive-agent.git
cd progressive-agent

# Option A: Interactive setup (recommended)
python scripts/setup.py

# Option B: Manual
pip install -r requirements.txt
cp .env.example .env    # edit with your API keys
python -m src.main
```

**Windows:** double-click `install.bat`
**Linux/macOS:** `chmod +x install.sh && ./install.sh`

### First Run

On first `/start` in Telegram, the agent will:
1. Detect your Telegram ID and save it as the owner
2. Ask your name, city, and interests
3. Fill in `soul/OWNER.md` with your profile
4. Start working — fully personalized

### Running Tests

```bash
pytest tests/ -v
```

---

## Configuration

### Required (`.env`)

| Key | What | Where to get |
|-----|------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot | [@BotFather](https://t.me/BotFather) |
| At least one LLM key: | | |
| `OPENAI_API_KEY` | OpenAI (GPT + embeddings + DALL-E) | [platform.openai.com](https://platform.openai.com/api-keys) |
| `GEMINI_API_KEY` | Google Gemini (**free**, 15 RPM) | [aistudio.google.com](https://aistudio.google.com/apikey) |
| `MISTRAL_API_KEY` | Mistral (**free**, 1B tokens/mo) | [console.mistral.ai](https://console.mistral.ai) |

### Optional

| Key | What | Free Tier |
|-----|------|-----------|
| `TAVILY_API_KEY` | Web search | 1000/month |
| `CLOUDFLARE_API_KEY` | Workers AI (LLM fallback) | 10K/day |
| `FINNHUB_API_KEY` | Stock data | 60 calls/min |
| `TWITCH_CLIENT_ID` | Twitch monitor | Unlimited |
| `YOUTUBE_API_KEY` | YouTube monitor | 10K units/day |
| `DEEPL_API_KEY` | Translation | 500K chars/month |
| `TMDB_API_KEY` | Movies/TV | Unlimited |
| `NOVAPOSHTA_API_KEY` | Package tracking | Unlimited |

See [`.env.example`](.env.example) for the full list.

### Agent Settings (`config/agent.toml`)

```toml
[agent]
name = "Progressive Agent"
default_model = "claude-opus-4-6"
max_tokens = 16384

[telegram]
allowed_users = []  # Auto-detected on first /start

[memory]
db_path = "data/memory.db"
embedding_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
```

---

## Project Structure

```
progressive-agent/
├── config/                 # TOML configuration
│   └── agent.toml          # All settings (memory, costs, monitors, etc.)
├── docs/                   # Detailed documentation
│   ├── ARCHITECTURE.md     # Full architecture deep-dive
│   ├── API_DOCUMENTATION.md # How to create tools & skills
│   └── DEPLOYMENT_GUIDE.md # Windows / Linux / Oracle Cloud
├── prompts/                # LLM system prompt components
│   ├── TOOLS.md            # Tool map & anti-hallucination rules
│   └── SELF_MAP.md         # Agent self-awareness
├── skills/                 # 18 skill definitions (Markdown)
│   └── */SKILL.md          # Each skill = trigger keywords + instructions
├── soul/                   # Agent personality system
│   ├── SOUL.md             # Core identity & communication style
│   ├── OWNER.md            # Owner profile (auto-filled on first run)
│   ├── RULES.md            # Security, format, honesty rules
│   └── traits/             # 11 behavioral traits (action rules, tone, etc.)
├── src/
│   ├── core/               # Agent brain (13 modules)
│   │   ├── agent.py        # Orchestrator (Builder pattern, tool loop)
│   │   ├── llm.py          # 6 LLM providers + FallbackProvider
│   │   ├── dispatcher.py   # Native tool_use + XML fallback
│   │   ├── router.py       # Skill routing (keywords → prompt injection)
│   │   └── ...             # config, scheduler, costs, goals, orchestrator
│   ├── tools/              # 48 tool implementations (Python, async)
│   ├── monitors/           # 10 background monitors (APScheduler)
│   ├── memory/             # Hybrid memory (vector + FTS5 + decay)
│   ├── channels/           # Telegram channel (aiogram 3)
│   └── skills/             # Skill loader & registry
├── tests/                  # Test suite (9 test files)
├── .env.example            # Environment template with all keys
├── pyproject.toml          # Dependencies (MIT, Python 3.11+)
└── CLAUDE.md               # Development instructions
```

---

## Adding New Tools

Implement the Tool protocol — that's it:

```python
from src.core.tools import ToolDefinition, ToolParameter, ToolResult

class MyTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="my_tool",
            description="What this tool does",
            parameters=[
                ToolParameter(name="query", type="string", description="Search query"),
            ],
        )

    async def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "")
        # ... your async logic here
        return ToolResult(success=True, data="Result")
```

Register in the agent builder → the LLM instantly sees it as a callable function.

## Adding New Skills

Create `skills/my_skill/SKILL.md`:

```markdown
---
name: my_skill
description: "What this skill does"
tools:
  - my_tool
trigger_keywords:
  - keyword1
  - keyword2
---

# My Skill

Instructions for the LLM in natural language.
When the user asks about X, use `my_tool` with Y parameters.
```

The router auto-detects the new skill. No restart needed if using `skill_manager`.

---

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-tool`)
3. Follow the code style: async/await, type hints, logging (not print)
4. Add tests for new functionality
5. Submit a pull request

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details and [`API_DOCUMENTATION.md`](docs/API_DOCUMENTATION.md) for the tool/skill creation guide.

---

## License

[MIT](LICENSE) — use it, fork it, build on it.

---

<p align="center">
  Built by <a href="https://progressiveai.me">Progressive AI</a>
</p>
