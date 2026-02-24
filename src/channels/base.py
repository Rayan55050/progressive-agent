"""
Базовые интерфейсы для каналов связи.

Все каналы (Telegram, Web и т.д.) реализуют эти протоколы.
Паттерн из ZeroClaw: asyncio.Queue pipeline — все каналы пушат
в одну очередь, Agent потребляет.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Protocol, runtime_checkable


@dataclass
class IncomingMessage:
    """Входящее сообщение из любого канала."""

    user_id: str
    text: str | None = None
    voice_file_path: Path | None = None
    audio_file_path: Path | None = None      # Аудиофайл (MP3/M4A — музыка, подкасты)
    document_file_path: Path | None = None  # Прикреплённый файл (doc, pdf, ...)
    document_file_name: str | None = None   # Оригинальное имя файла
    photo_file_path: Path | None = None     # Прикреплённое фото
    video_note_file_path: Path | None = None  # Видео-кружок (MP4)
    image_base64: str | None = None         # Base64-encoded image data (for vision)
    image_media_type: str | None = None     # MIME type: "image/jpeg", "image/png", etc.
    forward_info: str | None = None         # "Пересланное от @username" (контекст пересылки)
    channel: str = "telegram"  # "telegram", "web"
    timestamp: datetime = field(default_factory=datetime.now)
    message_id: str = ""
    is_owner: bool = True  # False = stranger (troll mode)
    raw: Any = None  # Оригинальный объект сообщения (для reply)


@dataclass
class OutgoingMessage:
    """Исходящее сообщение для отправки в канал."""

    user_id: str
    text: str
    reply_to: str | None = None  # message_id для ответа
    parse_mode: str = "Markdown"


@runtime_checkable
class Channel(Protocol):
    """Протокол канала связи.

    Каждый канал (Telegram, Web) реализует этот интерфейс.
    Сообщения от всех каналов попадают в единую asyncio.Queue.
    """

    async def start(self, queue: asyncio.Queue[IncomingMessage]) -> None:
        """Запустить канал. Входящие сообщения класть в queue."""
        ...

    async def stop(self) -> None:
        """Остановить канал."""
        ...

    async def send(self, message: OutgoingMessage) -> str:
        """Отправить сообщение. Возвращает message_id."""
        ...

    async def send_file(self, user_id: str, file_path: Path, caption: str = "") -> None:
        """Отправить файл пользователю."""
        ...

    async def draft_update(self, user_id: str, message_id: str, text: str) -> None:
        """Обновить сообщение (для стриминга ответов).

        Паттерн из ZeroClaw: draft/progressive updates.
        Отправляем пустое сообщение, затем редактируем его
        по мере генерации ответа.
        """
        ...

    async def health_check(self) -> bool:
        """Проверка работоспособности канала."""
        ...
