"""
Gmail API tools for Progressive Agent.

Provides three LLM-callable tools:
- email_inbox: list / search emails
- email_read: read full email by ID
- email_compose: draft or send email

OAuth2 flow:
1. Put gmail_credentials.json in config/ (from Google Cloud Console)
2. Run: python -m src.tools.email_tool --setup
3. Authorize in the browser → token saved to data/gmail_token.json
4. After that, token auto-refreshes
"""

from __future__ import annotations

import asyncio
import base64
import logging
from email.mime.text import MIMEText
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Timeout for Gmail API calls (seconds).  Prevents process hangs if
# Google's servers are slow or the network is flaky.
GMAIL_HTTP_TIMEOUT = 30       # per-HTTP-request timeout (httplib2)
GMAIL_OPERATION_TIMEOUT = 60  # overall async operation timeout

# Gmail API scopes: read + send + modify (labels)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailService:
    """Shared Gmail API service with lazy OAuth2 authentication.

    Handles token loading, refresh, and provides the underlying
    Google API service object.
    """

    def __init__(
        self,
        credentials_path: str = "config/gmail_credentials.json",
        token_path: str = "data/gmail_token.json",
    ) -> None:
        self._credentials_path = Path(credentials_path)
        self._token_path = Path(token_path)
        self._service: Any = None
        self._available = False

    @property
    def available(self) -> bool:
        """Check if Gmail is configured (token exists)."""
        return self._token_path.exists()

    def _get_service(self) -> Any:
        """Get or create the Gmail API service (synchronous)."""
        if self._service is not None:
            return self._service

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds: Credentials | None = None

        # Load saved token
        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._token_path), SCOPES
            )

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._token_path.write_text(creds.to_json())
                logger.info("Gmail token refreshed")
            except Exception as e:
                logger.error("Gmail token refresh failed: %s", e)
                creds = None

        if not creds or not creds.valid:
            logger.warning(
                "Gmail not authenticated. Run: python -m src.tools.email_tool --setup"
            )
            return None

        # Build with HTTP timeout to prevent hangs on network issues
        import httplib2
        import google_auth_httplib2
        http = httplib2.Http(timeout=GMAIL_HTTP_TIMEOUT)
        authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
        self._service = build("gmail", "v1", http=authed_http)
        self._available = True
        logger.info("Gmail API service initialized (timeout=%ds)", GMAIL_HTTP_TIMEOUT)
        return self._service

    async def _svc(self) -> Any:
        """Get service in async context (with timeout)."""
        return await asyncio.wait_for(
            asyncio.to_thread(self._get_service),
            timeout=GMAIL_OPERATION_TIMEOUT,
        )

    def run_setup(self) -> bool:
        """Interactive OAuth2 setup — run from terminal.

        Opens browser for Google authorization.
        Saves token to token_path.

        Returns:
            True if setup succeeded.
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self._credentials_path.exists():
            print(
                f"ERROR: Credentials file not found: {self._credentials_path}\n"
                "Download it from Google Cloud Console:\n"
                "  1. Go to https://console.cloud.google.com/apis/credentials\n"
                "  2. Create OAuth 2.0 Client ID (Desktop application)\n"
                "  3. Download JSON and save as config/gmail_credentials.json"
            )
            return False

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._credentials_path), SCOPES
        )
        creds = flow.run_local_server(port=0)

        # Ensure data directory exists
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(creds.to_json())
        print(f"Gmail authorized! Token saved to {self._token_path}")
        return True

    # ----- API methods -----

    async def list_messages(
        self,
        query: str = "",
        max_results: int = 10,
        label: str = "INBOX",
    ) -> list[dict[str, Any]]:
        """List emails matching query.

        Args:
            query: Gmail search query (e.g. "is:unread", "from:boss@co.com").
            max_results: Maximum emails to return.
            label: Gmail label (INBOX, SENT, DRAFT, etc.).

        Returns:
            List of email summaries (id, from, subject, date, snippet, is_unread).
        """
        svc = await self._svc()
        if svc is None:
            return []

        def _list() -> list[dict[str, Any]]:
            results = (
                svc.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    labelIds=[label] if label else None,
                    maxResults=max_results,
                )
                .execute()
            )
            messages = results.get("messages", [])
            if not messages:
                return []

            summaries = []
            for msg_stub in messages:
                msg = (
                    svc.users()
                    .messages()
                    .get(userId="me", id=msg_stub["id"], format="metadata",
                         metadataHeaders=["From", "Subject", "Date"])
                    .execute()
                )
                headers = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                summaries.append({
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", "(no subject)"),
                    "date": headers.get("Date", ""),
                    "snippet": msg.get("snippet", ""),
                    "is_unread": "UNREAD" in msg.get("labelIds", []),
                })
            return summaries

        return await asyncio.wait_for(
            asyncio.to_thread(_list), timeout=GMAIL_OPERATION_TIMEOUT,
        )

    async def get_message(self, msg_id: str) -> dict[str, Any] | None:
        """Get full email content by ID.

        Args:
            msg_id: Gmail message ID.

        Returns:
            Dict with full email data (from, to, subject, date, body).
        """
        svc = await self._svc()
        if svc is None:
            return None

        def _get() -> dict[str, Any] | None:
            msg = (
                svc.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            body = _extract_body(msg.get("payload", {}))
            return {
                "id": msg["id"],
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "date": headers.get("Date", ""),
                "body": body,
                "labels": msg.get("labelIds", []),
                "snippet": msg.get("snippet", ""),
            }

        return await asyncio.wait_for(
            asyncio.to_thread(_get), timeout=GMAIL_OPERATION_TIMEOUT,
        )

    async def send_email(
        self, to: str, subject: str, body: str
    ) -> dict[str, Any] | None:
        """Send an email.

        Args:
            to: Recipient email address.
            subject: Email subject.
            body: Email body (plain text).

        Returns:
            Sent message metadata or None on failure.
        """
        svc = await self._svc()
        if svc is None:
            return None

        def _send() -> dict[str, Any]:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            return (
                svc.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )

        return await asyncio.wait_for(
            asyncio.to_thread(_send), timeout=GMAIL_OPERATION_TIMEOUT,
        )

    async def create_draft(
        self, to: str, subject: str, body: str
    ) -> dict[str, Any] | None:
        """Create a draft email.

        Args:
            to: Recipient email.
            subject: Subject line.
            body: Email body.

        Returns:
            Draft metadata or None.
        """
        svc = await self._svc()
        if svc is None:
            return None

        def _draft() -> dict[str, Any]:
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            return (
                svc.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw}})
                .execute()
            )

        return await asyncio.wait_for(
            asyncio.to_thread(_draft), timeout=GMAIL_OPERATION_TIMEOUT,
        )

    async def get_unread_count(self) -> int:
        """Get count of unread emails in inbox."""
        svc = await self._svc()
        if svc is None:
            return 0

        def _count() -> int:
            results = (
                svc.users()
                .messages()
                .list(userId="me", q="is:unread", labelIds=["INBOX"], maxResults=1)
                .execute()
            )
            return results.get("resultSizeEstimate", 0)

        return await asyncio.wait_for(
            asyncio.to_thread(_count), timeout=GMAIL_OPERATION_TIMEOUT,
        )


def _extract_body(payload: dict[str, Any]) -> str:
    """Extract plain text body from Gmail message payload.

    Handles both simple and multipart messages.
    """
    # Simple message (no parts)
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart message — look for text/plain
    parts = payload.get("parts", [])
    for part in parts:
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(
                part["body"]["data"]
            ).decode("utf-8", errors="replace")

    # Fallback: try text/html
    for part in parts:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            html = base64.urlsafe_b64decode(
                part["body"]["data"]
            ).decode("utf-8", errors="replace")
            # Strip HTML tags (basic)
            import re
            text = re.sub(r"<[^>]+>", "", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text

    # Nested multipart
    for part in parts:
        if "parts" in part:
            result = _extract_body(part)
            if result:
                return result

    return "(email body could not be extracted)"


# ---------------------------------------------------------------------------
# Tool: email_inbox — list / search emails
# ---------------------------------------------------------------------------


class EmailInboxTool:
    """List or search emails in Gmail inbox."""

    def __init__(self, gmail: GmailService) -> None:
        self._gmail = gmail

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="email_inbox",
            description=(
                "List or search emails in Gmail inbox. "
                "Use query for Gmail search syntax (e.g. 'is:unread', "
                "'from:boss@company.com', 'subject:invoice', 'newer_than:1d'). "
                "Empty query returns recent emails."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Gmail search query (empty = recent emails)",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of emails to return (1-50)",
                    required=False,
                    default=10,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        max_results = min(int(kwargs.get("max_results", 10)), 50)

        if not self._gmail.available:
            return ToolResult(
                success=False,
                error="Gmail не настроен. Нужна авторизация: python -m src.tools.email_tool --setup",
            )

        try:
            messages = await self._gmail.list_messages(
                query=query, max_results=max_results
            )
            if not messages:
                return ToolResult(success=True, data="Писем не найдено.")

            lines = []
            for msg in messages:
                unread = " [NEW]" if msg["is_unread"] else ""
                lines.append(
                    f"ID: {msg['id']}{unread}\n"
                    f"  От: {msg['from']}\n"
                    f"  Тема: {msg['subject']}\n"
                    f"  Дата: {msg['date']}\n"
                    f"  Превью: {msg['snippet'][:100]}"
                )
            return ToolResult(success=True, data="\n\n".join(lines))
        except Exception as e:
            logger.error("email_inbox failed: %s", e)
            return ToolResult(success=False, error=f"Gmail error: {e}")


# ---------------------------------------------------------------------------
# Tool: email_read — read full email by ID
# ---------------------------------------------------------------------------


class EmailReadTool:
    """Read a specific email by its ID."""

    def __init__(self, gmail: GmailService) -> None:
        self._gmail = gmail

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="email_read",
            description=(
                "Read the full content of a specific email by its ID. "
                "Use email_inbox first to find the message ID."
            ),
            parameters=[
                ToolParameter(
                    name="message_id",
                    type="string",
                    description="Gmail message ID (from email_inbox results)",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        msg_id = kwargs.get("message_id", "")
        if not msg_id:
            return ToolResult(success=False, error="message_id is required")

        if not self._gmail.available:
            return ToolResult(
                success=False,
                error="Gmail не настроен. Нужна авторизация: python -m src.tools.email_tool --setup",
            )

        try:
            msg = await self._gmail.get_message(msg_id)
            if not msg:
                return ToolResult(success=False, error=f"Email {msg_id} not found")

            body = msg["body"]
            # Truncate very long emails
            if len(body) > 5000:
                body = body[:5000] + "\n\n... (письмо обрезано, слишком длинное)"

            text = (
                f"От: {msg['from']}\n"
                f"Кому: {msg['to']}\n"
                f"Тема: {msg['subject']}\n"
                f"Дата: {msg['date']}\n"
                f"Метки: {', '.join(msg['labels'])}\n"
                f"\n{body}"
            )
            return ToolResult(success=True, data=text)
        except Exception as e:
            logger.error("email_read failed: %s", e)
            return ToolResult(success=False, error=f"Gmail error: {e}")


# ---------------------------------------------------------------------------
# Tool: email_compose — draft or send email
# ---------------------------------------------------------------------------


class EmailComposeTool:
    """Compose and send or draft an email."""

    def __init__(self, gmail: GmailService) -> None:
        self._gmail = gmail

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="email_compose",
            description=(
                "Compose an email. By default creates a DRAFT (safe). "
                "Set action='send' to send immediately. "
                "IMPORTANT: always create a draft first unless the user explicitly says 'send'."
            ),
            parameters=[
                ToolParameter(
                    name="to",
                    type="string",
                    description="Recipient email address",
                    required=True,
                ),
                ToolParameter(
                    name="subject",
                    type="string",
                    description="Email subject line",
                    required=True,
                ),
                ToolParameter(
                    name="body",
                    type="string",
                    description="Email body text",
                    required=True,
                ),
                ToolParameter(
                    name="action",
                    type="string",
                    description="'draft' (default, safe) or 'send' (sends immediately)",
                    required=False,
                    default="draft",
                    enum=["draft", "send"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        to = kwargs.get("to", "")
        subject = kwargs.get("subject", "")
        body = kwargs.get("body", "")
        action = kwargs.get("action", "draft")

        if not to or not subject:
            return ToolResult(success=False, error="'to' and 'subject' are required")

        if not self._gmail.available:
            return ToolResult(
                success=False,
                error="Gmail не настроен. Нужна авторизация: python -m src.tools.email_tool --setup",
            )

        try:
            if action == "send":
                result = await self._gmail.send_email(to, subject, body)
                if result:
                    return ToolResult(
                        success=True,
                        data=f"Письмо отправлено на {to} (ID: {result.get('id', '?')})",
                    )
                return ToolResult(success=False, error="Failed to send email")
            else:
                result = await self._gmail.create_draft(to, subject, body)
                if result:
                    return ToolResult(
                        success=True,
                        data=(
                            f"Черновик создан (ID: {result.get('id', '?')})\n"
                            f"Кому: {to}\nТема: {subject}\n"
                            "Черновик можно найти в Gmail → Drafts"
                        ),
                    )
                return ToolResult(success=False, error="Failed to create draft")
        except Exception as e:
            logger.error("email_compose failed: %s", e)
            return ToolResult(success=False, error=f"Gmail error: {e}")


# ---------------------------------------------------------------------------
# CLI: setup OAuth
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if "--setup" in sys.argv:
        gmail = GmailService()
        gmail.run_setup()
    else:
        print("Usage: python -m src.tools.email_tool --setup")
