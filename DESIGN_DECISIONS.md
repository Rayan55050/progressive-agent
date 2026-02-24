# Design Decisions

This document explains the key architectural choices in Progressive Agent and the reasoning behind them. Understanding these decisions will help contributors work with (not against) the project's design.

---

## Why Markdown Skills (Not Code)

**Decision:** Skills are Markdown files (`skills/*/SKILL.md`), not Python modules.

**Alternatives considered:** Python skill classes with execute methods, YAML configuration files, JSON schemas.

**Why Markdown:**

- **LLM-native.** Large language models understand natural language instructions better than structured configs. A Markdown skill file is literally a set of instructions that gets injected into the system prompt -- the LLM reads it the same way a human would.
- **Zero barrier to entry.** Anyone who can write a paragraph can create a skill. No Python knowledge required. This dramatically lowers the contribution threshold.
- **Instant iteration.** Edit a Markdown file, restart the bot, test. No compilation, no class hierarchies, no interface compliance.
- **Readable.** A skill file is self-documenting. You can read `skills/crypto/SKILL.md` and immediately understand what the bot does when asked about cryptocurrency.
- **Separation of concerns.** Tools handle the "can do" (capabilities). Skills handle the "should do" (instructions). This prevents the common anti-pattern of mixing business logic with LLM prompt engineering.

**Tradeoff:** Skills cannot contain executable logic. Complex workflows that require conditional branching or state management must be implemented as tools.

---

## Why SQLite (Not Postgres)

**Decision:** All data (memory, conversation history, embeddings, state) is stored in a single SQLite database.

**Alternatives considered:** PostgreSQL with pgvector, Redis, MongoDB, Pinecone, ChromaDB.

**Why SQLite:**

- **Zero dependencies.** No database server to install, configure, or maintain. The database is a single file (`data/memory.db`).
- **Portable.** Copy the file to another machine and everything works. Back it up by copying a file.
- **Privacy.** Your data never leaves your machine. No cloud database, no network exposure, no connection strings to leak.
- **Performance.** For a single-user personal assistant, SQLite handles the workload with room to spare. With WAL mode and proper indexing, it supports concurrent reads during writes.
- **sqlite-vec for vectors.** The `sqlite-vec` extension provides native vector similarity search within SQLite, eliminating the need for a separate vector database.
- **FTS5 for keywords.** SQLite's built-in FTS5 module provides full-text search with BM25 ranking -- no external search engine needed.

**Tradeoff:** Not suitable for multi-user deployments with high concurrency. If the project ever needs multi-tenant support, a migration to PostgreSQL would be necessary.

---

## Why asyncio (Not Threading)

**Decision:** The entire codebase is async/await, built on Python's `asyncio`.

**Alternatives considered:** Threading with `concurrent.futures`, multiprocessing, Trio.

**Why asyncio:**

- **Natural fit for I/O-bound work.** A Telegram bot spends most of its time waiting: waiting for user messages, waiting for API responses, waiting for LLM completions. async/await handles thousands of concurrent I/O operations without thread overhead.
- **Single event loop simplicity.** One event loop, one thread for the main logic. No race conditions from shared mutable state, no deadlocks from lock ordering.
- **Library ecosystem.** `aiogram` (Telegram), `aiohttp` (HTTP), `aiofiles` (file I/O), and the Anthropic/OpenAI SDKs all natively support asyncio.
- **Streaming.** LLM streaming responses (draft updates in Telegram) map naturally to async iterators.
- **APScheduler integration.** The `AsyncIOScheduler` from APScheduler runs background monitors (crypto, email, news) on the same event loop without threading complexity.

**Tradeoff:** CPU-bound work (like local STT) blocks the event loop. These operations are run in a thread executor via `asyncio.to_thread()`.

---

## Why a Fallback Chain (Not a Single Provider)

**Decision:** The bot tries up to 6 LLM providers in sequence, falling through on failure.

**Alternatives considered:** Single provider with retries, load balancing across providers, user-selectable provider per request.

**Why a fallback chain:**

- **Reliability.** No single provider has 100% uptime. API keys expire, rate limits hit, services go down. The chain ensures the bot always has a working LLM.
- **Cost optimization.** The chain is ordered by cost: free providers first (Claude subscription proxy, Gemini free tier, Mistral free tier), paid providers last (OpenAI, Claude API). This minimizes API spend.
- **Zero configuration needed.** Users configure whatever providers they have keys for. The bot automatically uses what is available and skips what is not.
- **Graceful degradation.** If the best model (Claude Opus) is unavailable, the bot falls back to a smaller model rather than failing entirely. Some answer is better than no answer.

