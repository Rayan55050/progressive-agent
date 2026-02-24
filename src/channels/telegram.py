"""
Telegram channel — aiogram 3 bot.

Features:
- Text message handling
- Voice message handling (download + pass to STT)
- Draft/progressive updates (streaming via edit_message)
- Deny-by-default whitelist
- /start command
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart

import re

from src.channels.base import IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)


def _prepare_for_telegram(text: str) -> str:
    """Convert LLM output to Telegram-compatible Markdown.

    Telegram legacy Markdown uses single * for bold, not double **.
    Ensures all formatting entities are properly closed to avoid parse errors.

    Args:
        text: Raw text from LLM.

    Returns:
        Telegram-compatible text.
    """
    # Remove Markdown headers (# ## ###)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove horizontal rules (--- or ***)
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\*{3,}$", "", text, flags=re.MULTILINE)
    # Convert **bold** to *bold* (Telegram legacy Markdown uses single *)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Convert - list items to bullet points (cleaner in Telegram)
    text = re.sub(r"^- ", "• ", text, flags=re.MULTILINE)
    # Replace em-dashes and en-dashes with comma or colon
    text = text.replace(" — ", ", ")
    text = text.replace(" – ", ", ")
    text = text.replace("—", ", ")
    text = text.replace("–", ", ")
    # Strip quotes from inside markdown link URLs: [text]("url") → [text](url)
    # LLM sometimes wraps URLs in quotes which breaks Telegram links
    def _clean_md_link(m: re.Match) -> str:
        label = m.group(1)
        url = m.group(2)
        # Strip all quote types from URL
        for ch in ['"', "'", '`', '\u201c', '\u201d', '\u2018', '\u2019']:
            url = url.strip(ch)
        url = url.replace("%22", "").replace("%27", "")
        return f"[{label}]({url})"

    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', _clean_md_link, text)

    # Clean up excessive blank lines (max 2 in a row)
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # Fix unclosed Markdown entities (bold, italic, code, links)
    # This prevents "can't parse entities" errors from Telegram
    text = _fix_unclosed_entities(text)

    return text.strip()


def _fix_unclosed_entities(text: str) -> str:
    """Ensure all Markdown formatting entities are properly paired.

    Telegram rejects messages with unclosed *, `, _ or [] entities.
    This function strips unpaired markers rather than letting Telegram error out.
    """
    # Fix unclosed inline code (backticks)
    # First handle triple backticks (code blocks)
    triple_count = text.count("```")
    if triple_count % 2 != 0:
        text = text + "\n```"

    # For single backticks, count only those NOT inside triple-backtick blocks
    parts = text.split("```")
    for i in range(0, len(parts), 2):  # Only outside code blocks (even indices)
        if i < len(parts):
            single_count = parts[i].count("`")
            if single_count % 2 != 0:
                # Remove the last lone backtick
                idx = parts[i].rfind("`")
                parts[i] = parts[i][:idx] + parts[i][idx + 1:]
    text = "```".join(parts)

    # Fix unclosed bold/italic markers (* and _)
    # Count outside of code blocks
    parts = re.split(r"(`[^`]*`|```[\s\S]*?```)", text)
    for i in range(0, len(parts), 2):
        if i < len(parts):
            chunk = parts[i]
            # Fix unclosed *bold*
            star_count = chunk.count("*")
            if star_count % 2 != 0:
                idx = chunk.rfind("*")
                chunk = chunk[:idx] + chunk[idx + 1:]
            # Fix unclosed _italic_
            under_count = chunk.count("_")
            if under_count % 2 != 0:
                idx = chunk.rfind("_")
                chunk = chunk[:idx] + chunk[idx + 1:]
            parts[i] = chunk
    text = "".join(parts)

    # Fix unclosed markdown links [text](url) — remove broken ones
    text = re.sub(r"\[([^\]]*)\]\([^)]*$", r"\1", text)
    # Remove lone [ without closing ]
    text = re.sub(r"\[([^\]]*?)$", r"\1", text)

    return text


def _extract_forward_info(message: types.Message) -> str | None:
    """Extract forwarded-from context from a Telegram message.

    Returns a human-readable string like "Пересланное от @username"
    or None if the message is not forwarded.
    """
    # forward_from: user object (if privacy allows)
    if message.forward_from:
        user = message.forward_from
        if user.username:
            return f"Пересланное сообщение от @{user.username}"
        name = user.first_name or ""
        if user.last_name:
            name += f" {user.last_name}"
        return f"Пересланное сообщение от {name}".strip()

    # forward_sender_name: string (when user hides their profile via privacy)
    if message.forward_sender_name:
        return f"Пересланное сообщение от {message.forward_sender_name}"

    # forward_from_chat: forwarded from channel/group
    if message.forward_from_chat:
        title = message.forward_from_chat.title or "канал"
        return f"Пересланное сообщение из {title}"

    # forward_date alone means it's forwarded but sender info is hidden
    if message.forward_date:
        return "Пересланное сообщение"

    return None


