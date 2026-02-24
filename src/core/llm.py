"""
LLM Provider abstraction layer.

Supports two providers:
1. ClaudeSubscriptionProvider (primary) — uses Claude Max subscription via CLI proxy
   (OpenAI-compatible endpoint from claude-max-api-proxy or CLIProxyAPI)
2. ClaudeAPIProvider (fallback) — uses Anthropic API key directly

The subscription provider is the default. API provider is only used if
explicitly configured or if the proxy is unavailable.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable

import anthropic
import openai
from mistralai import Mistral

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProviderCapabilities:
    """Capabilities of an LLM provider."""

    supports_tools: bool = False
    supports_vision: bool = False
    supports_streaming: bool = False
    max_context_tokens: int = 0
    max_output_tokens: int = 0


@dataclass
class TokenUsage:
    """Token usage for a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""

    text: str | None = None
    tool_call: dict[str, Any] | None = None
    done: bool = False


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that all LLM providers must implement."""

    @property
    def name(self) -> str:
        """Provider name (e.g. 'claude-subscription', 'claude-api')."""
        ...

    @property
    def capabilities(self) -> ProviderCapabilities:
        """Provider capabilities."""
        ...

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        system: str | None = None,
    ) -> LLMResponse:
        """Send messages to the LLM and get a response."""
        ...

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response chunks from the LLM."""
        ...


# ---------------------------------------------------------------------------
# Claude Subscription Provider (PRIMARY — через подписку Max)
# ---------------------------------------------------------------------------


