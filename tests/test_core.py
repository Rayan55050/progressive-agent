"""
Tests for core modules:
- config.py (load_config, AppConfig)
- llm.py (ClaudeProvider)
- reliable.py (@reliable decorator)
- cost_tracker.py (CostTracker, calculate_cost)
- router.py (Router)
- dispatcher.py (NativeDispatcher)
- agent.py (Agent, AgentBuilder)
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.channels.base import IncomingMessage
from src.core.agent import Agent, AgentBuilder, _load_soul_files
from src.core.config import AgentConfig, AppConfig, CostConfig, load_config
from src.core.cost_tracker import (
    BudgetStatus,
    CostTracker,
    calculate_cost,
)
from src.core.dispatcher import DispatchResult, NativeDispatcher, ToolCall
from src.core.llm import ClaudeProvider, LLMResponse, TokenUsage
from src.core.reliable import reliable
from src.core.router import Router, RoutingResult, _estimate_complexity
from src.core.tools import ToolDefinition, ToolParameter, ToolRegistry, ToolResult


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def tmp_toml_config(tmp_path: Path) -> Path:
    """Create a temporary TOML config file."""
    content = """\
[agent]
name = "Test Agent"
default_model = "claude-test-model"
fallback_model = "claude-test-haiku"
max_tokens = 2048
temperature = 0.5

[telegram]
allowed_users = [111, 222]
streaming_chunk_size = 30

[memory]
db_path = "data/test_memory.db"
embedding_model = "text-embedding-3-small"
embedding_dimensions = 128
max_context_memories = 5
temporal_decay_lambda = 0.02

[costs]
daily_limit_usd = 1.0
monthly_limit_usd = 10.0
warning_threshold = 0.7

