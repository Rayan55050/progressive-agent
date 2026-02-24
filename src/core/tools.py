"""
Базовые интерфейсы для инструментов агента.

Каждый инструмент (search, email, files и т.д.) реализует Protocol Tool.
Инструменты регистрируются в ToolRegistry и доступны агенту.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolResult:
    """Результат выполнения инструмента."""

    success: bool
    data: Any = None
    error: str | None = None


@dataclass
class ToolParameter:
    """Параметр инструмента (для генерации JSON schema)."""

    name: str
    type: str  # "string", "integer", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class ToolDefinition:
    """Определение инструмента для LLM (JSON schema для function calling)."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)

    def to_anthropic_schema(self) -> dict:
        """Конвертировать в формат Anthropic API tools."""
        properties = {}
        required = []
        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


@runtime_checkable
class Tool(Protocol):
    """Протокол инструмента агента.

    Каждый инструмент реализует этот интерфейс.
    Используется Dispatcher'ом для выполнения tool calls от LLM.
    """

    @property
    def definition(self) -> ToolDefinition:
        """Определение инструмента (имя, описание, параметры)."""
        ...

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Выполнить инструмент с заданными параметрами."""
        ...


class ToolRegistry:
    """Реестр инструментов агента.

    Хранит все зарегистрированные инструменты.
    Предоставляет доступ по имени и генерирует schemas для LLM.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Зарегистрировать инструмент."""
        self._tools[tool.definition.name] = tool

    def get(self, name: str) -> Tool | None:
        """Получить инструмент по имени."""
        return self._resolve_tool_name(name)

    def list_tools(self) -> list[ToolDefinition]:
        """Список всех инструментов."""
        return [tool.definition for tool in self._tools.values()]

    def to_anthropic_tools(self) -> list[dict]:
        """Все инструменты в формате Anthropic API."""
        return [tool.definition.to_anthropic_schema() for tool in self._tools.values()]

    def _resolve_tool_name(self, name: str) -> Tool | None:
        """Resolve tool by name, stripping common prefixes.

        Some proxies (e.g. CLIProxyAPI) add a 'proxy_' prefix to tool
        names. This method tries exact match first, then stripped variants.
        """
        tool = self._tools.get(name)
        if tool is not None:
            return tool
        # Strip proxy_ prefix (CLIProxyAPI adds this)
        if name.startswith("proxy_"):
            tool = self._tools.get(name[6:])
            if tool is not None:
                return tool
        return None

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """Выполнить инструмент по имени."""
        tool = self._resolve_tool_name(tool_name)
        if tool is None:
            return ToolResult(success=False, error=f"Tool '{tool_name}' not found")
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(success=False, error=f"Tool '{tool_name}' failed: {e}")