class ClaudeSubscriptionProvider:
    """LLM provider using Claude Max subscription via CLI proxy.

    Uses an OpenAI-compatible local proxy (claude-max-api-proxy or CLIProxyAPI)
    that wraps the Claude Code CLI to access your Claude Max subscription.

    No API key needed — uses your subscription directly.

    Setup:
        1. Install: npx claude-max-api-proxy
           or download CLIProxyAPI from github.com/router-for-me/CLIProxyAPI
        2. Run the proxy (it will listen on localhost)
        3. Set CLAUDE_PROXY_URL in .env (default: http://localhost:3456/v1)
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8317/v1",
        api_key: str = "progressive-agent-local",
        model: str = "claude-opus-4-6",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self._client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self._base_url = base_url
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._name = "claude-subscription"
        self._capabilities = ProviderCapabilities(
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            max_context_tokens=200_000,
            max_output_tokens=max_tokens,
        )
        logger.info(
            "ClaudeSubscriptionProvider initialized: proxy=%s, model=%s",
            base_url,
            model,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        system: str | None = None,
    ) -> LLMResponse:
        """Send messages to Claude via subscription proxy."""
        # Convert Anthropic-style messages to OpenAI format
        oai_messages = self._to_openai_messages(messages, system)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": oai_messages,
        }

        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        # Diagnostic: log tool names being sent to proxy
        if tools:
            tool_names = [t.get("name", "?") for t in tools]
            logger.info(
                "Proxy request: model=%s, msgs=%d, tools=%d (%s)",
                self._model, len(oai_messages), len(tools),
                ", ".join(tool_names),
            )
        else:
            logger.info(
                "Proxy request: model=%s, msgs=%d, no tools",
                self._model, len(oai_messages),
            )

        if stream:
            return await self._stream_to_response(kwargs)

        response = await self._client.chat.completions.create(**kwargs)
        parsed = self._parse_openai_response(response)

        # Diagnostic: log what came back
        if parsed.tool_calls:
            tc_names = [tc.get("name", "?") for tc in parsed.tool_calls]
            logger.info("Proxy response: text=%d chars, tool_calls=%s",
                        len(parsed.content), tc_names)
        else:
            logger.info("Proxy response: text=%d chars, no tool_calls",
                        len(parsed.content))

        return parsed

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response chunks from Claude via subscription proxy."""
        oai_messages = self._to_openai_messages(messages, system)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": oai_messages,
            "stream": True,
        }

        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)

        tool_calls_acc: dict[int, dict[str, Any]] = {}

        response_stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in response_stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Text content
            if delta.content:
                yield StreamChunk(text=delta.content)

            # Tool calls (accumulated across chunks)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function and tc.function.name else "",
                            "input": "",
                        }
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["input"] += tc.function.arguments

            # Check finish
            if chunk.choices and chunk.choices[0].finish_reason:
                # Emit accumulated tool calls
                for tc_data in tool_calls_acc.values():
                    try:
                        tc_data["input"] = json.loads(tc_data["input"])
                    except (json.JSONDecodeError, TypeError):
                        tc_data["input"] = {}
                    yield StreamChunk(tool_call=tc_data)
                yield StreamChunk(done=True)

    async def _stream_to_response(self, kwargs: dict[str, Any]) -> LLMResponse:
        """Collect streaming response into a single LLMResponse."""
        kwargs["stream"] = True
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_calls_acc: dict[int, dict[str, Any]] = {}

        response_stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in response_stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue
            if delta.content:
                text_parts.append(delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function and tc.function.name else "",
                            "input": "",
                        }
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["input"] += tc.function.arguments

        for tc_data in tool_calls_acc.values():
            try:
                tc_data["input"] = json.loads(tc_data["input"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Failed to parse streamed tool call arguments for %s "
                    "(truncated? length=%d): %.200s",
                    tc_data.get("name", "?"),
                    len(tc_data.get("input", "")),
                    tc_data.get("input", ""),
                )
                tc_data["input"] = {}
            tool_calls.append(tc_data)

        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            usage=TokenUsage(),
            model=self._model,
        )

    @staticmethod
    def _to_openai_messages(
        messages: list[dict[str, Any]], system: str | None
    ) -> list[dict[str, Any]]:
        """Convert Anthropic-style messages to OpenAI format.

        Handles three cases:
        1. Simple text messages → pass through
        2. Assistant messages with tool_use blocks → OpenAI tool_calls format
        3. User messages with tool_result blocks → OpenAI tool role messages
        """
        oai_messages: list[dict[str, Any]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Simple string content — pass through
            if isinstance(content, str):
                oai_messages.append({"role": role, "content": content})
                continue

            # List content — need to convert based on block types
            if isinstance(content, list) and content:
                first_type = content[0].get("type", "")

                # Assistant message with tool_use blocks → OpenAI tool_calls
                if role == "assistant" and first_type in ("text", "tool_use"):
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            })

                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": "\n".join(text_parts) if text_parts else "",
                    }
                    if tool_calls:
                        assistant_msg["tool_calls"] = tool_calls
                    oai_messages.append(assistant_msg)
                    continue

                # User message with tool_result blocks → OpenAI tool role
                if role == "user" and first_type == "tool_result":
                    for block in content:
                        if block.get("type") == "tool_result":
                            result_content = block.get("content", "")
                            if not result_content:
                                result_content = "No output."
                            oai_messages.append({
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": str(result_content),
                            })
                    continue

                # User message with text + image blocks → OpenAI vision format
                if role == "user":
                    oai_content: list[dict[str, Any]] = []
                    for block in content:
                        btype = block.get("type", "")
                        if btype == "text":
                            oai_content.append({
                                "type": "text",
                                "text": block.get("text", ""),
                            })
                        elif btype == "image":
                            source = block.get("source", {})
                            media_type = source.get("media_type", "image/jpeg")
                            b64_data = source.get("data", "")
                            oai_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{b64_data}",
                                },
                            })
                    if oai_content:
                        oai_messages.append({"role": "user", "content": oai_content})
                        continue

            # Fallback — serialize as string
            oai_messages.append({"role": role, "content": str(content)})

        return oai_messages

    @staticmethod
    def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic tool format to OpenAI function calling format."""
        oai_tools = []
        for tool in tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return oai_tools

    def _parse_openai_response(self, response: Any) -> LLMResponse:
        """Parse OpenAI-format response into LLMResponse."""
        choice = response.choices[0] if response.choices else None
        content = ""
        tool_calls: list[dict[str, Any]] = []

        if choice and choice.message:
            content = choice.message.content or ""
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                        logger.warning(
                            "Failed to parse tool call arguments for %s "
                            "(truncated response? args length=%d): %.200s",
                            tc.function.name,
                            len(tc.function.arguments or ""),
                            tc.function.arguments or "",
                        )
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": args,
                    })

        usage = TokenUsage()
        if response.usage:
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=response.model or self._model,
        )


# ---------------------------------------------------------------------------
# Claude API Provider (FALLBACK — через API ключ)
# ---------------------------------------------------------------------------


class ClaudeAPIProvider:
    """LLM provider using Anthropic API key (pay-per-token).

    This is the fallback provider. Used only when:
    - CLI proxy is not running
    - Explicitly configured for API key usage
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._name = "claude-api"
        self._capabilities = ProviderCapabilities(
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            max_context_tokens=200_000,
            max_output_tokens=max_tokens,
        )
        logger.info(
            "ClaudeAPIProvider initialized: model=%s, max_tokens=%d",
            model,
            max_tokens,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        system: str | None = None,
    ) -> LLMResponse:
        """Send messages to Claude API."""
        if stream:
            return await self._stream_to_response(messages, tools, system)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": messages,
        }
        if system:
            # Prompt caching: system as content block with cache_control
            # Saves ~90% on repeated system prompt tokens (5-min TTL)
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response chunks from Claude API."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if tools:
            kwargs["tools"] = tools

        current_tool_call: dict[str, Any] | None = None

        async with self._client.messages.stream(**kwargs) as stream_manager:
            async for event in stream_manager:
                if event.type == "content_block_start":
                    block = event.content_block
                    if hasattr(block, "type") and block.type == "tool_use":
                        current_tool_call = {
                            "id": block.id,
                            "name": block.name,
                            "input": "",
                        }

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "type"):
                        if delta.type == "text_delta":
                            yield StreamChunk(text=delta.text)
                        elif delta.type == "input_json_delta":
                            if current_tool_call is not None:
                                current_tool_call["input"] += delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_call is not None:
                        try:
                            current_tool_call["input"] = json.loads(
                                current_tool_call["input"]
                            )
                        except (json.JSONDecodeError, TypeError):
                            current_tool_call["input"] = {}
                        yield StreamChunk(tool_call=current_tool_call)
                        current_tool_call = None

                elif event.type == "message_stop":
                    yield StreamChunk(done=True)

    async def _stream_to_response(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        system: str | None,
    ) -> LLMResponse:
        """Collect streaming response into a single LLMResponse."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        async for chunk in self.stream(messages, tools, system):
            if chunk.text is not None:
                text_parts.append(chunk.text)
            if chunk.tool_call is not None:
                tool_calls.append(chunk.tool_call)

        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            usage=TokenUsage(),
            model=self._model,
        )

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse an Anthropic Messages API response into LLMResponse."""
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            model=response.model,
        )