def _split_message(text: str, max_len: int = 4096) -> list[str]:
    """Split long text into chunks that fit Telegram's message length limit.

    Tries to split at paragraph boundaries, then newlines, then spaces.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at paragraph boundary
        split_pos = text.rfind("\n\n", 0, max_len)
        if split_pos == -1 or split_pos < max_len // 2:
            # Try single newline
            split_pos = text.rfind("\n", 0, max_len)
        if split_pos == -1 or split_pos < max_len // 2:
            # Last resort: split at space
            split_pos = text.rfind(" ", 0, max_len)
        if split_pos == -1:
            split_pos = max_len
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    return chunks


class TelegramChannel:
    """Telegram bot channel using aiogram 3.

    Implements the Channel Protocol from src/channels/base.py.
    Handles text messages, voice messages, video notes, /start command,
    deny-by-default whitelist, and draft/progressive updates
    for streaming responses.
    """

    def __init__(
        self,
        bot_token: str,
        allowed_users: list[int] | None = None,
        streaming_chunk_size: int = 50,
        streaming_delay_ms: int = 100,
    ) -> None:
        self._bot = Bot(
            token=bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self._dp = Dispatcher()
        self._router = Router()
        self._queue: asyncio.Queue[IncomingMessage] | None = None
        self._allowed_users: set[int] = set(allowed_users or [])
        self._streaming_chunk_size = streaming_chunk_size
        self._streaming_delay = streaming_delay_ms / 1000.0
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Register message handlers on the router."""

        @self._router.message(CommandStart())
        async def handle_start(message: types.Message) -> None:
            if not message.from_user:
                return

            # Auto-onboarding: if no allowed users configured, first /start sets the owner
            if not self._allowed_users:
                user_id = message.from_user.id
                self._allowed_users.add(user_id)
                logger.info("Auto-onboarding: user %d registered as owner", user_id)

                # Persist to config/agent.toml
                try:
                    self._save_owner_to_config(user_id)
                except Exception as e:
                    logger.error("Failed to save owner ID to config: %s", e)

                first_name = message.from_user.first_name or ""
                await message.answer(
                    f"Привет{', ' + first_name if first_name else ''}! "
                    "Я Progressive Agent — твой персональный AI-ассистент.\n\n"
                    "Ты первый, кто написал мне /start, поэтому я зарегистрировал "
                    "тебя как владельца. Теперь я работаю только для тебя.\n\n"
                    "Расскажи мне немного о себе:\n"
                    "• Как тебя зовут?\n"
                    "• В каком городе живёшь?\n"
                    "• Чем занимаешься?\n"
                    "• Какие у тебя интересы?\n\n"
                    "Это поможет мне лучше адаптироваться под тебя."
                )
                return

            if self._is_allowed(message.from_user.id):
                await message.answer(
                    "Progressive Agent запущен. "
                    "Напиши мне что-нибудь или отправь голосовое сообщение."
                )
            else:
                await message.answer(
                    "Привет! Я Progressive Agent. Чем могу помочь?"
                )

        @self._router.message(Command("restart"))
        async def handle_restart(message: types.Message) -> None:
            if not message.from_user or not self._is_allowed(message.from_user.id):
                return
            await message.answer("♻️ Перезапускаюсь, бро...")
            logger.info("Restart requested by user %s", message.from_user.id)
            # Give 1s for message to actually send, then exit
            # Watchdog sees exit code 42 → restarts immediately
            await asyncio.sleep(1)
            os._exit(42)

        @self._router.message(F.voice)
        async def handle_voice(message: types.Message) -> None:
            if not message.from_user:
                return
            is_owner = self._is_allowed(message.from_user.id)
            if not is_owner:
                if self._queue is not None:
                    await self._queue.put(
                        IncomingMessage(
                            user_id=str(message.from_user.id),
                            text="[Stranger sent a voice message]",
                            channel="telegram",
                            message_id=str(message.message_id),
                            is_owner=False,
                            raw=message,
                        )
                    )
                return
            voice = message.voice
            file = await self._bot.get_file(voice.file_id)
            if not file.file_path:
                logger.warning("Voice file_path is None (file too large?), file_id=%s", voice.file_id)
                return
            temp_dir = tempfile.mkdtemp()
            file_path = Path(temp_dir) / f"{voice.file_id}.ogg"
            await self._bot.download_file(file.file_path, destination=file_path)

            if self._queue is not None:
                await self._queue.put(
                    IncomingMessage(
                        user_id=str(message.from_user.id),
                        voice_file_path=file_path,
                        forward_info=_extract_forward_info(message),
                        channel="telegram",
                        message_id=str(message.message_id),
                        raw=message,
                    )
                )

        @self._router.message(F.audio)
        async def handle_audio(message: types.Message) -> None:
            """Handle audio files (MP3, M4A — music, podcasts)."""
            if not message.from_user:
                return
            is_owner = self._is_allowed(message.from_user.id)
            if not is_owner:
                if self._queue is not None:
                    await self._queue.put(
                        IncomingMessage(
                            user_id=str(message.from_user.id),
                            text="[Stranger sent an audio file]",
                            channel="telegram",
                            message_id=str(message.message_id),
                            is_owner=False,
                            raw=message,
                        )
                    )
                return
            audio = message.audio
            file = await self._bot.get_file(audio.file_id)
            if not file.file_path:
                logger.warning("Audio file_path is None, file_id=%s", audio.file_id)
                return
            ext = Path(audio.file_name).suffix if audio.file_name else ".mp3"
            temp_dir = tempfile.mkdtemp()
            file_path = Path(temp_dir) / f"{audio.file_id}{ext}"
            await self._bot.download_file(file.file_path, destination=file_path)

            caption = message.caption or ""
            audio_info = ""
            if audio.title:
                audio_info += f" title={audio.title}"
            if audio.performer:
                audio_info += f" artist={audio.performer}"

            if self._queue is not None:
                await self._queue.put(
                    IncomingMessage(
                        user_id=str(message.from_user.id),
                        text=caption if caption else None,
                        audio_file_path=file_path,
                        forward_info=_extract_forward_info(message),
                        channel="telegram",
                        message_id=str(message.message_id),
                        raw=message,
                    )
                )

        @self._router.message(F.video_note)
        async def handle_video_note(message: types.Message) -> None:
            if not message.from_user:
                return
            is_owner = self._is_allowed(message.from_user.id)
            if not is_owner:
                if self._queue is not None:
                    await self._queue.put(
                        IncomingMessage(
                            user_id=str(message.from_user.id),
                            text="[Stranger sent a video note]",
                            channel="telegram",
                            message_id=str(message.message_id),
                            is_owner=False,
                            raw=message,
                        )
                    )
                return

            vn = message.video_note
            # Download the video note (MP4)
            file = await self._bot.get_file(vn.file_id)
            if not file.file_path:
                logger.warning("Video note file_path is None, file_id=%s", vn.file_id)
                return
            temp_dir = tempfile.mkdtemp()
            file_path = Path(temp_dir) / f"{vn.file_id}.mp4"
            await self._bot.download_file(file.file_path, destination=file_path)

            # Download thumbnail as image for Vision (if available)
            thumb_path: Path | None = None
            if vn.thumbnail:
                try:
                    thumb_file = await self._bot.get_file(vn.thumbnail.file_id)
                    thumb_path = Path(temp_dir) / f"{vn.file_id}_thumb.jpg"
                    await self._bot.download_file(
                        thumb_file.file_path, destination=thumb_path,
                    )
                except Exception as e:
                    logger.debug("Failed to download video_note thumbnail: %s", e)

            if self._queue is not None:
                await self._queue.put(
                    IncomingMessage(
                        user_id=str(message.from_user.id),
                        video_note_file_path=file_path,
                        photo_file_path=thumb_path,  # thumbnail for Vision
                        forward_info=_extract_forward_info(message),
                        channel="telegram",
                        message_id=str(message.message_id),
                        raw=message,
                    )
                )

        @self._router.message(F.document)
        async def handle_document(message: types.Message) -> None:
            if not message.from_user:
                return
            is_owner = self._is_allowed(message.from_user.id)
            if not is_owner:
                if self._queue is not None:
                    await self._queue.put(
                        IncomingMessage(
                            user_id=str(message.from_user.id),
                            text="[Stranger sent a file]",
                            channel="telegram",
                            message_id=str(message.message_id),
                            is_owner=False,
                            raw=message,
                        )
                    )
                return
            doc = message.document
            file = await self._bot.get_file(doc.file_id)
            if not file.file_path:
                logger.warning("Document file_path is None (file too large?), file_id=%s", doc.file_id)
                return
            temp_dir = tempfile.mkdtemp()
            # Keep original filename for clarity
            filename = doc.file_name or f"file_{doc.file_id}"
            file_path = Path(temp_dir) / filename
            await self._bot.download_file(file.file_path, destination=file_path)

            if self._queue is not None:
                await self._queue.put(
                    IncomingMessage(
                        user_id=str(message.from_user.id),
                        text=message.caption,  # may be None
                        document_file_path=file_path,
                        document_file_name=filename,
                        forward_info=_extract_forward_info(message),
                        channel="telegram",
                        message_id=str(message.message_id),
                        raw=message,
                    )
                )

        @self._router.message(F.photo)
        async def handle_photo(message: types.Message) -> None:
            if not message.from_user:
                return
            is_owner = self._is_allowed(message.from_user.id)
            if not is_owner:
                if self._queue is not None:
                    await self._queue.put(
                        IncomingMessage(
                            user_id=str(message.from_user.id),
                            text="[Stranger sent a photo]",
                            channel="telegram",
                            message_id=str(message.message_id),
                            is_owner=False,
                            raw=message,
                        )
                    )
                return
            # Largest resolution is the last element
            photo = message.photo[-1]
            file = await self._bot.get_file(photo.file_id)
            if not file.file_path:
                logger.warning("Photo file_path is None, file_id=%s", photo.file_id)
                return
            temp_dir = tempfile.mkdtemp()
            file_path = Path(temp_dir) / f"{photo.file_id}.jpg"
            await self._bot.download_file(file.file_path, destination=file_path)

            if self._queue is not None:
                await self._queue.put(
                    IncomingMessage(
                        user_id=str(message.from_user.id),
                        text=message.caption,  # may be None
                        photo_file_path=file_path,
                        forward_info=_extract_forward_info(message),
                        channel="telegram",
                        message_id=str(message.message_id),
                        raw=message,
                    )
                )

        @self._router.message(F.text)
        async def handle_text(message: types.Message) -> None:
            if not message.from_user:
                return
            is_owner = self._is_allowed(message.from_user.id)
            if self._queue is not None:
                await self._queue.put(
                    IncomingMessage(
                        user_id=str(message.from_user.id),
                        text=message.text,
                        forward_info=_extract_forward_info(message),
                        channel="telegram",
                        message_id=str(message.message_id),
                        is_owner=is_owner,
                        raw=message,
                    )
                )

        self._dp.include_router(self._router)

    @staticmethod
    def _save_owner_to_config(user_id: int) -> None:
        """Save the owner's Telegram ID to config/agent.toml.

        Called once during auto-onboarding when no allowed_users are configured.
        """
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "agent.toml"
        if not config_path.exists():
            logger.warning("config/agent.toml not found at %s", config_path)
            return

        content = config_path.read_text(encoding="utf-8")
        # Replace empty allowed_users with the new owner ID
        import re as _re
        new_content = _re.sub(
            r"allowed_users\s*=\s*\[\s*\]",
            f"allowed_users = [{user_id}]",
            content,
        )
        if new_content != content:
            config_path.write_text(new_content, encoding="utf-8")
            logger.info("Saved owner ID %d to %s", user_id, config_path)
        else:
            logger.warning("Could not find 'allowed_users = []' in config to update")

    def _is_allowed(self, user_id: int) -> bool:
        """Check if user is in the whitelist.

        If the whitelist is empty, all users are allowed (dev mode).

        Args:
            user_id: Telegram user ID.

        Returns:
            True if the user is allowed to interact with the bot.
        """
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    async def start(self, queue: asyncio.Queue[IncomingMessage]) -> None:
        """Start the Telegram bot polling.

        Incoming messages are pushed into the provided queue.

        Args:
            queue: Shared asyncio queue for incoming messages.
        """
        self._queue = queue
        logger.info("Starting Telegram bot...")
        await self._dp.start_polling(self._bot)

    async def stop(self) -> None:
        """Stop the Telegram bot and close the session."""
        await self._dp.stop_polling()
        await self._bot.session.close()
        logger.info("Telegram bot stopped")

    async def send_typing(self, user_id: str) -> None:
        """Send 'typing...' indicator to user (native Telegram animation)."""
        await self._bot.send_chat_action(
            chat_id=int(user_id), action=ChatAction.TYPING
        )

    async def send_record_video_note(self, user_id: str) -> None:
        """Send 'recording video note...' indicator (circle animation)."""
        await self._bot.send_chat_action(
            chat_id=int(user_id), action=ChatAction.RECORD_VIDEO_NOTE
        )

    async def send(self, message: OutgoingMessage) -> str:
        """Send a message to a user.

        Preprocesses text for Telegram Markdown compatibility.
        Falls back to plain text if Markdown parsing fails.

        Args:
            message: Outgoing message with user_id, text, and optional parse_mode.

        Returns:
            The sent message ID as a string.
        """
        prepared_text = _prepare_for_telegram(message.text)
        if not prepared_text:
            logger.warning("Prepared text is empty, using fallback")
            prepared_text = "..."

        chunks = _split_message(prepared_text)
        last_msg_id = ""
        for chunk in chunks:
            try:
                result = await self._bot.send_message(
                    chat_id=int(message.user_id),
                    text=chunk,
                    parse_mode=message.parse_mode,
                )
            except Exception:
                # Markdown parsing failed — send as plain text
                logger.warning("Markdown send failed, retrying as plain text")
                result = await self._bot.send_message(
                    chat_id=int(message.user_id),
                    text=chunk,
                    parse_mode=None,
                )
            last_msg_id = str(result.message_id)
        return last_msg_id

    async def send_file(
        self, user_id: str, file_path: Path, caption: str = ""
    ) -> None:
        """Send a file to a user.

        Args:
            user_id: Telegram user ID as string.
            file_path: Path to the file to send.
            caption: Optional caption for the document.
        """
        document = types.FSInputFile(path=str(file_path))
        await self._bot.send_document(
            chat_id=int(user_id), document=document, caption=caption
        )

    async def send_audio(
        self, user_id: str, file_path: Path, caption: str = '',
        title: str = '', performer: str = ''
    ) -> None:
        audio = types.FSInputFile(path=str(file_path))
        kwargs: dict = {
            'chat_id': int(user_id),
            'audio': audio,
        }
        if caption:
            kwargs['caption'] = caption
        if title:
            kwargs['title'] = title
        if performer:
            kwargs['performer'] = performer
        await self._bot.send_audio(**kwargs)

    async def draft_update(
        self, user_id: str, message_id: str, text: str
    ) -> None:
        """Update an existing message (for streaming/progressive updates).

        Handles Telegram rate limits and unchanged content gracefully.
        Falls back to plain text if Markdown parsing fails.

        Args:
            user_id: Telegram user ID as string.
            message_id: ID of the message to edit.
            text: New text content for the message.
        """
        prepared = _prepare_for_telegram(text) if text else "..."
        if not prepared:
            prepared = "..."
        try:
            await self._bot.edit_message_text(
                chat_id=int(user_id),
                message_id=int(message_id),
                text=prepared,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            err_str = str(e).lower()
            if "message is not modified" in err_str:
                return
            # Try again without markdown if parsing failed (explicit None overrides default)
            try:
                await self._bot.edit_message_text(
                    chat_id=int(user_id),
                    message_id=int(message_id),
                    text=prepared,
                    parse_mode=None,
                )
            except Exception as e2:
                if "message is not modified" not in str(e2).lower():
                    logger.warning("Failed to update draft message: %s", e2)

    async def delete_message(self, user_id: str, message_id: str) -> None:
        """Delete a message from the chat.

        Args:
            user_id: Telegram user ID as string.
            message_id: ID of the message to delete.
        """
        try:
            await self._bot.delete_message(
                chat_id=int(user_id),
                message_id=int(message_id),
            )
        except Exception as e:
            logger.debug("Failed to delete message %s: %s", message_id, e)

    async def send_video_note(
        self, user_id: str, file_path: Path, duration: int | None = None
    ) -> str:
        """Send a video note (circle) to a user.

        Args:
            user_id: Telegram user ID as string.
            file_path: Path to MP4 video file (square, H.264).
            duration: Video duration in seconds (optional).

        Returns:
            The sent message ID as a string.
        """
        video = types.FSInputFile(path=str(file_path))
        kwargs: dict = {
            "chat_id": int(user_id),
            "video_note": video,
            "length": 384,
        }
        if duration:
            kwargs["duration"] = duration
        result = await self._bot.send_video_note(**kwargs)
        return str(result.message_id)

    async def send_voice(
        self, user_id: str, file_path: Path, caption: str = ""
    ) -> str:
        """Send a voice message to a user.

        Args:
            user_id: Telegram user ID as string.
            file_path: Path to audio file (MP3/OGG).
            caption: Optional caption.

        Returns:
            The sent message ID as a string.
        """
        voice = types.FSInputFile(path=str(file_path))
        result = await self._bot.send_voice(
            chat_id=int(user_id), voice=voice, caption=caption
        )
        return str(result.message_id)

    async def health_check(self) -> bool:
        """Check if the Telegram bot is reachable.

        Returns:
            True if the bot API responds successfully, False otherwise.
        """
        try:
            me = await self._bot.get_me()
            return me is not None
        except Exception:
            return False
