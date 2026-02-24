# Frequently Asked Questions

## General

### What is Progressive Agent?

Progressive Agent is an open-source personal AI assistant that runs as a Telegram bot. It combines multiple LLM providers, local memory, and a growing set of tools to help you manage daily tasks -- from web search and file operations to crypto tracking, email management, and media downloads. It is designed for a single owner who wants a "second brain" that runs on their own machine.

### Is it free?

The software itself is free and open-source (MIT license). However, some features require API keys:

- **Completely free setup:** Use free-tier LLM providers (Gemini, Mistral, Cloudflare Workers AI) + free tools (CoinGecko, Wikipedia, exchange rates, local STT).
- **Recommended setup:** Claude subscription with proxy ($20/mo) or OpenAI API key (pay-per-use) for the best experience.
- **All API keys are optional.** The bot starts with whatever providers and tools you configure.

### Can I use it without Claude?

Yes. While Claude is the default primary provider, Progressive Agent supports a **6-level fallback chain** of LLM providers. You can run it with any combination:

- Google Gemini (free, 15 RPM)
- Mistral (free, 1 RPS)
- Cloudflare Workers AI (free, 10K neurons/day)
- OpenAI GPT (paid)
- Anthropic Claude API (paid)

Configure whichever providers you have keys for in `.env`. The bot will use whatever is available.

### Can I use it on Linux/Mac?

Yes. The project is cross-platform. It is developed on Windows but works on Linux and macOS. A few notes:

- **ffmpeg** must be installed for voice message transcription (available via apt, brew, etc.).
- **File paths** in `config/agent.toml` use forward slashes on all platforms.
- The Windows-specific autostart scripts (`start_silent.vbs`, `stop_agent.vbs`) are not needed on Linux/Mac -- use systemd, launchd, or screen instead.
- Browser tools assume Chrome/Chromium is installed.

### Is my data private?

Yes. Everything runs locally on your machine:

- **Memory** is stored in a local SQLite database (`data/memory.db`).
- **Embeddings** are generated locally using `fastembed` (no data sent to OpenAI for embeddings).
- **STT** uses `faster-whisper` running locally on CPU -- your voice messages are never sent to any cloud service.
- **Conversation history** stays in your local database.
- **No telemetry.** The bot does not phone home.

The only data that leaves your machine is what you explicitly send to LLM providers (your messages and tool results) and API calls to configured services (Telegram, search engines, etc.).

---

## Architecture

### What LLM models does it support?

Progressive Agent supports any OpenAI-compatible API endpoint plus native Anthropic and Mistral SDKs:

| Provider | Models | Tool Calling | Streaming |
|----------|--------|-------------|-----------|
| Claude (proxy) | Opus 4.6, Sonnet 4.5 | Yes | Yes |
| Claude API | All Claude models | Yes | Yes |
| OpenAI | GPT-4o, GPT-5, etc. | Yes | Yes |
| Google Gemini | Gemini 2.0 Flash | Yes | Yes |
| Mistral | Large, Medium, Small | Yes | Yes |
| Cloudflare | Llama 3.3 70B, etc. | Yes | Yes |

### How does the fallback chain work?

When the bot needs to call an LLM, it tries providers in order of priority. If a provider fails (network error, rate limit, API key issue), it automatically falls through to the next one:

1. Claude Proxy (local subscription) -- primary, zero marginal cost
2. Gemini Flash (free tier) -- fast, multimodal
3. Mistral Large (free tier) -- rate-limited but capable
4. Cloudflare Workers AI (free tier) -- Llama 3.3 70B
5. OpenAI (paid) -- reliable fallback
6. Claude API (paid) -- emergency fallback

This means the bot keeps working even if your primary provider goes down. Configure as many or as few as you want.

### What is the difference between tools and skills?

| | Tools | Skills |
|---|-------|--------|
| **What** | Python code that executes actions | Markdown files with LLM instructions |
| **Where** | `src/tools/*.py` | `skills/*/SKILL.md` |
| **Purpose** | Capabilities (API calls, file ops, system commands) | Context and behavior (how to use tools, response format) |
| **Example** | `web_search` tool calls the Tavily API | `web_search` skill teaches the LLM to formulate good queries and cite sources |

