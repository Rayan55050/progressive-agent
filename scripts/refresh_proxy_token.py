"""
Refresh CLIProxyAPI OAuth token for Claude.

Uses the refresh_token to get a new access_token without browser interaction.
Can be run standalone (scheduled task) or imported as a module.

Usage:
    python scripts/refresh_proxy_token.py          # refresh + restart proxy
    python scripts/refresh_proxy_token.py --check   # only check, refresh if needed
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("token_refresh")

# Paths
AUTH_DIR = Path.home() / ".cli-proxy-api"
PROXY_EXE = Path(__file__).resolve().parent.parent / "CLIProxyAPI" / "cli-proxy-api.exe"

# Claude OAuth constants (from CLIProxyAPI source)
CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_TOKEN_URL = "https://claude.ai/oauth/token"


def find_token_file() -> Path | None:
    """Find the Claude token file in auth dir."""
    if not AUTH_DIR.exists():
        return None
    for f in AUTH_DIR.glob("claude-*.json"):
        return f
    return None


def load_token(path: Path) -> dict:
    """Load token data from JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def save_token(path: Path, data: dict) -> None:
    """Save token data to JSON file."""
    path.write_text(json.dumps(data), encoding="utf-8")
    logger.info("Token saved to %s", path)


def is_token_expired(data: dict, buffer_minutes: int = 30) -> bool:
    """Check if token is expired or will expire within buffer_minutes."""
    expired_str = data.get("expired", "")
    if not expired_str:
        return True

    try:
        # Parse ISO format with timezone
        expired_dt = datetime.fromisoformat(expired_str)
        now = datetime.now(expired_dt.tzinfo)
        remaining = (expired_dt - now).total_seconds()
        remaining_min = remaining / 60

        if remaining <= 0:
            logger.info("Token expired %d minutes ago", abs(remaining_min))
            return True
        elif remaining_min <= buffer_minutes:
            logger.info("Token expires in %.0f minutes (buffer: %d min), refreshing", remaining_min, buffer_minutes)
            return True
        else:
            logger.info("Token valid for %.0f more minutes", remaining_min)
            return False
    except Exception as e:
        logger.error("Failed to parse expiry date '%s': %s", expired_str, e)
        return True


def refresh_token(refresh_token_value: str) -> dict | None:
    """Exchange refresh_token for new access_token via Claude OAuth."""
    data = urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_value,
        "client_id": CLAUDE_CLIENT_ID,
    }).encode("utf-8")

    req = Request(
        CLAUDE_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            logger.info("Token refreshed successfully")
            return result
    except Exception as e:
        logger.error("Token refresh failed: %s", e)
        return None


def restart_proxy() -> bool:
    """Restart the CLIProxyAPI process."""
    if not PROXY_EXE.exists():
        logger.error("Proxy exe not found: %s", PROXY_EXE)
        return False

    # Kill existing
    try:
        subprocess.run(
            ["taskkill", "/IM", "cli-proxy-api.exe", "/F"],
            capture_output=True, timeout=5,
        )
        time.sleep(2)
    except Exception:
        pass

    # Start new
    try:
        subprocess.Popen(
            [str(PROXY_EXE)],
            cwd=str(PROXY_EXE.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        logger.info("Proxy restarted")
        time.sleep(3)
        return True
    except Exception as e:
        logger.error("Failed to restart proxy: %s", e)
        return False


def do_refresh(check_only: bool = False) -> bool:
    """Main refresh logic.

    Args:
        check_only: if True, only refresh when token is expired/expiring

    Returns:
        True if token is valid after this call
    """
    token_file = find_token_file()
    if not token_file:
        logger.error("No Claude token file found in %s", AUTH_DIR)
        return False

    token_data = load_token(token_file)
    logger.info("Token file: %s (email: %s)", token_file.name, token_data.get("email", "?"))

    # Check if refresh is needed
    if check_only and not is_token_expired(token_data):
        return True

    # Get refresh token
    rt = token_data.get("refresh_token", "")
    if not rt:
        logger.error("No refresh_token in token file")
        return False

    # Refresh
    result = refresh_token(rt)
    if not result:
        return False

    # Update token data
    new_access = result.get("access_token", "")
    new_refresh = result.get("refresh_token", rt)  # Keep old if not returned
    expires_in = result.get("expires_in", 28800)  # default 8 hours

    if not new_access:
        logger.error("No access_token in refresh response: %s", result)
        return False

    now = datetime.now().astimezone()
    from datetime import timedelta
    expired_dt = now + timedelta(seconds=expires_in)

    token_data["access_token"] = new_access
    token_data["refresh_token"] = new_refresh
    token_data["last_refresh"] = now.isoformat()
    token_data["expired"] = expired_dt.isoformat()
    token_data["disabled"] = False

    save_token(token_file, token_data)
    logger.info("New token expires: %s (~%.1f hours)", expired_dt.isoformat(), expires_in / 3600)

    # Restart proxy to pick up new token
    restart_proxy()

    return True


# Async version for use in bot's ProxyMonitor
async def async_refresh_token() -> bool:
    """Async wrapper for token refresh (runs in thread to avoid blocking)."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: do_refresh(check_only=False))


async def async_check_and_refresh() -> bool:
    """Async check-and-refresh (only refreshes if needed)."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: do_refresh(check_only=True))


if __name__ == "__main__":
    check_only = "--check" in sys.argv
    success = do_refresh(check_only=check_only)
    sys.exit(0 if success else 1)