# ---------------------------------------------------------------------------
# Mistral Provider (FREE TIER — 1B tokens/month)
# ---------------------------------------------------------------------------


class MistralProvider:
    """LLM provider using Mistral AI API (free tier: 1B tokens/month).

    Excellent for fallback — native function calling, 1 RPS limit.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "mistral-large-latest",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self._client = Mistral(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._name = "mistral"
        self._capabilities = ProviderCapabilities(
            supports_tools=True,
            supports_vision=False,
            supports_streaming=True,
            max_context_tokens=128_000,
            max_output_tokens=max_tokens,
        )
        logger.info(
            "MistralProvider initialized: model=%s, max_tokens=%d",
            model,
            max_tokens,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        system: str | None = None,
    ) -> LLMResponse:
        """Send messages to Mistral API."""
        # Convert Anthropic format to Mistral format
        mistral_messages = self._to_mistral_messages(messages, system)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": mistral_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }

        if tools:
            kwargs["tools"] = self._to_mistral_tools(tools)
            kwargs["tool_choice"] = "auto"

        if stream:
            return await self._stream_to_response(kwargs)

        response = await self._client.chat.complete_async(**kwargs)
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response chunks from Mistral API."""
        mistral_messages = self._to_mistral_messages(messages, system)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": mistral_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }

        if tools:
            kwargs["tools"] = self._to_mistral_tools(tools)

        async for chunk in await self._client.chat.stream_async(**kwargs):
            if chunk.data.choices:
                delta = chunk.data.choices[0].delta

                # Text content
                if hasattr(delta, "content") and delta.content:
                    yield StreamChunk(text=delta.content)

                # Tool calls
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.function:
                            yield StreamChunk(tool_call={
                                "id": tc.id or "",
                                "name": tc.function.name or "",
                                "input": json.loads(tc.function.arguments or "{}"),
                            })

                # Check finish
                if chunk.data.choices[0].finish_reason:
                    yield StreamChunk(done=True)

    async def _stream_to_response(self, kwargs: dict[str, Any]) -> LLMResponse:
        """Collect streaming response into a single LLMResponse."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        async for chunk in self.stream(kwargs["messages"], kwargs.get("tools")):
            if chunk.text is not None:
                text_parts.append(chunk.text)
            if chunk.tool_call is not None:
                tool_calls.append(chunk.tool_call)

        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            usage=TokenUsage(),
            model=self._model,
        )

    @staticmethod
    def _to_mistral_messages(
        messages: list[dict[str, Any]], system: str | None
    ) -> list[dict[str, Any]]:
        """Convert Anthropic-style messages to Mistral format."""
        mistral_messages: list[dict[str, Any]] = []

        # System message
        if system:
            mistral_messages.append({"role": "system", "content": system})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Simple text content
            if isinstance(content, str):
                mistral_messages.append({"role": role, "content": content})
                continue

            # Complex content (tool_use, tool_result blocks)
            if isinstance(content, list):
                # Convert tool_use blocks to tool_calls
                if role == "assistant":
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            })

                    msg_dict: dict[str, Any] = {
                        "role": "assistant",
                        "content": "\n".join(text_parts) if text_parts else "",
                    }
                    if tool_calls:
                        msg_dict["tool_calls"] = tool_calls
                    mistral_messages.append(msg_dict)
                    continue

                # Convert tool_result blocks to tool messages
                if role == "user":
                    for block in content:
                        if block.get("type") == "tool_result":
                            mistral_messages.append({
                                "role": "tool",
                                "name": block.get("name", "unknown"),
                                "content": str(block.get("content", "")),
                                "tool_call_id": block.get("tool_use_id", ""),
                            })
                    continue

            # Fallback
            mistral_messages.append({"role": role, "content": str(content)})

        return mistral_messages

    @staticmethod
    def _to_mistral_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic tool format to Mistral format."""
        mistral_tools = []
        for tool in tools:
            mistral_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return mistral_tools

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse Mistral response into LLMResponse."""
        choice = response.choices[0] if response.choices else None
        content = ""
        tool_calls: list[dict[str, Any]] = []

        if choice and choice.message:
            content = choice.message.content or ""
            if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        args = {}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": args,
                    })

        usage = TokenUsage()
        if hasattr(response, "usage") and response.usage:
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self._model,
        )


# ---------------------------------------------------------------------------
# OpenAI Provider (GPT-5.2/GPT-5.3 — платный fallback)
# ---------------------------------------------------------------------------


class OpenAIProvider:
    """LLM provider using OpenAI API (GPT-5.2/GPT-5.3).

    Fast and reliable fallback with good tool calling support.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.2",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._name = "openai"
        self._capabilities = ProviderCapabilities(
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            max_context_tokens=128_000,
            max_output_tokens=max_tokens,
        )
        logger.info(
            "OpenAIProvider initialized: model=%s, max_tokens=%d",
            model,
            max_tokens,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        system: str | None = None,
    ) -> LLMResponse:
        """Send messages to OpenAI API."""
        # Convert Anthropic format to OpenAI format
        openai_messages = self._to_openai_messages(messages, system)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }

        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"

        if stream:
            return await self._stream_to_response(kwargs)

        response = await self._client.chat.completions.create(**kwargs)
        return self._parse_response(response)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream response chunks from OpenAI API."""
        openai_messages = self._to_openai_messages(messages, system)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": openai_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": True,
        }

        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)

        async for chunk in await self._client.chat.completions.create(**kwargs):
            if chunk.choices:
                delta = chunk.choices[0].delta

                # Text content
                if delta.content:
                    yield StreamChunk(text=delta.content)

                # Tool calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.function:
                            yield StreamChunk(tool_call={
                                "id": tc.id or "",
                                "name": tc.function.name or "",
                                "input": json.loads(tc.function.arguments or "{}"),
                            })

                # Check finish
                if chunk.choices[0].finish_reason:
                    yield StreamChunk(done=True)

    async def _stream_to_response(self, kwargs: dict[str, Any]) -> LLMResponse:
        """Collect streaming response into a single LLMResponse."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        async for chunk in self.stream(kwargs["messages"], kwargs.get("tools")):
            if chunk.text is not None:
                text_parts.append(chunk.text)
            if chunk.tool_call is not None:
                tool_calls.append(chunk.tool_call)

        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            usage=TokenUsage(),
            model=self._model,
        )

    @staticmethod
    def _to_openai_messages(
        messages: list[dict[str, Any]], system: str | None
    ) -> list[dict[str, Any]]:
        """Convert Anthropic-style messages to OpenAI format."""
        openai_messages: list[dict[str, Any]] = []

        # System message
        if system:
            openai_messages.append({"role": "system", "content": system})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Simple text content
            if isinstance(content, str):
                openai_messages.append({"role": role, "content": content})
                continue

            # Complex content (tool_use, tool_result blocks)
            if isinstance(content, list):
                # Convert tool_use blocks to tool_calls
                if role == "assistant":
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            })

                    msg_dict: dict[str, Any] = {
                        "role": "assistant",
                        "content": "\n".join(text_parts) if text_parts else None,
                    }
                    if tool_calls:
                        msg_dict["tool_calls"] = tool_calls
                    openai_messages.append(msg_dict)
                    continue

                # Convert tool_result blocks to tool messages
                if role == "user":
                    for block in content:
                        if block.get("type") == "tool_result":
                            openai_messages.append({
                                "role": "tool",
                                "content": str(block.get("content", "")),
                                "tool_call_id": block.get("tool_use_id", ""),
                            })
                    continue

            # Fallback
            openai_messages.append({"role": role, "content": str(content)})

        return openai_messages

    @staticmethod
    def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Anthropic tool format to OpenAI format."""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return openai_tools

    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse OpenAI response into LLMResponse."""
        choice = response.choices[0] if response.choices else None
        content = ""
        tool_calls: list[dict[str, Any]] = []

        if choice and choice.message:
            content = choice.message.content or ""
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        args = {}
                        logger.warning(
                            "OpenAI: failed to parse tool call arguments for %s "
                            "(truncated? length=%d): %.200s",
                            tc.function.name,
                            len(tc.function.arguments or ""),
                            tc.function.arguments or "",
                        )
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": args,
                    })

        usage = TokenUsage()
        if response.usage:
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=self._model,
        )


