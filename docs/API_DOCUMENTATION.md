# API Documentation

This guide explains how to create custom tools and skills for Progressive Agent.

---

## Table of Contents

1. [Tool Protocol](#tool-protocol)
2. [Core Data Classes](#core-data-classes)
3. [Creating a Tool (Step by Step)](#creating-a-tool-step-by-step)
4. [Registering Tools](#registering-tools)
5. [Tool Best Practices](#tool-best-practices)
6. [Creating a Skill](#creating-a-skill)
7. [Skill Best Practices](#skill-best-practices)
8. [LLM Provider Protocol](#llm-provider-protocol)
9. [Monitor Pattern](#monitor-pattern)

---

## Tool Protocol

Every tool must satisfy the `Tool` protocol defined in `src/core/tools.py`:

```python
from src.core.tools import Tool, ToolDefinition, ToolParameter, ToolResult

class Tool(Protocol):
    @property
    def definition(self) -> ToolDefinition:
        """Return the tool's schema (name, description, parameters)."""
        ...

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...
```

The `definition` property tells the LLM what the tool does and what parameters it accepts. The `execute` method does the actual work.

---

## Core Data Classes

### ToolDefinition

Describes the tool for the LLM. Converted to JSON Schema via `to_anthropic_schema()`.

```python
@dataclass
class ToolDefinition:
    name: str                                    # Unique tool identifier (snake_case)
    description: str                             # What the tool does (shown to LLM)
    parameters: list[ToolParameter] = field(default_factory=list)
```

### ToolParameter

Describes a single parameter the tool accepts.

```python
@dataclass
class ToolParameter:
    name: str                    # Parameter name
    type: str                    # JSON Schema type: "string", "integer", "boolean",
                                 #                   "number", "array", "object"
    description: str             # What the parameter does (shown to LLM)
    required: bool = True        # Whether the LLM must provide this parameter
    default: Any = None          # Default value (informational, not enforced)
    enum: list[str] | None = None  # Allowed values (shown to LLM as choices)
```

### ToolResult

Returned by every tool execution.

```python
@dataclass
class ToolResult:
    success: bool              # True if the tool executed without errors
    data: Any = None           # Result data (string, dict, list, etc.)
    error: str | None = None   # Error message if success=False
```

The Agent formats `ToolResult` for the LLM:
- On success: converts `data` to string (with special formatting for search results).
- On failure: returns `"Error: {error_message}"`.
- Results longer than 30,000 characters are truncated.

---

## Creating a Tool (Step by Step)

### Example: IP Address Lookup Tool

Create a new file `src/tools/ip_tool.py`:

```python
"""
IP Address Lookup Tool -- get public IP and geolocation.

Free, no API key required.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class IPLookupTool:
    """Get public IP address and geolocation info."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ip_lookup",
            description=(
                "Get the current public IP address and its geolocation "
                "(country, city, ISP). Free, no API key required."
            ),
            parameters=[
                ToolParameter(
                    name="ip",
                    type="string",
                    description="IP address to look up. Leave empty for current public IP.",
                    required=False,
                ),
            ],
        )

    async def execute(self, ip: str | None = None, **kwargs: Any) -> ToolResult:
        """Look up IP address geolocation."""
        target = ip or ""
        url = f"http://ip-api.com/json/{target}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        return ToolResult(
                            success=False,
                            error=f"API returned HTTP {resp.status}",
                        )
                    data = await resp.json()

            if data.get("status") == "fail":
                return ToolResult(
                    success=False,
                    error=data.get("message", "Lookup failed"),
                )

            result = (
                f"IP: {data.get('query', 'unknown')}\n"
                f"Country: {data.get('country', 'unknown')}\n"
                f"City: {data.get('city', 'unknown')}\n"
                f"ISP: {data.get('isp', 'unknown')}\n"
                f"Lat/Lon: {data.get('lat')}, {data.get('lon')}"
            )

            return ToolResult(success=True, data=result)

        except aiohttp.ClientError as exc:
            logger.error("IP lookup failed: %s", exc)
            return ToolResult(success=False, error=f"Network error: {exc}")
        except Exception as exc:
            logger.error("IP lookup unexpected error: %s", exc)
            return ToolResult(success=False, error=str(exc))
```

### Key Points

1. **`definition` is a property**, not a method. Return a `ToolDefinition` instance.
2. **`execute` is async** and accepts `**kwargs`. The LLM sends parameters as keyword arguments.
3. **Always return `ToolResult`**. Never raise exceptions from `execute` -- catch them and return `ToolResult(success=False, error=...)`.
4. **Use `aiohttp`** for HTTP requests (the project is fully async).
5. **Log with `logging`**, never use `print`.
6. **Accept `**kwargs`** in execute to be forward-compatible (the framework may pass extra fields).

---

## Registering Tools

Tools are registered in `src/main.py` during startup:

```python
from src.tools.ip_tool import IPLookupTool

# In the main() function, after tool_registry = ToolRegistry():
tool_registry.register(IPLookupTool())
logger.info("IP lookup tool registered")
```

That is all. Once registered, the tool appears in every LLM request and can be called by the model.

### Conditional Registration

If the tool requires an API key:

```python
if config.some_api_key:
    tool_registry.register(SomeTool(api_key=config.some_api_key))
    logger.info("Some tool registered")
else:
    logger.warning("Some tool not configured -- set SOME_API_KEY in .env")
```

### Service Pattern

If multiple tools share state (like a database connection or API client), use a service object:

```python
class MyService:
    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def fetch_data(self, query: str) -> dict: ...

class MySearchTool:
    def __init__(self, service: MyService):
        self._service = service
    # ...

class MyDetailTool:
    def __init__(self, service: MyService):
        self._service = service
    # ...

# Registration:
service = MyService(api_key=config.my_api_key)
if service.available:
    tool_registry.register(MySearchTool(service))
    tool_registry.register(MyDetailTool(service))
```

---

## Tool Best Practices

### Naming

- Use `snake_case` for tool names: `weather`, `web_search`, `monobank_balance`.
- Keep names short and descriptive.
- Prefix related tools: `monobank_balance`, `monobank_transactions`, `monobank_rates`.

### Description

- Write clear, concise descriptions that help the LLM decide when to use the tool.
- Include what API/service it uses and whether it requires an API key.
- Mention if it is free or paid.

```python
description=(
    "Get current weather and 3-day forecast for a city. "
    "Free, no API key. Supports any city worldwide."
)
```

### Parameters

- Make parameters optional when a sensible default exists.
- Use `enum` for fixed choices:

```python
ToolParameter(
    name="action",
    type="string",
    description="What to do",
    required=True,
    enum=["search", "details", "trending"],
)
```

### Error Handling

- **Never raise exceptions** from `execute`. Always catch and return `ToolResult(success=False, error=...)`.
- Provide meaningful error messages that help the LLM try a different approach.
- Set reasonable timeouts on network requests (8-15 seconds).

### Result Formatting

- Return human-readable strings when possible (the LLM reads the result).
- For structured data, return dicts or lists -- the Agent will serialize them.
- Keep results under 30,000 characters (results are truncated beyond that).

---

## Creating a Skill

Skills are Markdown files that inject domain-specific instructions into the system prompt when triggered by keywords.

### Skill File Structure

Create `skills/<skill_name>/SKILL.md`:

```markdown
---
name: cooking
description: "Cooking recipes and meal planning"
tools:
  - web_search
  - web_reader
trigger_keywords:
  - recipe
  - cook
  - meal
  - dinner
  - lunch
  - breakfast
  - ingredients
---

# Cooking Assistant

You are a cooking expert. When the user asks about food:

## How to respond:
1. If they want a specific recipe, search for it and provide step-by-step instructions.
2. If they have ingredients, suggest what they can cook.
3. Always include cooking time, servings, and difficulty level.

## Format:
- Recipe name (bold)
- Prep time / Cook time / Servings
- Ingredients list
- Step-by-step instructions
- Tips

## Rules:
- Prefer simple, practical recipes
- Include metric and imperial measurements
- Mention common substitutions for hard-to-find ingredients
```

### YAML Frontmatter Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique skill identifier (used internally) |
| `description` | string | Yes | Human-readable description |
| `tools` | list[string] | Yes | Tool names this skill typically uses |
| `trigger_keywords` | list[string] | Yes | Keywords that activate this skill |

### How Skills Work

1. User sends a message.
2. `Router` checks if any `trigger_keywords` appear in the message.
3. If matched, the skill's Markdown body (everything after the YAML frontmatter) is appended to the system prompt.
4. The LLM now has domain-specific instructions guiding its behavior and tool usage.

Skills do NOT restrict which tools are available. All registered tools are always visible to the LLM. The skill instructions merely guide the LLM on which tools to prefer and how to format responses.

### Registering a Skill

Skills are auto-discovered. Just create the file and either:
- Restart the bot, or
- Use the `skill_manager` tool to hot-reload: the LLM can call `skill_manager action="reload"`.

---

## Skill Best Practices

1. **Write clear, actionable instructions**. The LLM follows them literally.
2. **Specify which tool to use for which scenario**. Example: "For currency rates, use `exchange_rates` first, not `web_search`."
3. **Include response format guidelines**. The LLM will follow the format you specify.
4. **Use specific trigger keywords**. Avoid overly generic words that would match unrelated queries.
5. **List only the tools the skill actually needs** in the `tools` field. This is informational and helps with documentation.
6. **Keep instructions concise**. Every character counts toward the context window.

---

## LLM Provider Protocol

To add a new LLM provider, implement the `LLMProvider` protocol:

```python
from src.core.llm import LLMProvider, LLMResponse, StreamChunk, ProviderCapabilities, TokenUsage

class MyProvider:
    @property
    def name(self) -> str:
        return "my-provider"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tools=True,
            supports_vision=False,
            supports_streaming=True,
            max_context_tokens=128_000,
            max_output_tokens=4096,
        )

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
        system: str | None = None,
    ) -> LLMResponse:
        # Convert Anthropic-style messages to your provider's format
        # Call the API
        # Parse the response into LLMResponse
        return LLMResponse(
            content="response text",
            tool_calls=[{"id": "...", "name": "tool_name", "input": {...}}],
            usage=TokenUsage(input_tokens=100, output_tokens=50),
            model="model-name",
        )

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        # Stream response chunks
        yield StreamChunk(text="partial text")
        yield StreamChunk(tool_call={"id": "...", "name": "...", "input": {...}})
        yield StreamChunk(done=True)
```

Key requirements:
- Messages come in Anthropic format (role + content, where content can be a string or a list of blocks including `tool_use` and `tool_result`).
- Tool definitions come in Anthropic format (`name`, `description`, `input_schema`).
- Tool calls in `LLMResponse.tool_calls` must have `id`, `name`, and `input` fields.
- The provider should handle its own message format conversion internally.

If your provider uses an OpenAI-compatible endpoint, extend `OpenAIProvider` instead of implementing from scratch (see `GeminiProvider` and `CloudflareAIProvider` for examples).

---

## Monitor Pattern

To create a background monitor:

```python
"""My custom monitor."""

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class MyMonitor:
    def __init__(
        self,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        user_id: str,
    ) -> None:
        self._notify = notify
        self._user_id = user_id
        self._previous_state: dict | None = None

    async def check(self) -> None:
        """Called by APScheduler at configured intervals."""
        try:
            current_state = await self._fetch_data()

            if self._previous_state is None:
                self._previous_state = current_state
                return

            changes = self._detect_changes(self._previous_state, current_state)
            self._previous_state = current_state

            if changes:
                message = self._format_notification(changes)
                await self._notify(self._user_id, message)

        except Exception as exc:
            logger.error("MyMonitor check failed: %s", exc)

    async def _fetch_data(self) -> dict:
        """Fetch current data from API/source."""
        ...

    def _detect_changes(self, old: dict, new: dict) -> list:
        """Compare old and new state, return changes."""
        ...

    def _format_notification(self, changes: list) -> str:
        """Format changes into a notification message."""
        ...
```

Register in `src/main.py`:

```python
from src.monitors.my_monitor import MyMonitor

async def _my_notify(user_id: str, text: str) -> None:
    await telegram.send(OutgoingMessage(user_id=user_id, text=text))

my_monitor = MyMonitor(notify=_my_notify, user_id=monitor_user)
scheduler.add_job(
    my_monitor.check,
    trigger="interval",
    minutes=15,
    name="my_custom_check",
)
```
