"""
Dispatcher — translates between Agent tool-call format and LLM provider format.

Two implementations:
- NativeDispatcher: for providers with native function calling (Claude, GPT-4).
  Passes tools as JSON schema, parses tool_use blocks from response.
- XmlDispatcher: fallback for providers without function calling.
  Instructs model to return XML tool calls, parses them.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.core.llm import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A parsed tool call from an LLM response."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""  # Provider-specific ID for result matching


@dataclass
class DispatchResult:
    """Result from dispatching messages through a provider."""

    response_text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_response: LLMResponse | None = None


# ---------------------------------------------------------------------------
# Dispatcher Protocol
# ---------------------------------------------------------------------------


class Dispatcher(Protocol):
    """Protocol for message dispatchers.

    Dispatchers handle the translation between the Agent's internal
    representation and the LLM provider's specific format for tools.
    """

    async def dispatch(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        provider: LLMProvider,
        system: str | None = None,
    ) -> DispatchResult:
        """Dispatch messages to the LLM provider and parse the response.

        Args:
            messages: Conversation messages.
            tools: Tool definitions (JSON schema format).
            provider: LLM provider to use.
            system: Optional system prompt.

        Returns:
            DispatchResult with response text and parsed tool calls.
        """
        ...


# ---------------------------------------------------------------------------
# NativeDispatcher — for Claude and other models with native tool use
# ---------------------------------------------------------------------------


class NativeDispatcher:
    """Dispatcher for providers with native function calling support.

    Passes tools as JSON schema to the provider and parses tool_use
    blocks from the response. This is the preferred dispatcher for
    Claude (Anthropic API).
    """

    async def dispatch(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        provider: LLMProvider,
        system: str | None = None,
    ) -> DispatchResult:
        """Send messages with tools via native function calling.

        Args:
            messages: Conversation messages.
            tools: Tool definitions in Anthropic JSON schema format.
            provider: LLM provider (must support native tools).
            system: Optional system prompt.

        Returns:
            DispatchResult with parsed tool calls.
        """
        logger.debug(
            "NativeDispatcher: sending %d messages, %d tools to %s",
            len(messages),
            len(tools) if tools else 0,
            provider.name,
        )

        # Build kwargs for the provider
        kwargs: dict[str, Any] = {
            "messages": messages,
            "tools": tools if tools else None,
        }
        if system is not None:
            kwargs["system"] = system

        response: LLMResponse = await provider.complete(**kwargs)

        # Parse tool calls from response
        tool_calls = [
            ToolCall(
                tool_name=tc.get("name", "unknown_tool"),
                arguments=tc.get("input", {}),
                call_id=tc.get("id", ""),
            )
            for tc in response.tool_calls
        ]

        if tool_calls:
            logger.info(
                "NativeDispatcher: received %d tool calls: %s",
                len(tool_calls),
                [tc.tool_name for tc in tool_calls],
            )

        return DispatchResult(
            response_text=response.content,
            tool_calls=tool_calls,
            raw_response=response,
        )


# ---------------------------------------------------------------------------
# XmlDispatcher — fallback for models without native function calling
# ---------------------------------------------------------------------------

# System prompt addition to instruct the model to use XML for tool calls
XML_TOOL_INSTRUCTION = """
When you need to use a tool, respond with XML in this exact format:

<tool_call>
<tool_name>tool_name_here</tool_name>
<arguments>
{"param1": "value1", "param2": "value2"}
</arguments>
</tool_call>

