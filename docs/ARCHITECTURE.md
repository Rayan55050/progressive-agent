# Architecture

Progressive Agent is a personal AI agent with a Telegram interface. It is inspired by OpenClaw (skills as Markdown, SOUL system) and ZeroClaw (Builder pattern, dual dispatcher, reliable wrapper).

This document describes the internal architecture in full detail.

---

## Table of Contents

1. [High-Level Data Flow](#high-level-data-flow)
2. [Agent Loop](#agent-loop)
3. [Builder Pattern](#builder-pattern)
4. [LLM Provider & Fallback Chain](#llm-provider--fallback-chain)
5. [Dispatcher](#dispatcher)
6. [Tool System](#tool-system)
7. [Skill System](#skill-system)
8. [Memory System](#memory-system)
9. [Soul System](#soul-system)
10. [Monitor System](#monitor-system)
11. [Channel Layer](#channel-layer)
12. [Configuration](#configuration)
13. [Directory Structure](#directory-structure)

---

## High-Level Data Flow

```
User (Telegram)
     |
     v
TelegramChannel (aiogram 3)
     |
     v
asyncio.Queue<IncomingMessage>        APScheduler
     |                                  |
     v                            +-----+-----+
  Agent.process()                 | Monitors   |
     |                            | (Crypto,   |
     +---> Memory.search()        |  Email,    |
     |     (hybrid recall)        |  Twitch,   |
     |                            |  YouTube,  |
     +---> Soul files             |  NewsRadar,|
     |     (system prompt)        |  Proxy,    |
     |                            |  Heartbeat)|
     +---> Router.route()         +-----+------+
     |     (skill selection)            |
     |                                  v
     +---> Dispatcher.dispatch()  Telegram Push
     |     (LLM call)            Notifications
     |
     +---> Tool execution loop
     |     (up to 25 iterations)
     |
     +---> Memory.save()
     |     (conversation + facts)
     |
     v
TelegramChannel.send()
     |
     v
User (Telegram)
```

Every incoming message -- text, voice, photo, document, video note, or forwarded -- enters through `TelegramChannel`, gets pushed into a single `asyncio.Queue`, and is consumed by the Agent. The Agent runs the full pipeline (memory lookup, system prompt assembly, routing, LLM dispatch, tool call loop, memory save) and sends the response back through Telegram.

Background monitors run on APScheduler and push notifications directly to Telegram without going through the queue.

---

## Agent Loop

The core processing pipeline in `Agent.process()` (`src/core/agent.py`):

```
1. Stranger check       -- Non-owner users get troll mode (no tools, no memory)
2. Load memories        -- Hybrid search for relevant past context
3. Build system prompt  -- Tool preamble + self-map + soul + memories + AGENTS.md learnings
4. Route                -- Match skill by keywords, select model
5. Append skill         -- Inject matched skill instructions into system prompt
6. Build messages       -- Sanitized conversation history + new user message
7. Dispatch with tools  -- LLM call loop (up to 25 iterations)
   a. Send to LLM via Dispatcher
   b. If tool_calls returned -> execute each tool -> append results -> loop
   c. If no tool_calls -> return text response
   d. Loop detection: 3 consecutive failures of same tool -> inject hint
8. Update history       -- Save full dispatch chain (including tool_use/tool_result)
9. Save to memory       -- Persist conversation exchange
10. Context compaction   -- Fire-and-forget: summarize old messages at 80% capacity
11. Fact extraction      -- Every 3 exchanges: extract structured facts via cheap LLM
12. Return response
```

Key implementation details:

- **History sanitization**: Before sending to the LLM, orphaned `tool_use`/`tool_result` pairs are stripped to prevent "unexpected tool_use_id" errors when the deque trims old messages.
- **Progress callbacks**: The caller receives real-time events (`thinking`, `routed`, `tool_start`, `tool_done`, `tool_progress`, `done`) to update the user on long-running operations.
- **Loop detection**: If the same dominant tool fails 3 iterations in a row, a system hint is injected telling the LLM to try a different approach.
- **Cheap LLM for internal tasks**: Summarization and fact extraction use the cheapest available provider (Mistral free > Cloudflare free > OpenAI > main) to avoid wasting tokens.

---

## Builder Pattern

The Agent is constructed using a fluent Builder pattern:

```python
agent = (
    Agent.builder()
    .provider(provider)           # LLMProvider (required)
    .memory(memory_manager)       # MemoryManager (optional)
    .tools(tool_registry)         # ToolRegistry (optional, defaults to empty)
    .soul_path("soul")            # Path to soul/ directory
    .skills(skill_registry)       # SkillRegistry (optional)
    .config(app_config)           # AppConfig (optional)
    .router(router)               # Router (optional, auto-built from config)
    .dispatcher(dispatcher)       # Dispatcher (optional, defaults to NativeDispatcher)
    .cost_tracker(cost_tracker)   # CostTracker (optional)
    .build()
)
```

This keeps the Agent constructor clean while allowing flexible composition of dependencies. Each setter returns `self` for chaining. The `build()` method validates that required dependencies (provider) are present and applies defaults for optional ones.

---

## LLM Provider & Fallback Chain

### Provider Protocol

Every LLM provider implements `LLMProvider` (`src/core/llm.py`):

```python
class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def capabilities(self) -> ProviderCapabilities: ...
    async def complete(self, messages, tools=None, stream=False, system=None) -> LLMResponse: ...
    async def stream(self, messages, tools=None, system=None) -> AsyncIterator[StreamChunk]: ...
```

Supporting data classes:

```python
@dataclass
class ProviderCapabilities:
    supports_tools: bool = False
    supports_vision: bool = False
    supports_streaming: bool = False
    max_context_tokens: int = 0
    max_output_tokens: int = 0

@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
```

### Implemented Providers

| # | Provider | Class | API | Cost | Notes |
|---|----------|-------|-----|------|-------|
| 1 | Claude Proxy | `ClaudeSubscriptionProvider` | OpenAI-compatible local proxy | Free (subscription) | Primary when PC is on |
| 2 | Gemini | `GeminiProvider` | Google AI Studio (OpenAI-compat) | Free (15 RPM) | Multimodal, 1M context |
| 3 | Mistral | `MistralProvider` | Mistral AI native SDK | Free (1B tokens/mo) | 1 RPS limit |
| 4 | Cloudflare | `CloudflareAIProvider` | Workers AI (OpenAI-compat) | Free (10K/day) | Llama 3.3 70B |
| 5 | OpenAI | `OpenAIProvider` | OpenAI API | Paid | GPT-5.2, fast |
| 6 | Claude API | `ClaudeAPIProvider` | Anthropic API | Paid | Emergency fallback |

`GeminiProvider` and `CloudflareAIProvider` extend `OpenAIProvider` since they use OpenAI-compatible endpoints.

### FallbackProvider

`FallbackProvider` wraps a primary provider and a list of fallbacks:

```python
provider = FallbackProvider(
    primary=ClaudeSubscriptionProvider(...),
    fallbacks=[
        GeminiProvider(...),
        MistralProvider(...),
        CloudflareAIProvider(...),
        OpenAIProvider(...),
        ClaudeAPIProvider(...),
    ],
    auto_recovery=True,
)
```

Behavior:
- Tries the current provider first.
- On proxy/connection/auth errors, tries the next fallback in order.
- After 3 consecutive failures of the primary, switches the current provider to the first fallback.
- Auto-recovery: stays on the fallback that succeeded (does not immediately retry primary).
- Non-proxy errors (invalid input, rate limits on non-proxy providers) are re-raised, not caught.

### Provider Factory

`create_provider()` builds the appropriate provider based on available API keys:

```python
provider = create_provider(
    proxy_url=config.claude_proxy_url,
    api_key=config.anthropic_api_key,
    mistral_api_key=config.mistral_api_key,
    openai_api_key=config.openai_api_key,
    # ... more keys
)
```

If multiple keys are provided, it builds a `FallbackProvider`. If only one is available, it returns a single provider.

---

## Dispatcher

The Dispatcher translates between the Agent's internal format and the LLM provider's specific API format for tool calling.

### Dispatcher Protocol

```python
class Dispatcher(Protocol):
    async def dispatch(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        provider: LLMProvider,
        system: str | None = None,
    ) -> DispatchResult: ...
```

### NativeDispatcher (default)

For providers with native function calling (Claude, GPT, Gemini, Mistral):
- Passes tool definitions as JSON schema directly to the provider.
- Parses `tool_use` blocks from the response into `ToolCall` objects.
- This is the preferred dispatcher.

### XmlDispatcher (fallback)

For providers without native function calling:
- Injects XML tool call instructions into the system prompt.
- Parses `<tool_call>` XML blocks from the response text.
- Uses regex: `<tool_call><tool_name>...</tool_name><arguments>...</arguments></tool_call>`.

### DispatchResult

```python
@dataclass
class DispatchResult:
    response_text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_response: LLMResponse | None = None

@dataclass
class ToolCall:
    tool_name: str
    arguments: dict = field(default_factory=dict)
    call_id: str = ""
```

---

## Tool System

### Tool Protocol

Every tool implements this protocol (`src/core/tools.py`):

```python
class Tool(Protocol):
    @property
    def definition(self) -> ToolDefinition: ...
    async def execute(self, **kwargs) -> ToolResult: ...
```

### Core Data Classes

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)

@dataclass
class ToolParameter:
    name: str
    type: str          # "string", "integer", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None

@dataclass
class ToolResult:
    success: bool
    data: Any = None
    error: str | None = None
```

`ToolDefinition.to_anthropic_schema()` converts the definition to Anthropic API format with `name`, `description`, and `input_schema` (JSON Schema).

### ToolRegistry

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None       # Add tool
    def get(self, name: str) -> Tool | None       # Get by name
    def list_tools(self) -> list[ToolDefinition]  # All definitions
    def to_anthropic_tools(self) -> list[dict]    # All in API format
    async def execute(self, name, **kwargs) -> ToolResult  # Execute by name
```

The registry handles name resolution including stripping `proxy_` prefixes that some proxies add to tool names.

### Always-Available Tools

These tools are always available regardless of the active skill:

```python
_ALWAYS_AVAILABLE_TOOLS = {
    "file_search", "file_read", "file_list", "file_write",
    "file_delete", "file_send", "file_open", "file_pdf", "file_copy",
    "cli_exec", "git", "agent_control",
    "qr_code", "clipboard", "system", "media_download", "screenshot",
    "skill_manager", "goal", "multi_agent",
}
```

In practice, ALL registered tools are sent to the LLM in every request. Skills provide instructions (injected into the system prompt) that guide tool selection, but they do not restrict tool visibility.

### Tool Categories

| Category | Tools | API Keys Required |
|----------|-------|-------------------|
| File System | file_search, file_read, file_list, file_write, file_delete, file_send, file_open, file_pdf, file_copy | None |
| Shell | cli_exec | None |
| Search | web_search, web_reader, web_extract, web_research | Tavily, Jina, SerpApi, Firecrawl |
| Communication | email_inbox, email_read, email_compose | Gmail OAuth |
| Finance | monobank_balance, monobank_transactions, monobank_rates, exchange_rates, finnhub | Monobank, Finnhub |
| Subscriptions | subscription_add, subscription_list, subscription_remove | None |
| Crypto/DeFi | coingecko, defi_llama, dex_screener, fear_greed | None |
| Media | tts, image_gen, bg_remove, media_download, diagram, shazam, audio_capture | OpenAI (for DALL-E/TTS) |
| Knowledge | wikipedia, tmdb, hackernews, reddit, github | TMDB |
| Productivity | weather, deepl, qr_code, clipboard, screenshot, ocr, system, exif_reader | DeepL |
| Ukraine | novaposhta, alerts_ua, prozorro, datagov, ukrpravda | NovaPoshta, AlertsUA |
| Agent | agent_control, git, skill_manager, self_improve, goal, multi_agent | None |
| Speech | stt (faster-whisper, local) | None |
| Data | csv_analyst, pdf_swiss_knife, speedtest | None |
| Browser | browser_open, browser_action, browser_history, browser_bookmarks, browser_close | None (Playwright) |
| Notes | obsidian_note, obsidian_search, obsidian_daily, obsidian_list | None (local vault) |
| Twitch | twitch_status | Twitch Client ID/Secret |
| YouTube | youtube_search, youtube_info, youtube_summary, youtube_subscriptions, youtube_liked | YouTube API Key + OAuth |
| Scheduler | scheduler_add, scheduler_list, scheduler_remove | None |
| Contact | contact | None |

---

## Skill System

Skills are Markdown files that provide domain-specific instructions to the LLM. They are **not code** -- they are prompt injections that guide the LLM's behavior when a specific domain is detected.

### Skill File Format

Each skill lives in `skills/<skill_name>/SKILL.md` with YAML frontmatter:

```markdown
---
name: finance
description: "Finance: Monobank, subscriptions, exchange rates, markets"
tools:
  - monobank_balance
  - monobank_transactions
  - exchange_rates
  - subscription_list
trigger_keywords:
  - balance
  - transactions
  - exchange rate
  - stock
  - subscription
---

# Finance

## Monobank (primary tool)

You have direct access to the owner's Monobank API. Use it FIRST for financial queries.

### When to use which tool:
- "Balance?" -> `monobank_balance`
- "Transactions?" -> `monobank_transactions` (days=3-7)
- "USD rate?" -> `exchange_rates` (PrivatBank + NBU)

## Rules
1. monobank = first source for balance/transactions
2. exchange_rates = first source for currency rates
3. Do not show IBANs or full card numbers in responses
```

### Loading Pipeline

1. `SkillLoader` (`src/skills/loader.py`) scans `skills/*/SKILL.md` files.
2. Parses YAML frontmatter (name, description, tools, trigger_keywords) and Markdown body (instructions).
3. `SkillRegistry` (`src/skills/registry.py`) stores loaded skills in a dict, supports hot-reload.
4. `SkillManagerTool` allows runtime CRUD operations on skills (create, delete, reload).

### Routing

The `Router` (`src/core/router.py`) matches incoming messages to skills:

1. **Keyword matching**: Check if any `trigger_keywords` appear in the message. Scoring: 1 match = 0.5, 2 matches = 0.7, 3+ matches = 0.9.
2. **LLM classification** (stub): Falls back to no-skill routing with default model.
3. **Model selection**: Currently always returns `default_model` (multi-model routing is prepared but not active).

When a skill matches, its instructions are appended to the system prompt:

```
[Tool Preamble] + [Self-Map] + [Soul Files] + [Memories] + [AGENTS.md]
---
# Active Skill: finance
[Skill Instructions from SKILL.md body]
```

---

## Memory System

The memory system (`src/memory/`) provides persistent, searchable storage for conversation history and extracted facts.

### Components

```
MemoryManager (facade)
    |
    +-- SQLiteStore          -- CRUD on `memories` table
    +-- EmbeddingGenerator   -- fastembed (local ONNX, no API key)
    +-- VectorSearch         -- sqlite-vec extension (cosine distance)
    +-- KeywordSearch        -- SQLite FTS5 (BM25 scoring)
    +-- HybridSearch         -- Combines all four signals
```

### Database Schema

Single SQLite database (`data/memory.db`):

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,          -- UUID4
    content TEXT NOT NULL,
    type TEXT NOT NULL,            -- "conversation", "fact", "preference", "task"
    importance REAL DEFAULT 0.5,   -- 0.0 to 1.0
    embedding BLOB,                -- Vector (float32 array, serialized)
    created_at TIMESTAMP,
    accessed_at TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    metadata JSON                  -- {"user_id", "channel", "source", ...}
);

-- Vector search index (sqlite-vec extension)
CREATE VIRTUAL TABLE vec_memories USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[384]           -- 384-dim from paraphrase-multilingual-MiniLM-L12-v2
);

-- Full-text search index
CREATE VIRTUAL TABLE memories_fts USING fts5(
    id,
    content,
    type
);
```

### Hybrid Search Algorithm

`HybridSearch.search()` combines four signals with fixed weights:

```
Combined Score = 0.4 * vector_similarity
               + 0.3 * keyword_score
               + 0.2 * temporal_decay
               + 0.1 * importance
```

Steps:
1. Generate query embedding via fastembed (local, no API).
2. **Vector search**: sqlite-vec cosine distance, normalized to [0,1] via `similarity = 1 - distance/2`.
3. **Keyword search**: FTS5 BM25 scores, min-max normalized to [0,1].
4. **Temporal decay**: `exp(-0.01 * days_since_last_access)` -- recent memories score higher.
5. **Importance**: Raw importance value (0.0-1.0).
6. Merge all candidate IDs, compute combined score, sort descending, return top-K.

### Embedding Model

- Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Dimensions: 384
- Runtime: fastembed (ONNX Runtime, no PyTorch, no API key)
- Supports: Russian, Ukrainian, English, and 50+ other languages

### Memory Lifecycle

1. **Save**: Every conversation exchange (`User: ... + Assistant: ...`) is saved as type `conversation` with importance 0.5.
2. **Fact extraction**: Every 3 exchanges, a cheap LLM extracts structured facts and saves them as type `fact` with importance 0.75.
3. **Context compaction**: When history reaches 80% of max capacity, oldest 60% of messages are summarized into a compact summary.
4. **Cleanup**: Memories older than 90 days with importance below 0.3 are deleted.
5. **Orphan purging**: At startup, orphaned entries in vector/FTS indexes (with no matching store entry) are removed.

---

## Soul System

The soul system defines the agent's personality, owner profile, and behavioral rules. All files live in the `soul/` directory and are loaded at agent initialization.

### Core Files

| File | Purpose |
|------|---------|
| `soul/SOUL.md` | Agent personality, communication style, language preferences |
| `soul/OWNER.md` | Owner profile (auto-filled): name, city, interests, tech stack |
| `soul/RULES.md` | Behavioral rules: what to do, what not to do, response format |
| `soul/CONTACTS.md` | Contact book (managed via ContactTool at runtime) |

### Trait Files

`soul/traits/*.md` files are loaded in sorted order (by filename). They provide additional behavioral rules, such as action rules for specific scenarios.

Example: `soul/traits/00_action_rules.md` might contain rules like "when user says X, always do Y".

### System Prompt Assembly

The full system prompt is assembled in this order:

```
1. Tool Preamble (prompts/TOOLS.md)    -- "Call tools, don't narrate"
2. Self-Map (prompts/SELF_MAP.md)       -- Project structure awareness
3. Soul (SOUL.md + OWNER.md + RULES.md + CONTACTS.md + traits/*.md)
4. Relevant Memories                     -- From hybrid search
5. AGENTS.md learnings                   -- Self-improvement knowledge base
---
6. Active Skill instructions             -- If a skill matched
```

Tool instructions go FIRST (before personality) to ensure the LLM prioritizes tool use over conversational brevity.

### Stranger Mode

Non-owner users (not in `allowed_users` whitelist) get a separate system prompt (`STRANGER_SYSTEM_PROMPT`) that:
- Presents the bot as an autonomous digital entity.
- Allows friendly but trolling conversation on general topics.
- Blocks all tool execution, memory access, and skill routing.
- Never reveals owner information, tech stack, or API details.
- Rate-limited: 20 messages per 10 minutes per stranger.

---

## Monitor System

Monitors are background jobs that run on APScheduler and push notifications to Telegram. Each monitor follows a common pattern.

### Monitor Pattern

```python
class SomeMonitor:
    def __init__(
        self,
        notify: Callable[[str, str], Coroutine],  # async (user_id, text) -> None
        user_id: str,                               # Owner's Telegram user ID
        # ... monitor-specific config
    ):
        self._notify = notify
        self._user_id = user_id
        # ... state

    async def check(self) -> None:
        """Called by APScheduler at configured intervals."""
        # 1. Fetch data (API call, RSS parse, etc.)
        # 2. Compare with previous state
        # 3. If something changed, notify
        if changed:
            await self._notify(self._user_id, message)
```

### Active Monitors

| Monitor | Trigger | Interval | Source |
|---------|---------|----------|--------|
| CryptoMonitor | interval | 2 min | CoinGecko (BTC price, $500 threshold) |
| SubscriptionMonitor | cron | Daily at 09:00 | Local JSON (3-day + 1-day + due reminders) |
| NewsRadarMonitor | interval | 4 hours | RSS + Reddit + HN + HuggingFace + Google News |
| TechRadarMonitor | interval | 6 hours | GitHub trending + HN + Reddit (curated) |
| ProxyMonitor | interval | 2 min | CLIProxyAPI health check + auto-restart |
| HeartbeatEngine | interval | 30 min | HEARTBEAT.md tasks (run through agent) |
| MorningBriefingMonitor | cron | Daily at 08:00 | Weather + email + crypto + subscriptions |
| GoalEngine | interval | 15 min | data/goals.json (long-running background goals) |
| EmailMonitor | interval | 1 min | Gmail API (new emails) |
| MonobankMonitor | interval | 3 min | Monobank API (new transactions) |
| TwitchMonitor | interval | 3 min | Twitch API (live notifications) |
| YouTubeMonitor | interval | 30 min | YouTube Data API (new videos) |
| NovaPoshtaMonitor | interval | 30 min | Nova Poshta API (parcel status changes) |

### Scheduler

The `Scheduler` class (`src/core/scheduler.py`) wraps APScheduler's `AsyncIOScheduler`:

```python
scheduler = Scheduler(timezone="Europe/Kiev")
scheduler.start()

job_id = scheduler.add_job(
    func=monitor.check,
    trigger="interval",
    minutes=30,
    name="my_monitor",
)
```

Supports `cron`, `interval`, and `date` triggers. All jobs get UUID identifiers.

---

## Channel Layer

### Channel Protocol

```python
class Channel(Protocol):
    async def start(self, queue: asyncio.Queue[IncomingMessage]) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, message: OutgoingMessage) -> str: ...
    async def send_file(self, user_id: str, file_path: Path, caption: str = "") -> None: ...
    async def draft_update(self, user_id: str, message_id: str, text: str) -> None: ...
    async def health_check(self) -> bool: ...
```

### IncomingMessage

```python
@dataclass
class IncomingMessage:
    user_id: str
    text: str | None = None
    voice_file_path: Path | None = None
    audio_file_path: Path | None = None
    document_file_path: Path | None = None
    document_file_name: str | None = None
    photo_file_path: Path | None = None
    video_note_file_path: Path | None = None
    image_base64: str | None = None
    image_media_type: str | None = None
    forward_info: str | None = None
    channel: str = "telegram"
    timestamp: datetime = field(default_factory=datetime.now)
    message_id: str = ""
    is_owner: bool = True
    raw: Any = None
```

### TelegramChannel

The primary (and currently only) channel implementation. Built with aiogram 3.

Features:
- Text, voice, audio, photo, document, video note handling.
- Voice-to-text via faster-whisper (local STT).
- Photo encoding to base64 for Claude Vision.
- Document parsing (PDF, DOCX, XLSX, etc.).
- Draft updates (progressive message editing during generation).
- Typing indicator (continuous "typing..." while agent works).
- File, audio, voice, and video note sending.
- Deny-by-default: only `allowed_users` get full access.

### Pipeline

```python
queue = asyncio.Queue()

# TelegramChannel pushes messages to queue
await telegram.start(queue)

# Message processor consumes from queue
while True:
    msg = await queue.get()
    response = await agent.process(msg, progress=callback)
    await telegram.send(OutgoingMessage(user_id=msg.user_id, text=response))
```

---

## Configuration

### TOML Configuration (`config/agent.toml`)

All non-secret settings are stored in TOML format:

```toml
[agent]
name = "Progressive Agent"
default_model = "claude-opus-4-6"
fallback_model = "claude-sonnet-4-5-20250929"
max_tokens = 16384
temperature = 0.7

[telegram]
allowed_users = [123456789]    # Telegram user IDs (whitelist)
streaming_chunk_size = 50

[memory]
db_path = "data/memory.db"
embedding_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
embedding_dimensions = 384
max_context_memories = 10
temporal_decay_lambda = 0.01

[costs]
daily_limit_usd = 5.0
monthly_limit_usd = 50.0
warning_threshold = 0.8

[search]
provider = "tavily"
max_results = 5

[weather]
default_city = ""  # auto-detected from IP or set during onboarding

[scheduler]
timezone = "Europe/Kiev"
```

Additional sections: `[email]`, `[crypto]`, `[monobank]`, `[obsidian]`, `[twitch]`, `[youtube]`, `[news_radar]`, `[files]`, `[tts]`, `[morning_briefing]`, `[heartbeat]`, `[novaposhta]`.

### Environment Variables (`.env`)

All secrets are stored in `.env` (never committed):

```bash
# LLM Providers
CLAUDE_PROXY_URL=http://127.0.0.1:8317/v1
ANTHROPIC_API_KEY=sk-ant-xxx          # Fallback
MISTRAL_API_KEY=xxx                    # Free tier
OPENAI_API_KEY=sk-xxx                  # Paid fallback
GEMINI_API_KEY=xxx                     # Free tier
CLOUDFLARE_API_KEY=xxx                 # Free tier
CLOUDFLARE_ACCOUNT_ID=xxx

# Core
TELEGRAM_BOT_TOKEN=123456:ABC...

# Search (multi-provider)
TAVILY_API_KEY=tvly-xxx
TAVILY_API_KEYS=key1,key2,key3        # Auto-rotation pool
SERPAPI_API_KEY=xxx
JINA_API_KEY=xxx
FIRECRAWL_API_KEY=xxx

# Services
MONOBANK_API_TOKEN=xxx
TWITCH_CLIENT_ID=xxx
TWITCH_CLIENT_SECRET=xxx
YOUTUBE_API_KEY=xxx
DEEPL_API_KEY=xxx
FINNHUB_API_KEY=xxx
NOVAPOSHTA_API_KEY=xxx
ALERTS_UA_TOKEN=xxx
TMDB_API_KEY=xxx
```

### Config Loading

`load_config()` in `src/core/config.py`:
1. Loads `.env` via python-dotenv.
2. Loads TOML config via `tomllib`.
3. Builds Pydantic models for each section.
4. Reads secrets from environment variables.
5. Returns a fully populated `AppConfig` instance.

---

## Directory Structure

```
progressive-agent/
|
|-- config/
|   |-- agent.toml              # Main configuration (TOML)
|   +-- gmail_credentials.json  # Gmail OAuth credentials
|
|-- data/                        # Runtime data (git-ignored)
|   |-- memory.db               # SQLite database (memories + vectors + FTS)
|   |-- costs.db                # Cost tracking database
|   |-- agent.log               # Application log (rotating, 5MB)
|   +-- watchdog_state.json     # Watchdog health state
|
|-- docs/                        # Documentation
|   |-- ARCHITECTURE.md          # This file
|   |-- ROADMAP.md               # 21-module, 5-phase roadmap
|   +-- STATUS.md                # Current progress
|
|-- prompts/
|   |-- TOOLS.md                 # Tool use preamble (injected first in system prompt)
|   +-- SELF_MAP.md              # Self-awareness map
|
|-- skills/                      # Skill definitions (Markdown)
|   |-- finance/SKILL.md
|   |-- weather/SKILL.md
|   |-- youtube/SKILL.md
|   +-- ...
|
|-- soul/                        # Agent personality
|   |-- SOUL.md                  # Core personality
|   |-- OWNER.md                 # Owner profile
|   |-- RULES.md                 # Behavioral rules
|   |-- CONTACTS.md              # Contact book
|   +-- traits/                  # Additional behavioral traits
|       +-- 00_action_rules.md
|
|-- src/
|   |-- main.py                  # Entry point (initializes everything)
|   |-- watchdog.py              # Process supervisor with crash recovery
|   |
|   |-- core/
|   |   |-- agent.py             # Agent orchestrator (Builder pattern)
|   |   |-- llm.py               # LLM providers (6 implementations)
|   |   |-- dispatcher.py        # Native + XML dispatchers
|   |   |-- router.py            # Skill routing (keywords + LLM)
|   |   |-- config.py            # Configuration loading (TOML + .env)
|   |   |-- tools.py             # Tool protocol + ToolRegistry
|   |   |-- scheduler.py         # APScheduler wrapper
|   |   |-- cost_tracker.py      # API cost tracking
|   |   |-- heartbeat.py         # Autonomous task engine
|   |   |-- self_improve.py      # AGENTS.md self-improvement
|   |   |-- goals.py             # Long-running goal pursuit engine
|   |   +-- orchestrator.py      # Multi-agent parallel orchestrator
|   |
|   |-- channels/
|   |   |-- base.py              # Channel protocol + data classes
|   |   +-- telegram.py          # Telegram implementation (aiogram 3)
|   |
|   |-- memory/
|   |   |-- models.py            # Memory dataclass
|   |   |-- manager.py           # MemoryManager (facade)
|   |   |-- sqlite_store.py      # SQLite CRUD
|   |   |-- embeddings.py        # fastembed (local ONNX)
|   |   |-- vector_search.py     # sqlite-vec cosine search
|   |   |-- keyword_search.py    # FTS5 BM25 search
|   |   +-- hybrid.py            # Hybrid scoring (4 signals)
|   |
|   |-- skills/
|   |   |-- loader.py            # YAML + Markdown parser
|   |   +-- registry.py          # Skill registry with hot-reload
|   |
|   |-- tools/                   # Tool implementations (60+)
|   |   |-- search_tool.py       # Web search (Tavily + SerpApi + Jina)
|   |   |-- cli_tool.py          # Shell execution (with security guards)
|   |   |-- file_tool.py         # File system operations (9 tools)
|   |   |-- email_tool.py        # Gmail (OAuth2)
|   |   |-- weather_tool.py      # Open-Meteo + wttr.in
|   |   |-- browser_tool.py      # Playwright browser automation
|   |   +-- ...                  # 50+ more tools
|   |
|   +-- monitors/                # Background monitor jobs
|       |-- crypto_monitor.py
|       |-- news_radar_monitor.py
|       |-- subscription_monitor.py
|       +-- ...
|
|-- tests/                       # Test suite
|   |-- test_memory.py
|   |-- test_telegram.py
|   +-- ...
|
|-- scripts/                     # Utility scripts
|-- CLAUDE.md                    # Project instructions for Claude Code
|-- AGENTS.md                    # Self-improvement learnings
|-- HEARTBEAT.md                 # Autonomous tasks
|-- pyproject.toml               # Dependencies + build config
|-- start_silent.vbs             # Windows silent autostart
+-- .env.example                 # Environment variable template
```