**Tradeoff:** Different providers have different capabilities (tool calling support, context window size, response quality). The bot may behave slightly differently depending on which provider handles a given request.

---

## Why Telegram (Not Discord/Slack)

**Decision:** Telegram is the primary (and currently only) channel interface.

**Alternatives considered:** Discord, Slack, WhatsApp, web interface.

**Why Telegram:**

- **Target audience.** Telegram is the dominant messaging platform in Ukraine and across Eastern Europe / CIS countries, where the project originates.
- **Bot API quality.** Telegram's Bot API is well-documented, stable, and feature-rich: inline keyboards, file upload/download, voice messages, video notes, message editing (used for streaming), and Markdown formatting.
- **aiogram maturity.** The `aiogram` library (version 3) is a production-grade async Telegram framework with excellent Python support.
- **Privacy-friendly.** Telegram supports secret chats, does not require a phone number to be visible, and allows bots to operate without a public profile.
- **Low latency.** Message delivery is near-instant. Edit-based streaming (progressive message updates) provides a smooth UX.

**Tradeoff:** Users who prefer Discord or Slack cannot use the bot without writing a new channel adapter. The `Channel` protocol in `src/channels/base.py` is designed for exactly this extension, but no other implementations exist yet.

---

## Why TOML (Not YAML/JSON)

**Decision:** All configuration files use TOML format (`config/agent.toml`).

**Alternatives considered:** YAML, JSON, Python files, INI.

**Why TOML:**

- **Human-readable.** TOML is easy to read and write by hand. No indentation sensitivity (unlike YAML), no trailing comma issues (unlike JSON).
- **Type-safe.** TOML has native types for strings, integers, floats, booleans, dates, and arrays. `allowed_users = [123456789]` is unambiguously a list of integers -- no YAML "Norway problem" where `NO` becomes `false`.
- **Comments.** TOML supports inline comments (`# this is a comment`). JSON does not.
- **Python stdlib support.** Python 3.11+ includes `tomllib` in the standard library. For 3.11 compatibility, the lightweight `tomli` package is used.
- **Industry trend.** TOML is the standard for Python project configuration (`pyproject.toml`), Rust (`Cargo.toml`), and many modern tools. It is familiar to the target audience.

**Tradeoff:** TOML is less expressive than YAML for deeply nested structures. This has not been an issue -- the agent configuration is flat by design.

---

## Why Local STT (Not Cloud)

**Decision:** Speech-to-text uses `faster-whisper` running locally on CPU.

**Alternatives considered:** OpenAI Whisper API, Google Cloud Speech-to-Text, Azure Speech Services.

**Why local:**

- **Privacy.** Voice messages often contain sensitive information. Local processing ensures audio never leaves the user's machine.
- **No API costs.** Cloud STT services charge per minute of audio. Local processing is free after the one-time model download.
- **No API key required.** Reduces setup complexity. The bot transcribes voice messages out of the box.
- **Offline capability.** Works without internet (after initial model download).
- **Quality.** Whisper `large-v3` provides excellent accuracy for multilingual speech (Russian, Ukrainian, English), which is critical for the target audience.

**Tradeoff:** The `large-v3` model requires ~3 GB of disk space and is slow on CPU (a few seconds per short voice message). Users with limited resources can switch to smaller models (`base`, `small`, `medium`) in the configuration.

---

## Why Tools + Skills Separation

**Decision:** The bot has two distinct extension mechanisms: tools (Python code) and skills (Markdown instructions).

**Alternatives considered:** Unified plugin system, tools-only, LangChain-style agents.

**Why the separation:**

- **Tools = capabilities.** A tool is a Python function that can call an API, read a file, execute a command. It defines *what* the bot can do. Tools are deterministic, testable, and language-agnostic.
- **Skills = instructions.** A skill is a prompt injected into the system message. It defines *how* and *when* the bot should use tools. Skills shape the LLM's behavior: response format, tone, decision-making logic.
- **Independent evolution.** You can improve a skill (better instructions) without touching tool code. You can add a tool without writing a skill -- the LLM can figure out basic usage from the tool's description alone.
- **Non-programmer contributions.** Skill creation requires no Python. A domain expert who knows nothing about code can write a skill file that teaches the bot how to handle cryptocurrency analysis, email triage, or news summarization.
- **Inspired by OpenClaw.** This pattern comes from the OpenClaw project (157K+ GitHub stars), where it has proven effective at scale. Skills as Markdown files is their core innovation.

**Tradeoff:** The two-layer system can be confusing for newcomers. The [FAQ](FAQ.md) and [CONTRIBUTING.md](CONTRIBUTING.md) explain the distinction clearly.