[search]
provider = "tavily"
max_results = 3
"""
    cfg_file = tmp_path / "agent.toml"
    cfg_file.write_text(content, encoding="utf-8")
    return cfg_file


@pytest.fixture
def cost_config(tmp_path: Path) -> CostConfig:
    """CostConfig that stores DB in tmp_path."""
    return CostConfig(
        daily_limit_usd=5.0,
        monthly_limit_usd=50.0,
        warning_threshold=0.8,
        db_path=str(tmp_path / "costs.db"),
    )


@pytest.fixture
def mock_provider() -> MagicMock:
    """Create a mock LLM provider."""
    provider = MagicMock()
    provider.name = "claude"
    provider.model = "claude-test-model"
    provider.capabilities = MagicMock(
        supports_tools=True,
        supports_vision=True,
        supports_streaming=True,
    )
    provider.complete = AsyncMock(
        return_value=LLMResponse(
            content="Hello, test!",
            tool_calls=[],
            usage=TokenUsage(input_tokens=100, output_tokens=50),
            model="claude-test-model",
        )
    )
    return provider


@pytest.fixture
def mock_skill() -> MagicMock:
    """Create a mock skill."""
    skill = MagicMock()
    skill.name = "web_search"
    skill.description = "Search the web"
    skill.trigger_keywords = ["search", "find", "look up"]
    skill.tools = ["web_search"]
    skill.instructions = "Use the web_search tool to find information."
    return skill


@pytest.fixture
def soul_dir(tmp_path: Path) -> Path:
    """Create a temporary soul directory with files."""
    soul = tmp_path / "soul"
    soul.mkdir()
    (soul / "SOUL.md").write_text("I am a test agent.", encoding="utf-8")
    (soul / "OWNER.md").write_text("Owner: Tester", encoding="utf-8")
    (soul / "RULES.md").write_text("Rule 1: Be nice.", encoding="utf-8")
    return soul


# =========================================================================
# Tests: config.py
# =========================================================================


class TestLoadConfig:
    """Tests for load_config() function."""

    def test_load_config_with_toml(self, tmp_toml_config: Path) -> None:
        """load_config() should parse TOML file and return AppConfig."""
        # Patch PROJECT_ROOT to point to parent of our temp config
        config_dir = tmp_toml_config.parent
        with patch("src.core.config.PROJECT_ROOT", config_dir):
            config = load_config("agent.toml")

        assert isinstance(config, AppConfig)
        assert config.agent.name == "Test Agent"
        assert config.agent.default_model == "claude-test-model"
        assert config.agent.max_tokens == 2048
        assert config.agent.temperature == 0.5
        assert config.telegram.allowed_users == [111, 222]
        assert config.memory.embedding_dimensions == 128
        assert config.costs.daily_limit_usd == 1.0
        assert config.search.max_results == 3

    def test_load_config_defaults_when_no_file(self, tmp_path: Path) -> None:
        """load_config() uses defaults when TOML file is missing."""
        with patch("src.core.config.PROJECT_ROOT", tmp_path):
            config = load_config("nonexistent.toml")

        assert config.agent.name == "Progressive Agent"
        assert config.agent.default_model == "claude-opus-4-6"
        assert config.agent.max_tokens == 4096

    def test_load_config_loads_env_secrets(self, tmp_path: Path) -> None:
        """load_config() loads API keys from environment."""
        with (
            patch("src.core.config.PROJECT_ROOT", tmp_path),
            patch.dict(
                os.environ,
                {
                    "ANTHROPIC_API_KEY": "sk-ant-test",
                    "TELEGRAM_BOT_TOKEN": "123:ABC",
                    "OPENAI_API_KEY": "sk-openai-test",
                    "TAVILY_API_KEY": "tvly-test",
                },
            ),
        ):
            config = load_config("nonexistent.toml")

        assert config.anthropic_api_key == "sk-ant-test"
        assert config.telegram_bot_token == "123:ABC"
        assert config.openai_api_key == "sk-openai-test"
        assert config.tavily_api_key == "tvly-test"

    def test_app_config_validation(self) -> None:
        """AppConfig validates types with Pydantic."""
        cfg = AppConfig(
            agent=AgentConfig(name="X", max_tokens=999),
        )
        assert cfg.agent.name == "X"
        assert cfg.agent.max_tokens == 999
        assert cfg.memory.db_path == "data/memory.db"  # default


# =========================================================================
# Tests: llm.py
# =========================================================================


class TestClaudeProvider:
    """Tests for ClaudeProvider."""

    @patch("src.core.llm.anthropic.AsyncAnthropic")
    def test_creation(self, mock_anthropic_cls: MagicMock) -> None:
        """ClaudeProvider initializes with correct attributes."""
        provider = ClaudeProvider(
            api_key="sk-ant-test",
            model="claude-test-model",
            max_tokens=2048,
            temperature=0.5,
        )

        assert provider.name == "claude-api"
        assert provider.model == "claude-test-model"
        assert provider.capabilities.supports_tools is True
        assert provider.capabilities.supports_vision is True
        assert provider.capabilities.supports_streaming is True
        assert provider.capabilities.max_output_tokens == 2048

        mock_anthropic_cls.assert_called_once_with(api_key="sk-ant-test")

    @patch("src.core.llm.anthropic.AsyncAnthropic")
    def test_model_setter(self, mock_anthropic_cls: MagicMock) -> None:
        """ClaudeProvider.model setter changes the model."""
        provider = ClaudeProvider(api_key="sk-ant-test")
        provider.model = "new-model-id"
        assert provider.model == "new-model-id"

    @pytest.mark.asyncio
    @patch("src.core.llm.anthropic.AsyncAnthropic")
    async def test_complete_calls_api(self, mock_anthropic_cls: MagicMock) -> None:
        """ClaudeProvider.complete() calls the Anthropic messages API."""
        # Build a mock API response
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Test response"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 20
        mock_response.model = "claude-test-model"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic_cls.return_value = mock_client

        provider = ClaudeProvider(api_key="sk-ant-test", model="claude-test-model")
        result = await provider.complete(
            messages=[{"role": "user", "content": "Hello"}]
        )

        assert isinstance(result, LLMResponse)
        assert result.content == "Test response"
        assert result.usage.input_tokens == 10
        assert result.usage.output_tokens == 20
        assert result.tool_calls == []

    @pytest.mark.asyncio
    @patch("src.core.llm.anthropic.AsyncAnthropic")
    async def test_complete_with_tool_use(self, mock_anthropic_cls: MagicMock) -> None:
        """ClaudeProvider.complete() parses tool_use blocks."""
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Let me search."

        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.id = "call_123"
        mock_tool_block.name = "web_search"
        mock_tool_block.input = {"query": "test"}

        mock_response = MagicMock()
        mock_response.content = [mock_text_block, mock_tool_block]
        mock_response.usage.input_tokens = 15
        mock_response.usage.output_tokens = 25
        mock_response.model = "claude-test-model"

        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic_cls.return_value = mock_client

        provider = ClaudeProvider(api_key="sk-ant-test")
        result = await provider.complete(
            messages=[{"role": "user", "content": "Search for X"}],
            tools=[{"name": "web_search"}],
        )

        assert result.content == "Let me search."
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "web_search"
        assert result.tool_calls[0]["input"] == {"query": "test"}


# =========================================================================
# Tests: reliable.py
# =========================================================================


class TestReliableDecorator:
    """Tests for @reliable decorator."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self) -> None:
        """Function succeeds on first try -- no retries."""
        call_count = 0

        @reliable(max_retries=3, base_delay=0.01)
        async def succeed() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self) -> None:
        """Retries on asyncio.TimeoutError, then succeeds."""
        call_count = 0

        @reliable(max_retries=3, base_delay=0.01)
        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise asyncio.TimeoutError()
            return "ok"

        result = await flaky()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self) -> None:
        """Retries on ConnectionError, then succeeds."""
        call_count = 0

        @reliable(max_retries=2, base_delay=0.01)
        async def flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("refused")
            return "ok"

        result = await flaky()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_retryable_http_status(self) -> None:
        """Retries on 429 HTTP status."""
        call_count = 0
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}

        @reliable(max_retries=2, base_delay=0.01)
        async def rate_limited() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.HTTPStatusError(
                    "Rate limited", request=MagicMock(), response=mock_response
                )
            return "ok"

        result = await rate_limited()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_raises_on_non_retryable_http_status(self) -> None:
        """Non-retryable HTTP status (e.g. 404) raises immediately."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {}

        @reliable(max_retries=3, base_delay=0.01)
        async def not_found() -> str:
            raise httpx.HTTPStatusError(
                "Not found", request=MagicMock(), response=mock_response
            )

        with pytest.raises(httpx.HTTPStatusError):
            await not_found()

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self) -> None:
        """Raises after max retries are exhausted."""
        call_count = 0

        @reliable(max_retries=2, base_delay=0.01)
        async def always_timeout() -> str:
            nonlocal call_count
            call_count += 1
            raise asyncio.TimeoutError()

        with pytest.raises(asyncio.TimeoutError):
            await always_timeout()

        # 1 initial attempt + 2 retries = 3 total
        assert call_count == 3


# =========================================================================
# Tests: cost_tracker.py
# =========================================================================


class TestCostTracker:
    """Tests for CostTracker."""

    def test_calculate_cost_sonnet(self) -> None:
        """calculate_cost for Sonnet model uses correct pricing."""
        cost = calculate_cost("claude-sonnet-4-5-20250929", 1_000_000, 1_000_000)
        # Sonnet: 3.0 input + 15.0 output = 18.0
        assert cost == pytest.approx(18.0)

    def test_calculate_cost_haiku(self) -> None:
        """calculate_cost for Haiku model uses correct pricing."""
        cost = calculate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        # Haiku: 0.80 input + 4.0 output = 4.80
        assert cost == pytest.approx(4.80)

    def test_calculate_cost_unknown_model(self) -> None:
        """calculate_cost for unknown model falls back to default pricing."""
        cost = calculate_cost("unknown-model", 1_000_000, 1_000_000)
        # Default: 3.0 input + 15.0 output = 18.0
        assert cost == pytest.approx(18.0)

    def test_calculate_cost_small_usage(self) -> None:
        """calculate_cost correctly handles small token counts."""
        cost = calculate_cost("claude-sonnet-4-5-20250929", 100, 50)
        # Sonnet: (100/1M * 3.0) + (50/1M * 15.0) = 0.0003 + 0.00075 = 0.00105
        assert cost == pytest.approx(0.00105)

    @pytest.mark.asyncio
    async def test_track_records_usage(self, cost_config: CostConfig) -> None:
        """CostTracker.track() records usage and returns cost."""
        tracker = CostTracker(cost_config)
        await tracker.initialize()

        cost = await tracker.track("claude", "claude-sonnet-4-5-20250929", 1000, 500)
        assert cost > 0

        daily = await tracker.get_daily_spend()
        assert daily > 0
        assert daily == pytest.approx(cost)

        await tracker.close()

    @pytest.mark.asyncio
    async def test_budget_ok(self, cost_config: CostConfig) -> None:
        """check_budget returns OK when under limits."""
        tracker = CostTracker(cost_config)
        await tracker.initialize()

        status = await tracker.check_budget()
        assert status == BudgetStatus.OK

        await tracker.close()

    @pytest.mark.asyncio
    async def test_budget_exceeded(self, tmp_path: Path) -> None:
        """check_budget returns EXCEEDED when over daily limit."""
        cfg = CostConfig(
            daily_limit_usd=0.001,
            monthly_limit_usd=50.0,
            warning_threshold=0.8,
            db_path=str(tmp_path / "costs.db"),
        )
        tracker = CostTracker(cfg)
        await tracker.initialize()

        # Track enough to exceed the tiny limit
        await tracker.track("claude", "claude-sonnet-4-5-20250929", 100_000, 100_000)

        status = await tracker.check_budget()
        assert status == BudgetStatus.EXCEEDED

        await tracker.close()

    @pytest.mark.asyncio
    async def test_budget_warning(self, tmp_path: Path) -> None:
        """check_budget returns WARNING when over threshold but under limit."""
        cfg = CostConfig(
            daily_limit_usd=1.0,
            monthly_limit_usd=100.0,
            warning_threshold=0.5,
            db_path=str(tmp_path / "costs.db"),
        )
        tracker = CostTracker(cfg)
        await tracker.initialize()

        # Track enough to be above 50% but below 100% of daily limit
        # Sonnet: (1M/1M * 3) + (1M/1M * 15) = 18 per 1M tokens
        # We need ~$0.6 -> roughly 200_000 input tokens at $3/1M = $0.6
        await tracker.track("claude", "claude-sonnet-4-5-20250929", 200_000, 0)

        status = await tracker.check_budget()
        assert status == BudgetStatus.WARNING

        await tracker.close()

    @pytest.mark.asyncio
    async def test_monthly_spend(self, cost_config: CostConfig) -> None:
        """get_monthly_spend() aggregates all today's records."""
        tracker = CostTracker(cost_config)
        await tracker.initialize()

        await tracker.track("claude", "claude-sonnet-4-5-20250929", 500, 500)
        await tracker.track("claude", "claude-haiku-4-5-20251001", 500, 500)

        monthly = await tracker.get_monthly_spend()
        assert monthly > 0

        await tracker.close()


