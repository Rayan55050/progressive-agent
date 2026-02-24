"""
Tests for Telegram channel and STT tool.

Tests the real implementations:
- TelegramChannel (src/channels/telegram.py)
- STTTool (src/tools/stt_tool.py)

External dependencies (aiogram Bot, OpenAI Whisper) are mocked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.channels.base import IncomingMessage, OutgoingMessage
from src.core.tools import ToolResult


# =========================================================================
# Tests: TelegramChannel
# =========================================================================


class TestTelegramChannelCreation:
    """Tests for TelegramChannel initialization and basic operations."""

    @patch("src.channels.telegram.Bot")
    @patch("src.channels.telegram.Dispatcher")
    @patch("src.channels.telegram.Router")
    def test_creation(
        self, mock_router_cls: MagicMock, mock_dp_cls: MagicMock, mock_bot_cls: MagicMock
    ) -> None:
        """TelegramChannel initializes with bot_token."""
        from src.channels.telegram import TelegramChannel

        ch = TelegramChannel(bot_token="123:ABC", allowed_users=[111, 222])
        assert ch is not None
        assert ch._allowed_users == {111, 222}

    @patch("src.channels.telegram.Bot")
    @patch("src.channels.telegram.Dispatcher")
    @patch("src.channels.telegram.Router")
    def test_creation_default_whitelist(
        self, mock_router_cls: MagicMock, mock_dp_cls: MagicMock, mock_bot_cls: MagicMock
    ) -> None:
        """TelegramChannel with no allowed_users has empty set."""
        from src.channels.telegram import TelegramChannel

        ch = TelegramChannel(bot_token="123:ABC")
        assert ch._allowed_users == set()

    @patch("src.channels.telegram.Bot")
    @patch("src.channels.telegram.Dispatcher")
    @patch("src.channels.telegram.Router")
    def test_whitelist_allowed(
        self, mock_router_cls: MagicMock, mock_dp_cls: MagicMock, mock_bot_cls: MagicMock
    ) -> None:
        """Whitelisted users pass the check."""
        from src.channels.telegram import TelegramChannel

        ch = TelegramChannel(bot_token="123:ABC", allowed_users=[111, 222])
        assert ch._is_allowed(111) is True
        assert ch._is_allowed(222) is True
        assert ch._is_allowed(999) is False

    @patch("src.channels.telegram.Bot")
    @patch("src.channels.telegram.Dispatcher")
    @patch("src.channels.telegram.Router")
    def test_empty_whitelist_allows_all(
        self, mock_router_cls: MagicMock, mock_dp_cls: MagicMock, mock_bot_cls: MagicMock
    ) -> None:
        """Empty whitelist allows all users (dev mode)."""
        from src.channels.telegram import TelegramChannel

        ch = TelegramChannel(bot_token="123:ABC", allowed_users=[])
        assert ch._is_allowed(111) is True
        assert ch._is_allowed(999) is True

    @patch("src.channels.telegram.Bot")
    @patch("src.channels.telegram.Dispatcher")
    @patch("src.channels.telegram.Router")
    @pytest.mark.asyncio
    async def test_send_message(
        self, mock_router_cls: MagicMock, mock_dp_cls: MagicMock, mock_bot_cls: MagicMock
    ) -> None:
        """send() delegates to bot.send_message and returns message_id."""
        from src.channels.telegram import TelegramChannel

        ch = TelegramChannel(bot_token="123:ABC")
        # Mock the internal bot's send_message
        ch._bot.send_message = AsyncMock(
            return_value=MagicMock(message_id=42)
        )
        msg = OutgoingMessage(user_id="111", text="Hello!", parse_mode="Markdown")
        result = await ch.send(msg)
        assert result == "42"
        ch._bot.send_message.assert_awaited_once()

    @patch("src.channels.telegram.Bot")
    @patch("src.channels.telegram.Dispatcher")
    @patch("src.channels.telegram.Router")
    @pytest.mark.asyncio
    async def test_draft_update(
        self, mock_router_cls: MagicMock, mock_dp_cls: MagicMock, mock_bot_cls: MagicMock
    ) -> None:
        """draft_update() calls bot.edit_message_text."""
        from src.channels.telegram import TelegramChannel

        ch = TelegramChannel(bot_token="123:ABC")
        ch._bot.edit_message_text = AsyncMock()
        await ch.draft_update(user_id="111", message_id="42", text="Updated")
        ch._bot.edit_message_text.assert_awaited_once()

    @patch("src.channels.telegram.Bot")
    @patch("src.channels.telegram.Dispatcher")
    @patch("src.channels.telegram.Router")
    @pytest.mark.asyncio
    async def test_health_check_success(
        self, mock_router_cls: MagicMock, mock_dp_cls: MagicMock, mock_bot_cls: MagicMock
    ) -> None:
        """health_check() returns True when bot.get_me() succeeds."""
        from src.channels.telegram import TelegramChannel

        ch = TelegramChannel(bot_token="123:ABC")
        ch._bot.get_me = AsyncMock(return_value=MagicMock(id=123))
        result = await ch.health_check()
        assert result is True

    @patch("src.channels.telegram.Bot")
    @patch("src.channels.telegram.Dispatcher")
    @patch("src.channels.telegram.Router")
    @pytest.mark.asyncio
    async def test_health_check_failure(
        self, mock_router_cls: MagicMock, mock_dp_cls: MagicMock, mock_bot_cls: MagicMock
    ) -> None:
        """health_check() returns False on exception."""
        from src.channels.telegram import TelegramChannel

        ch = TelegramChannel(bot_token="123:ABC")
        ch._bot.get_me = AsyncMock(side_effect=Exception("Connection failed"))
        result = await ch.health_check()
        assert result is False


# =========================================================================
# Tests: STTTool
# =========================================================================


class TestSTTTool:
    """Tests for STT (Speech-to-Text) tool using local faster-whisper."""

    @pytest.mark.asyncio
    async def test_execute_success(self, tmp_path: Path) -> None:
        """execute() transcribes audio file via faster-whisper."""
        from src.tools.stt_tool import STTTool

        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")

        tool = STTTool(model_size="base")

        # Mock the internal model
        mock_segment = MagicMock()
        mock_segment.text = "Hello, this is a test transcription."
        mock_info = MagicMock()
        mock_info.language = "ru"
        mock_info.language_probability = 0.95

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        tool._model = mock_model

        result = await tool.execute(file_path=str(audio_file))
        assert result.success is True
        assert result.data == "Hello, this is a test transcription."

    @pytest.mark.asyncio
    async def test_execute_missing_file(self) -> None:
        """execute() returns error when file does not exist."""
        from src.tools.stt_tool import STTTool

        tool = STTTool()
        result = await tool.execute(file_path="/nonexistent/audio.ogg")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_empty_file_path(self) -> None:
        """execute() returns error when file_path is empty."""
        from src.tools.stt_tool import STTTool

        tool = STTTool()
        result = await tool.execute(file_path="")
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_api_error(self, tmp_path: Path) -> None:
        """execute() handles model errors gracefully."""
        from src.tools.stt_tool import STTTool

        audio_file = tmp_path / "voice.ogg"
        audio_file.write_bytes(b"fake audio data")

        tool = STTTool()
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = Exception("Model error")
        tool._model = mock_model

        result = await tool.execute(file_path=str(audio_file))
        assert result.success is False
        assert "failed" in result.error.lower()

    def test_definition(self) -> None:
        """STTTool.definition returns correct schema."""
        from src.tools.stt_tool import STTTool

        tool = STTTool()
        defn = tool.definition
        assert defn.name == "stt"
        param_names = [p.name for p in defn.parameters]
        assert "file_path" in param_names
