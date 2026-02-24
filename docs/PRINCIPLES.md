# Engineering Principles

## Tools, Not Wrappers

Every tool must provide real value through a real API or real system access. A tool that just calls web search with a different prompt is not a tool — it's a wrapper. If a skill only has `web_search` available, it's useless. Tools should connect to actual services: CoinGecko for crypto prices, Gmail for email, filesystem for files, TMDB for movies.

## LLM-Native Design

The LLM is the brain, not a text generator bolted onto a framework. Skills are markdown instructions injected into the system prompt — not Python code with if/else trees. The router picks skills based on the message. The dispatcher handles tool calls natively. Let the LLM decide what to do; give it good tools and clear instructions.

## Fail Gracefully

Every external call can fail. Every API has rate limits. Every network request can timeout. The agent must handle all of this without crashing or confusing the user. Fallback providers for LLM calls. Retries with exponential backoff. Sensible defaults when services are unavailable. The user should never see a stack trace.

## Zero-Config Where Possible

The agent should work out of the box with minimal setup. Auto-create directories. Auto-detect system settings. Provide sensible defaults for everything. The only mandatory config should be API keys — and even then, the fallback chain means the agent degrades gracefully with just one provider configured.

## Convention Over Configuration

File-based skills in `skills/*/SKILL.md`. Tools in `src/tools/*_tool.py`. Monitors in `src/monitors/*_monitor.py`. Config in `config/*.toml`. Follow the pattern, skip the boilerplate. New contributors should know where to put things without reading a guide.

## Async Everything

The entire codebase is async. No blocking calls. No sync-in-async hacks. One event loop, one message queue, clean concurrency. If a tool needs to do I/O, it uses `aiohttp`, `aiofiles`, or an async library. No exceptions.

## Prefer Specialized Over Generic

When the user asks about crypto, use CoinGecko — don't web search. When they ask about a movie, use TMDB. Specialized tools are faster, more accurate, and more reliable. Web search is the fallback of last resort, not the default approach.

## Test What Matters

Every tool, every monitor, every core module has tests. Not for coverage metrics — for confidence that changes don't break what's already working. Tests should be fast, deterministic, and meaningful. A failing test should point directly at the problem.