# =========================================================================
# Tests: router.py
# =========================================================================


class TestRouter:
    """Tests for Router."""

    def test_estimate_complexity_simple(self) -> None:
        """Short messages without indicators are 'simple'."""
        assert _estimate_complexity("hi") == "simple"
        assert _estimate_complexity("hello there") == "simple"

    def test_estimate_complexity_complex_keyword(self) -> None:
        """Messages with complexity indicators are 'complex'."""
        assert _estimate_complexity("analyze this data") == "complex"
        assert _estimate_complexity("explain quantum physics") == "complex"
        assert _estimate_complexity("write a poem") == "complex"

    def test_estimate_complexity_long_message(self) -> None:
        """Messages over 200 chars are 'complex'."""
        long_msg = "a " * 120  # 240 chars
        assert _estimate_complexity(long_msg) == "complex"

    @pytest.mark.asyncio
    async def test_route_keyword_match(self, mock_skill: MagicMock) -> None:
        """Router matches skill by keyword."""
        router = Router(
            default_model="sonnet",
            fast_model="haiku",
        )
        result = await router.route("search and find Python tutorials", [mock_skill])

        assert result.skill is not None
        assert result.skill.name == "web_search"
        assert result.confidence > 0

    @pytest.mark.asyncio
    async def test_route_no_match_returns_default(self, mock_skill: MagicMock) -> None:
        """Router returns no skill when no keywords match."""
        router = Router(
            default_model="sonnet",
            fast_model="haiku",
        )
        result = await router.route("hello", [mock_skill])

        assert result.skill is None
        assert result.model in ("sonnet", "haiku")

    @pytest.mark.asyncio
    async def test_route_selects_default_model_for_simple(
        self, mock_skill: MagicMock
    ) -> None:
        """Router always selects default model (multi-model routing disabled)."""
        router = Router(
            default_model="sonnet",
            fast_model="haiku",
        )
        result = await router.route("hi", [mock_skill])
        assert result.model == "sonnet"

    @pytest.mark.asyncio
    async def test_route_selects_default_model_for_complex(
        self, mock_skill: MagicMock
    ) -> None:
        """Router selects sonnet for complex messages."""
        router = Router(
            default_model="sonnet",
            fast_model="haiku",
        )
        result = await router.route("analyze this complex problem for me", [mock_skill])
        assert result.model == "sonnet"

    @pytest.mark.asyncio
    async def test_route_empty_message(self) -> None:
        """Router handles empty messages."""
        router = Router()
        result = await router.route("", [])
        assert result.skill is None
        assert result.confidence == 0.0


