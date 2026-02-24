"""
Email monitor — background inbox checker.

Checks for new unread emails every minute and pushes
fun bro-style notifications to the user via Telegram.

State (last seen email IDs) is persisted to disk so
bot restarts don't cause missed or duplicate notifications.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Callable, Coroutine

from src.tools.email_tool import GmailService

logger = logging.getLogger(__name__)

# State file — survives restarts
STATE_FILE = Path("data/email_monitor_state.json")

# Notification templates (randomized for variety)
_GREETINGS_SINGLE = [
    "Бро, тебе письмо!",
    "Йо, новое письмо на почте!",
    "Эй, тут кто-то написал на мыло!",
    "Письмо пришло, глянь!",
    "На почту прилетело!",
]

_GREETINGS_MULTI = [
    "Бро, тебе {count} новых писем!",
    "Йо, на почту навалило — {count} штук!",
    "Пачка писем пришла — {count}!",
    "{count} новых на почте, глянь!",
]

_ACTION_PROMPT = [
    "Чё делаем? Прочитать, ответить, в спам?",
    "Что с ним делать? Открыть, игнор, спам?",
    "Глянешь или пока забьём?",
    "Читаем или потом?",
]


def _extract_sender_name(from_field: str) -> str:
    """Extract clean sender name from 'Name <email>' format."""
    if "<" in from_field:
        name = from_field.split("<")[0].strip().strip('"')
        if name:
            return name
    # No name, just email
    return from_field.split("@")[0] if "@" in from_field else from_field


class EmailMonitor:
    """Monitors Gmail inbox for new important emails.

    Runs as a scheduled job via APScheduler (every 1 min).
    When new unread emails are found, calls the notify callback
    with a fun bro-style notification.

    State is persisted to disk so bot restarts don't lose track.
    """

    def __init__(
        self,
        gmail: GmailService,
        notify: Callable[[str, str], Coroutine[Any, Any, None]],
        user_id: str = "",
    ) -> None:
        self._gmail = gmail
        self._notify = notify
        self._user_id = user_id
        self._last_seen_ids: set[str] = set()
        self._initialized = False
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state from disk."""
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._last_seen_ids = set(data.get("last_seen_ids", []))
                self._initialized = bool(self._last_seen_ids)
                if self._initialized:
                    logger.info(
                        "Email monitor state loaded: %d known IDs",
                        len(self._last_seen_ids),
                    )
        except Exception as e:
            logger.warning("Failed to load email monitor state: %s", e)

    def _save_state(self) -> None:
        """Persist current state to disk."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {"last_seen_ids": list(self._last_seen_ids)}
            STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning("Failed to save email monitor state: %s", e)

    def _format_notification(self, messages: list[dict[str, Any]]) -> str:
        """Build a fun bro-style notification for new emails."""
        count = len(messages)

        if count == 1:
            msg = messages[0]
            sender = _extract_sender_name(msg["from"])
            subject = msg["subject"] or "(без темы)"
            snippet = msg.get("snippet", "")[:100]

            greeting = random.choice(_GREETINGS_SINGLE)
            action = random.choice(_ACTION_PROMPT)

            lines = [
                f"📨 {greeting}",
                "",
                f"От: {sender}",
                f"Тема: {subject}",
            ]
            if snippet:
                lines.append(f"Превью: {snippet}")
            lines.append("")
            lines.append(action)
            return "\n".join(lines)
        else:
            greeting = random.choice(_GREETINGS_MULTI).format(count=count)
            lines = [f"📨 {greeting}", ""]

            for i, msg in enumerate(messages[:5], 1):
                sender = _extract_sender_name(msg["from"])
                subject = msg["subject"] or "(без темы)"
                lines.append(f"{i}. {sender} — \"{subject}\"")

            if count > 5:
                lines.append(f"   ...и ещё {count - 5}")

            lines.append("")
            lines.append("Какое открыть? Или все в спам? 😏")
            return "\n".join(lines)

    async def check(self) -> None:
        """Check for new unread emails and notify if found."""
        if not self._gmail.available:
            return

        try:
            messages = await self._gmail.list_messages(
                query="is:unread", max_results=10
            )

            current_ids = {msg["id"] for msg in messages}

            # First run (no persisted state) — just record, don't spam
            if not self._initialized:
                self._last_seen_ids = current_ids
                self._initialized = True
                self._save_state()
                logger.info(
                    "Email monitor initialized: %d unread emails", len(current_ids)
                )
                return

            # Find truly new emails (not seen before)
            new_ids = current_ids - self._last_seen_ids
            if not new_ids:
                # Update state: remove IDs that are no longer unread
                if self._last_seen_ids != current_ids:
                    self._last_seen_ids = current_ids
                    self._save_state()
                return

            # Build fun notification
            new_messages = [m for m in messages if m["id"] in new_ids]
            text = self._format_notification(new_messages)

            if self._user_id:
                await self._notify(self._user_id, text)
                logger.info("Email notification sent: %d new emails", len(new_ids))

            # Update state
            self._last_seen_ids = current_ids
            self._save_state()

        except Exception as e:
            logger.error("Email monitor check failed: %s", e)