You may include regular text before or after the tool call.
If you need multiple tool calls, use multiple <tool_call> blocks.
Available tools:
{tool_descriptions}
"""

# Regex for parsing XML tool calls
_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*"
    r"<tool_name>(.*?)</tool_name>\s*"
    r"<arguments>\s*(.*?)\s*</arguments>\s*"
    r"</tool_call>",
    re.DOTALL,
)


class XmlDispatcher:
    """Fallback dispatcher that uses XML-formatted tool calls.

    For models that don't support native function calling, this
    dispatcher instructs the model to return tool calls as XML
    and parses them from the text response.
    """

    async def dispatch(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        provider: LLMProvider,
        system: str | None = None,
    ) -> DispatchResult:
        """Send messages with XML-based tool instructions.

        Args:
            messages: Conversation messages.
            tools: Tool definitions (used to build XML instructions).
            provider: LLM provider.
            system: Optional base system prompt.

        Returns:
            DispatchResult with tool calls parsed from XML in response text.
        """
        logger.debug(
            "XmlDispatcher: sending %d messages, %d tools to %s",
            len(messages),
            len(tools) if tools else 0,
            provider.name,
        )

        # Build system prompt with XML tool instructions
        effective_system = system or ""
        if tools:
            tool_descriptions = self._format_tool_descriptions(tools)
            xml_instruction = XML_TOOL_INSTRUCTION.format(
                tool_descriptions=tool_descriptions
            )
            effective_system = f"{effective_system}\n\n{xml_instruction}".strip()

        # Send without native tools — model returns text with XML
        kwargs: dict[str, Any] = {
            "messages": messages,
        }
        if effective_system:
            kwargs["system"] = effective_system

        response: LLMResponse = await provider.complete(**kwargs)

        # Parse XML tool calls from response text
        tool_calls = self._parse_xml_tool_calls(response.content)
        response_text = self._strip_tool_calls(response.content)

        if tool_calls:
            logger.info(
                "XmlDispatcher: parsed %d tool calls from XML: %s",
                len(tool_calls),
                [tc.tool_name for tc in tool_calls],
            )

        return DispatchResult(
            response_text=response_text,
            tool_calls=tool_calls,
            raw_response=response,
        )

    def _format_tool_descriptions(self, tools: list[dict[str, Any]]) -> str:
        """Format tool definitions as text descriptions for the system prompt.

        Args:
            tools: Tool definitions in JSON schema format.

        Returns:
            Human-readable tool descriptions.
        """
        descriptions: list[str] = []
        for tool in tools:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            schema = tool.get("input_schema", {})
            params = schema.get("properties", {})
            required = schema.get("required", [])

            param_lines: list[str] = []
            for param_name, param_info in params.items():
                req_mark = " (required)" if param_name in required else ""
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                param_lines.append(
                    f"  - {param_name}: {param_type}{req_mark} — {param_desc}"
                )

            tool_desc = f"- {name}: {desc}"
            if param_lines:
                tool_desc += "\n" + "\n".join(param_lines)
            descriptions.append(tool_desc)

        return "\n".join(descriptions)

    def _parse_xml_tool_calls(self, text: str) -> list[ToolCall]:
        """Parse XML-formatted tool calls from response text.

        Args:
            text: Full response text that may contain <tool_call> blocks.

        Returns:
            List of parsed ToolCall objects.
        """
        tool_calls: list[ToolCall] = []

        for match in _TOOL_CALL_PATTERN.finditer(text):
            tool_name = match.group(1).strip()
            arguments_str = match.group(2).strip()

            try:
                arguments = json.loads(arguments_str)
            except json.JSONDecodeError:
                logger.warning(
                    "XmlDispatcher: failed to parse arguments for tool %s: %s",
                    tool_name,
                    arguments_str[:100],
                )
                arguments = {}

            tool_calls.append(
                ToolCall(
                    tool_name=tool_name,
                    arguments=arguments,
                )
            )

        return tool_calls

    def _strip_tool_calls(self, text: str) -> str:
        """Remove XML tool call blocks from response text.

        Args:
            text: Full response text.

        Returns:
            Text with <tool_call> blocks removed and whitespace cleaned up.
        """
        cleaned = _TOOL_CALL_PATTERN.sub("", text)
        # Clean up excessive whitespace left behind
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