# =========================================================================
# Tests: dispatcher.py
# =========================================================================


class TestNativeDispatcher:
    """Tests for NativeDispatcher."""

    @pytest.mark.asyncio
    async def test_dispatch_text_response(self, mock_provider: MagicMock) -> None:
        """NativeDispatcher returns text when no tool calls."""
        dispatcher = NativeDispatcher()

        result = await dispatcher.dispatch(
            messages=[{"role": "user", "content": "Hello"}],
            tools=None,
            provider=mock_provider,
        )

        assert isinstance(result, DispatchResult)
        assert result.response_text == "Hello, test!"
        assert result.tool_calls == []
        mock_provider.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_parses_tool_calls(self) -> None:
        """NativeDispatcher parses tool_use blocks from response."""
        provider = MagicMock()
        provider.name = "claude"
        provider.complete = AsyncMock(
            return_value=LLMResponse(
                content="Let me search.",
                tool_calls=[
                    {"id": "call_1", "name": "web_search", "input": {"query": "test"}},
                    {"id": "call_2", "name": "read_file", "input": {"path": "/tmp"}},
                ],
                usage=TokenUsage(input_tokens=10, output_tokens=20),
                model="claude-test",
            )
        )

        dispatcher = NativeDispatcher()
        result = await dispatcher.dispatch(
            messages=[{"role": "user", "content": "Search for X"}],
            tools=[{"name": "web_search"}],
            provider=provider,
        )

        assert result.response_text == "Let me search."
        assert len(result.tool_calls) == 2
        assert isinstance(result.tool_calls[0], ToolCall)
        assert result.tool_calls[0].tool_name == "web_search"
        assert result.tool_calls[0].arguments == {"query": "test"}
        assert result.tool_calls[0].call_id == "call_1"
        assert result.tool_calls[1].tool_name == "read_file"

    @pytest.mark.asyncio
    async def test_dispatch_passes_system_prompt(self) -> None:
        """NativeDispatcher forwards system prompt to provider."""
        provider = MagicMock()
        provider.name = "claude"
        provider.complete = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[], usage=TokenUsage())
        )

        dispatcher = NativeDispatcher()
        await dispatcher.dispatch(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            provider=provider,
            system="You are a test agent.",
        )

        call_kwargs = provider.complete.call_args[1]
        assert call_kwargs["system"] == "You are a test agent."