# ---------------------------------------------------------------------------
# Google Gemini Provider (FREE — 15 RPM, OpenAI-compatible)
# ---------------------------------------------------------------------------


class GeminiProvider(OpenAIProvider):
    """LLM provider using Google Gemini API (OpenAI-compatible endpoint).

    Free tier: 15 requests/min, 1500/day for gemini-2.0-flash.
    Supports tools, vision (multimodal), streaming.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._name = "gemini"
        self._capabilities = ProviderCapabilities(
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            max_context_tokens=1_000_000,  # Gemini 2.0 Flash has 1M context
            max_output_tokens=max_tokens,
        )
        logger.info(
            "GeminiProvider initialized: model=%s (OpenAI-compatible endpoint)",
            model,
        )


# ---------------------------------------------------------------------------
# Cloudflare Workers AI Provider (FREE — 10K req/day, OpenAI-compatible)
# ---------------------------------------------------------------------------


class CloudflareAIProvider(OpenAIProvider):
    """LLM provider using Cloudflare Workers AI (OpenAI-compatible Gateway).

    Free tier: 10,000 neurons/day (~10K requests for small models).
    Models: @cf/meta/llama-3.3-70b-instruct-fp8-fast, @hf/mistral/mistral-7b-instruct, etc.
    Supports tools, streaming.
    """

    def __init__(
        self,
        api_key: str,
        account_id: str,
        model: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        )
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._name = "cloudflare-ai"
        self._capabilities = ProviderCapabilities(
            supports_tools=True,
            supports_vision=False,  # Most CF models don't support vision
            supports_streaming=True,
            max_context_tokens=128_000,
            max_output_tokens=max_tokens,
        )
        logger.info(
            "CloudflareAIProvider initialized: model=%s, account=%s...",
            model,
            account_id[:8],
        )


# ---------------------------------------------------------------------------
# Fallback Provider (AUTO-HEALING — прокси + API ключ)
# ---------------------------------------------------------------------------

# Errors that indicate proxy auth failure (should trigger fallback)
_AUTH_ERRORS = ("auth_unavailable", "no auth available", "auth expired", "unauthorized")


def _is_auth_error(exc: Exception) -> bool:
    """Check if an exception is a proxy auth failure."""
    msg = str(exc).lower()
    return any(sig in msg for sig in _AUTH_ERRORS)


def _is_proxy_error(exc: Exception) -> bool:
    """Check if an exception is a proxy connectivity/auth issue (not a normal LLM error)."""
    if _is_auth_error(exc):
        return True
    # Connection refused, proxy down
    msg = str(exc).lower()
    if "connection" in msg and ("refused" in msg or "error" in msg):
        return True
    # OpenAI client errors that indicate server issues (not input issues)
    # Any 5xx from proxy should trigger fallback (crash, overload, auth — doesn't matter)
    if isinstance(exc, openai.APIStatusError) and exc.status_code in (500, 502, 503):
        return True
    if isinstance(exc, (openai.APIConnectionError, ConnectionError, OSError)):
        return True
    return False


class FallbackProvider:
    """Multi-level fallback provider with automatic recovery.

    Tries providers in order. If primary fails (auth, connection error),
    switches to fallback automatically.

    Usage:
        provider = FallbackProvider(
            primary=ClaudeSubscriptionProvider(...),
            fallbacks=[
                MistralProvider(...),     # Free tier (комп OFF)
                ClaudeAPIProvider(...),   # Paid backup
            ]
        )
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: list[LLMProvider] | None = None,
        auto_recovery: bool = True,
    ) -> None:
        self._primary = primary
        self._fallbacks = fallbacks or []
        self._auto_recovery = auto_recovery
        self._current_provider = primary
        self._failure_count = 0
        self._max_failures = 3
        logger.info(
            "FallbackProvider initialized: primary=%s, fallbacks=%d, auto_recovery=%s",
            primary.name,
            len(self._fallbacks),
            auto_recovery,
        )

    @property
    def name(self) -> str:
        return f"fallback({self._current_provider.name})"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._current_provider.capabilities

    @property
    def model(self) -> str:
        return getattr(self._current_provider, "model", "unknown")

    @model.setter
    def model(self, value: str) -> None:
        # Only update primary provider's model, not fallback providers
        # Each fallback provider should keep its own model (mistral-large-latest, gpt-5.2, etc.)
        if hasattr(self._primary, "model"):
            self._primary.model = value  # type: ignore[union-attr]

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        system: str | None = None,
    ) -> LLMResponse:
        """Try primary, fallback on error."""
        providers = [self._current_provider] + self._fallbacks
        last_error: Exception | None = None

        for i, provider in enumerate(providers):
            try:
                logger.debug("Trying provider: %s", provider.name)
                response = await provider.complete(messages, tools, stream, system)

                # Success — reset failure count and return to primary if needed
                if self._auto_recovery and provider != self._primary:
                    self._failure_count = 0
                    logger.info(
                        "Fallback succeeded with %s, staying on fallback for now",
                        provider.name,
                    )
                    self._current_provider = provider

                return response

            except Exception as exc:
                last_error = exc
                is_proxy_issue = _is_proxy_error(exc)

                if is_proxy_issue and i < len(providers) - 1:
                    logger.warning(
                        "Provider %s failed (proxy error): %s — trying next",
                        provider.name,
                        exc,
                    )
                    self._failure_count += 1
                    if self._failure_count >= self._max_failures:
                        self._current_provider = self._fallbacks[0] if self._fallbacks else self._primary
                        logger.info(
                            "Switched to fallback provider: %s (after %d failures)",
                            self._current_provider.name,
                            self._failure_count,
                        )
                    continue

                # Not a proxy error or last provider → re-raise
                raise

        # All providers failed
        raise last_error or RuntimeError("All providers failed")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Try primary, fallback on error."""
        providers = [self._current_provider] + self._fallbacks
        last_error: Exception | None = None

        for i, provider in enumerate(providers):
            try:
                logger.debug("Streaming with provider: %s", provider.name)
                async for chunk in provider.stream(messages, tools, system):
                    yield chunk

                # Success
                if self._auto_recovery and provider != self._primary:
                    self._current_provider = provider
                return

            except Exception as exc:
                last_error = exc
                is_proxy_issue = _is_proxy_error(exc)

                if is_proxy_issue and i < len(providers) - 1:
                    logger.warning(
                        "Streaming provider %s failed: %s — trying next",
                        provider.name,
                        exc,
                    )
                    self._failure_count += 1
                    continue

                raise

        raise last_error or RuntimeError("All providers failed for streaming")

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Factory: создаёт нужный провайдер по конфигу
# ---------------------------------------------------------------------------


def create_provider(
    proxy_url: str | None = None,
    api_key: str | None = None,
    mistral_api_key: str | None = None,
    openai_api_key: str | None = None,
    gemini_api_key: str | None = None,
    cloudflare_api_key: str | None = None,
    cloudflare_account_id: str | None = None,
    model: str = "claude-opus-4-6",
    mistral_model: str = "mistral-large-latest",
    openai_model: str = "gpt-5.2",
    gemini_model: str = "gemini-2.0-flash",
    cloudflare_model: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> ClaudeSubscriptionProvider | ClaudeAPIProvider | MistralProvider | OpenAIProvider | FallbackProvider:
    """Create the appropriate LLM provider with multi-level fallback.

    Priority:
    1. If proxy_url + fallback keys → FallbackProvider (Claude proxy → fallbacks)
    2. If proxy_url only → ClaudeSubscriptionProvider
    3. If api_key → ClaudeAPIProvider
    4. Default → ClaudeSubscriptionProvider with default localhost proxy

    Fallback chain order:
    Claude proxy → Mistral (free) → Cloudflare AI (free) → OpenAI (paid) → Claude API (paid)
    """
    has_fallbacks = mistral_api_key or openai_api_key or api_key or gemini_api_key or cloudflare_api_key

    # Multi-level fallback
    if proxy_url and has_fallbacks:
        primary = ClaudeSubscriptionProvider(
            base_url=proxy_url,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        fallbacks: list[LLMProvider] = []

        # Gemini removed — free tier quota = 0, бесполезен
        # If you get a paid Gemini key, uncomment this:
        # if gemini_api_key:
        #     fallbacks.append(GeminiProvider(
        #         api_key=gemini_api_key,
        #         model=gemini_model,
        #         max_tokens=max_tokens,
        #         temperature=temperature,
        #     ))

        # Mistral free tier (1st fallback — бесплатно, 1 RPS)
        if mistral_api_key:
            fallbacks.append(MistralProvider(
                api_key=mistral_api_key,
                model=mistral_model,
                max_tokens=max_tokens,
                temperature=temperature,
            ))

        # Cloudflare Workers AI (3rd fallback — бесплатно, 10K/day)
        if cloudflare_api_key and cloudflare_account_id:
            fallbacks.append(CloudflareAIProvider(
                api_key=cloudflare_api_key,
                account_id=cloudflare_account_id,
                model=cloudflare_model,
                max_tokens=max_tokens,
                temperature=temperature,
            ))

        # OpenAI (4th fallback — платно, но быстрее и надёжнее)
        if openai_api_key:
            fallbacks.append(OpenAIProvider(
                api_key=openai_api_key,
                model=openai_model,
                max_tokens=max_tokens,
                temperature=temperature,
            ))

        # Claude API (3rd fallback — платно)
        if api_key:
            fallbacks.append(ClaudeAPIProvider(
                api_key=api_key,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            ))

        if fallbacks:
            logger.info(
                "Using FallbackProvider: primary=%s, fallbacks=%s",
                primary.name,
                [f.name for f in fallbacks],
            )
            return FallbackProvider(
                primary=primary,
                fallbacks=fallbacks,
                auto_recovery=True,
            )

    # No fallback keys — just proxy
    if proxy_url:
        logger.info("Using Claude subscription (proxy: %s)", proxy_url)
        return ClaudeSubscriptionProvider(
            base_url=proxy_url,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    # Mistral only (free tier standalone)
    if mistral_api_key and not api_key:
        logger.info("Using Mistral API (free tier)")
        return MistralProvider(
            api_key=mistral_api_key,
            model=mistral_model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    # Claude API only
    if api_key:
        logger.info("Using Claude API (pay-per-token)")
        return ClaudeAPIProvider(
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    # Default: try subscription proxy on default port
    logger.info("Using Claude subscription (default proxy: http://localhost:3456/v1)")
    return ClaudeSubscriptionProvider(
        base_url="http://localhost:3456/v1",
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )


# Keep old name as alias for backward compatibility with tests
ClaudeProvider = ClaudeAPIProvider
