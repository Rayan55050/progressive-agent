# Progressive Agent -- What It Does

Progressive Agent is an open-source personal AI assistant that lives inside Telegram. You talk to it like a person, and it responds with the full power of a large language model backed by 50+ tools, persistent memory, and background monitors that proactively deliver information you care about.

## Core Idea

One bot. One chat. Everything you need.

Instead of switching between apps, dashboards, and browser tabs, you send a message in Telegram and the agent handles the rest -- searching the web, reading your email, tracking crypto prices, managing files on your computer, translating text, downloading media, checking the weather, and much more.

## Key Capabilities

- **Web search and research** -- multi-provider search (Tavily, SerpApi, Jina, Firecrawl) with deep research mode that synthesizes information from multiple sources.
- **File management** -- search, read, write, delete, copy, and send files. Generate PDFs. Parse documents (PDF, DOCX, XLSX, TXT).
- **Email** -- read your Gmail inbox, compose drafts, send messages. Background monitor alerts you about new emails.
- **Crypto tracking** -- real-time prices via CoinGecko, DeFi protocol data via DefiLlama, token discovery via DexScreener, Fear and Greed Index. Background monitor pushes alerts on significant price moves.
- **Finance** -- Monobank integration (balance, transactions, exchange rates), PrivatBank and NBU exchange rates, subscription tracking with renewal reminders.
- **Media** -- download video/audio from 1000+ sites (yt-dlp), YouTube search and video summaries, Twitch stream notifications.
- **Local tools** -- execute shell commands, manage git repositories, take screenshots, generate QR codes, text-to-speech, image generation (DALL-E 3).
- **Knowledge** -- Wikipedia lookups, HackerNews feed, Reddit browsing, TMDB movie/TV database, weather forecasts.
- **Translation** -- DeepL-powered translation between languages.
- **Morning briefing** -- daily automated digest at 08:00 with weather, crypto, exchange rates, email summary, and upcoming subscription renewals. Zero LLM tokens consumed.

## Privacy First

Everything runs on your own machine. Conversations, memory, and files stay local in a SQLite database. The only external calls are to the LLM API and the specific tool APIs you configure. No telemetry, no cloud storage, no third-party data collection.

## Self-Adapting

The agent remembers your preferences, past conversations, and important facts. It uses hybrid memory search (vector similarity + full-text keyword search + temporal decay) to recall relevant context. After a restart, it restores recent conversation history so you can pick up where you left off.

## Who Is This For

- Developers who want a programmable personal assistant they fully control.
- Power users who want to consolidate notifications, research, and daily tasks into one chat interface.
- Anyone who values privacy and wants an AI assistant that does not send their data to third parties.

## Quick Start

```bash
git clone https://github.com/progressive-ai-community/progressive-agent.git
cd progressive-agent
uv sync
cp .env.example .env   # fill in your API keys
uv run python -m src.main
```

Open your Telegram bot and start chatting. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for technical details.