# =========================================================================
# Tests: agent.py
# =========================================================================


class TestAgentBuilder:
    """Tests for Agent.builder() chain."""

    def test_builder_requires_provider(self) -> None:
        """AgentBuilder.build() raises ValueError without provider."""
        with pytest.raises(ValueError, match="requires an LLM provider"):
            Agent.builder().build()

    def test_builder_chain(
        self, mock_provider: MagicMock, soul_dir: Path
    ) -> None:
        """AgentBuilder chain builds an Agent with all components."""
        config = AppConfig()
        registry = ToolRegistry()
        mock_memory = MagicMock()
        mock_skill_reg = MagicMock()
        mock_skill_reg.list_skills = MagicMock(return_value=[])

        agent = (
            Agent.builder()
            .provider(mock_provider)
            .memory(mock_memory)
            .tools(registry)
            .soul_path(soul_dir)
            .skills(mock_skill_reg)
            .config(config)
            .build()
        )

        assert isinstance(agent, Agent)

    def test_builder_defaults(self, mock_provider: MagicMock, soul_dir: Path) -> None:
        """AgentBuilder uses sensible defaults for optional components."""
        agent = (
            Agent.builder()
            .provider(mock_provider)
            .soul_path(soul_dir)
            .build()
        )
        assert isinstance(agent, Agent)