Tools provide the **what** (actions the bot can take). Skills provide the **how** (instructions for the LLM on when and how to use those tools effectively). You can have tools without skills, but skills without corresponding tools are limited to general LLM knowledge.

### How does memory work?

The bot uses a **hybrid memory system** built on SQLite:

1. **Vector search** -- Embeddings generated locally via `fastembed`, stored in `sqlite-vec`. Finds semantically similar memories.
2. **Keyword search** -- SQLite FTS5 full-text search. Finds exact keyword matches.
3. **Temporal decay** -- Recent memories rank higher. Importance score provides additional weighting.
4. **Hybrid ranking** -- Results from all three signals are merged and ranked to find the most relevant context.

Memories are automatically created from conversations and include types like `conversation`, `fact`, `preference`, and `task`. The bot also restores recent conversation history after restarts so it does not lose context.

### Can multiple users use it?

Progressive Agent is designed for a **single owner**. The `allowed_users` list in `config/agent.toml` defines who gets full access. Non-whitelisted users can message the bot, but they receive "troll mode" responses -- the bot is friendly and conversational but will not execute tools, access memory, or reveal any information about the owner.

You can add multiple user IDs to the whitelist, but the bot does not have per-user memory isolation or multi-tenant features. All whitelisted users share the same memory and tool access.

---

## Setup & Configuration

### How do I add a new tool?

1. Create `src/tools/your_tool.py`.
2. Implement the `Tool` protocol:
   ```python
   class YourTool:
       name = "your_tool"
       description = "What this tool does"

       @property
       def definition(self) -> ToolDefinition:
           return ToolDefinition(
               name=self.name,
               description=self.description,
               parameters=[
                   ToolParameter(name="query", type="string", description="...", required=True),
               ],
           )

       async def execute(self, **kwargs) -> ToolResult:
           # Your logic here
           return ToolResult(success=True, data="result")
   ```
3. Register the tool in `src/core/agent.py`.
4. Write tests in `tests/`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

### How do I add a new skill?

1. Create `skills/your_skill/SKILL.md`.
2. Write YAML frontmatter with metadata and Markdown instructions:
   ```markdown
   ---
   name: your_skill
   description: What this skill does
   tools:
     - tool_name_1
     - tool_name_2
   trigger_keywords:
     - keyword1
     - keyword2
   ---

   # Instructions for the LLM

   When the user asks about [topic], use [tool] to...
   ```
3. The skill is automatically loaded by the router on next restart.

### Can I use my own LLM provider?

Yes. Any provider that exposes an **OpenAI-compatible API** can be added. The `OpenAIProvider` class in `src/core/llm.py` handles the protocol. To add a custom provider:

1. Set the base URL and API key in `.env`.
2. Add a provider entry in the fallback chain configuration.
3. If the provider has a non-standard API, extend the `LLMProvider` protocol with a custom class.

Providers like LM Studio, Ollama, vLLM, and Text Generation Inference all expose OpenAI-compatible endpoints and work with minimal configuration.

### How do I update?

```bash
git pull origin main
uv sync
```

Then restart the bot. Database migrations (if any) are applied automatically on startup.

---

## Operations

### How do I check if the bot is healthy?

The bot sends a **startup notification** to the owner's Telegram with a status summary: LLM provider, loaded tools, active skills, running monitors, and restored history count.

At runtime, the **heartbeat engine** runs periodic health checks. You can also use the `agent_control` tool within the chat:
```
Check bot health
```

### How do I run the bot in the background?

**Windows:** Use the included `start_silent.vbs` script (runs invisibly, logs to `data/bot_startup.log`).

**Linux/Mac:**
```bash
# Using screen
screen -S agent python -m src.main

# Using systemd (create a service file)
# Using nohup
nohup python -m src.main > bot.log 2>&1 &
```

For crash recovery, use the **watchdog**:
```bash
python -m src.watchdog
```
It automatically restarts the bot on crashes with exponential backoff.

### How do I contribute?

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. In short:

1. Fork the repository.
2. Create a feature branch.
3. Make changes following the code style guidelines.
4. Write tests.
5. Submit a pull request.

All contributions are welcome -- tools, skills, bug fixes, documentation, and translations.