class TestAgent:
    """Tests for Agent.process()."""

    @pytest.mark.asyncio
    async def test_process_returns_response(
        self, mock_provider: MagicMock, soul_dir: Path
    ) -> None:
        """Agent.process() returns LLM response text."""
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(
            return_value=DispatchResult(
                response_text="Hi there!",
                tool_calls=[],
                raw_response=LLMResponse(
                    content="Hi there!",
                    tool_calls=[],
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                    model="test",
                ),
            )
        )

        agent = (
            Agent.builder()
            .provider(mock_provider)
            .dispatcher(mock_dispatcher)
            .soul_path(soul_dir)
            .build()
        )

        msg = IncomingMessage(user_id="user1", text="Hello", channel="telegram")
        response = await agent.process(msg)

        assert response == "Hi there!"
        mock_dispatcher.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_with_memory(
        self, mock_provider: MagicMock, soul_dir: Path
    ) -> None:
        """Agent.process() loads memories and saves conversation."""
        mock_memory = MagicMock()
        mock_memory.search = AsyncMock(
            return_value=[{"content": "User likes Python", "type": "preference"}]
        )
        mock_memory.save = AsyncMock(return_value="mem-id-1")

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(
            return_value=DispatchResult(
                response_text="Python is great!",
                tool_calls=[],
                raw_response=LLMResponse(
                    content="Python is great!",
                    usage=TokenUsage(input_tokens=10, output_tokens=5),
                ),
            )
        )

        agent = (
            Agent.builder()
            .provider(mock_provider)
            .dispatcher(mock_dispatcher)
            .memory(mock_memory)
            .soul_path(soul_dir)
            .build()
        )

        msg = IncomingMessage(user_id="user1", text="Tell me about Python")
        response = await agent.process(msg)

        assert response == "Python is great!"
        mock_memory.search.assert_awaited_once()
        mock_memory.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_handles_dispatch_error(
        self, mock_provider: MagicMock, soul_dir: Path
    ) -> None:
        """Agent.process() returns error message on dispatch failure."""
        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("LLM error"))

        agent = (
            Agent.builder()
            .provider(mock_provider)
            .dispatcher(mock_dispatcher)
            .soul_path(soul_dir)
            .build()
        )

        msg = IncomingMessage(user_id="user1", text="Hello")
        response = await agent.process(msg)

        assert "ошибка" in response.lower() or "error" in response.lower()

    @pytest.mark.asyncio
    async def test_process_with_tool_calls(
        self, mock_provider: MagicMock, soul_dir: Path
    ) -> None:
        """Agent.process() executes tool calls and continues conversation."""
        # First dispatch returns a tool call, second returns final text
        call_count = 0

        async def mock_dispatch(**kwargs: Any) -> DispatchResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return DispatchResult(
                    response_text="Let me search.",
                    tool_calls=[
                        ToolCall(
                            tool_name="web_search",
                            arguments={"query": "test"},
                            call_id="call_1",
                        )
                    ],
                    raw_response=LLMResponse(
                        content="Let me search.",
                        usage=TokenUsage(input_tokens=10, output_tokens=5),
                        model="test",
                    ),
                )
            return DispatchResult(
                response_text="I found the answer.",
                tool_calls=[],
                raw_response=LLMResponse(
                    content="I found the answer.",
                    usage=TokenUsage(input_tokens=20, output_tokens=10),
                    model="test",
                ),
            )

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(side_effect=mock_dispatch)

        # Create a tool that can be executed
        mock_tool = MagicMock()
        mock_tool.definition = ToolDefinition(name="web_search", description="Search")
        mock_tool.execute = AsyncMock(
            return_value=ToolResult(success=True, data="Search results here")
        )

        registry = ToolRegistry()
        registry.register(mock_tool)

        agent = (
            Agent.builder()
            .provider(mock_provider)
            .dispatcher(mock_dispatcher)
            .tools(registry)
            .soul_path(soul_dir)
            .build()
        )

        msg = IncomingMessage(user_id="user1", text="Search for test")
        response = await agent.process(msg)

        assert response == "I found the answer."
        assert call_count == 2
        mock_tool.execute.assert_awaited_once()


class TestLoadSoulFiles:
    """Tests for _load_soul_files helper."""

    def test_loads_all_files(self, soul_dir: Path) -> None:
        """Loads and concatenates SOUL.md, OWNER.md, RULES.md."""
        prompt = _load_soul_files(soul_dir)
        assert "I am a test agent." in prompt
        assert "Owner: Tester" in prompt
        assert "Rule 1: Be nice." in prompt

    def test_missing_files_skipped(self, tmp_path: Path) -> None:
        """Missing soul files are skipped, returns default prompt."""
        prompt = _load_soul_files(tmp_path)
        assert "helpful AI assistant" in prompt

    def test_partial_soul_files(self, tmp_path: Path) -> None:
        """Works with only some soul files present."""
        (tmp_path / "SOUL.md").write_text("I am partial.", encoding="utf-8")
        prompt = _load_soul_files(tmp_path)
        assert "I am partial." in prompt
        assert "Owner" not in prompt
