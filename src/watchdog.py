"""
Watchdog v2 — Supervisor with health tracking.

Runs `python -m src.main` as a subprocess.
If it exits with non-zero code (crash), waits and restarts.
If it exits with 0 (clean shutdown via Ctrl+C), stops.

v2 additions:
- Health state snapshots to data/watchdog_state.json
- Exponential backoff on repeated crashes (5s -> 10s -> 20s -> 40s -> 60s max)
- Uptime tracking
- Self-update support (exit code 43 = update + restart)

Anti-crash-loop: max 5 restarts in 10 minutes.
If exceeded, waits 5 minutes before resetting the counter.

Usage:
    python -m src.watchdog
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PYTHON = sys.executable
LOG_FILE = PROJECT_ROOT / "data" / "watchdog.log"
STATE_FILE = PROJECT_ROOT / "data" / "watchdog_state.json"

# Crash loop protection
MAX_RESTARTS = 5          # max restarts in the window
WINDOW_SECONDS = 600      # 10 minute window
COOLDOWN_SECONDS = 300    # 5 min cooldown if loop detected

# Restart delays
BASE_RESTART_DELAY = 5    # initial delay (seconds)
MAX_RESTART_DELAY = 60    # max delay after exponential backoff

# Special exit codes
RESTART_EXIT_CODE = 42    # /restart command (instant, no crash counter)
UPDATE_EXIT_CODE = 43     # self-update: git pull + restart


def log(msg: str) -> None:
    """Log to file + stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def save_state(state: dict) -> None:
    """Save health state to JSON file."""
    try:
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def do_self_update() -> bool:
    """Run git pull to update the project. Returns True on success."""
    log("Self-update: running git pull...")
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        log(f"git pull: {result.stdout.strip()}")
        if result.stderr.strip():
            log(f"git pull stderr: {result.stderr.strip()}")
        if result.returncode != 0:
            log(f"git pull failed (code {result.returncode})")
            return False
        log("Self-update complete")
        return True
    except Exception as e:
        log(f"Self-update failed: {e}")
        return False


def main() -> None:
    restart_times: list[float] = []
    consecutive_crashes = 0
    start_time = datetime.now().isoformat()
    total_restarts = 0

    state = {
        "status": "running",
        "started_at": start_time,
        "last_bot_start": None,
        "last_crash": None,
        "total_restarts": 0,
        "consecutive_crashes": 0,
        "uptime_seconds": 0,
        "pid": None,
    }

    log("Watchdog v2 started")
    save_state(state)

    while True:
        # Crash loop detection
        now = time.monotonic()
        restart_times = [t for t in restart_times if now - t < WINDOW_SECONDS]

        if len(restart_times) >= MAX_RESTARTS:
            log(
                f"Crash loop detected ({MAX_RESTARTS} restarts in {WINDOW_SECONDS}s). "
                f"Cooling down for {COOLDOWN_SECONDS}s..."
            )
            state["status"] = "cooldown"
            state["consecutive_crashes"] = consecutive_crashes
            save_state(state)

            time.sleep(COOLDOWN_SECONDS)
            restart_times.clear()
            consecutive_crashes = 0
            log("Cooldown complete, restarting...")

        # Launch the bot
        bot_start = time.monotonic()
        bot_start_ts = datetime.now().isoformat()
        state["status"] = "bot_running"
        state["last_bot_start"] = bot_start_ts
        state["consecutive_crashes"] = consecutive_crashes
        save_state(state)

        log("Starting bot: python -m src.main")
        try:
            proc = subprocess.Popen(
                [PYTHON, "-m", "src.main"],
                cwd=str(PROJECT_ROOT),
            )
            state["pid"] = proc.pid
            save_state(state)

            proc.wait()
            exit_code = proc.returncode
        except KeyboardInterrupt:
            log("Watchdog interrupted by user (Ctrl+C)")
            state["status"] = "stopped_by_user"
            save_state(state)
            break
        except Exception as exc:
            log(f"Failed to start bot: {exc}")
            exit_code = 1

        bot_uptime = time.monotonic() - bot_start
        state["uptime_seconds"] = round(bot_uptime, 1)
        state["pid"] = None

        # Clean exit (0) = intentional shutdown, don't restart
        if exit_code == 0:
            log("Bot exited cleanly (code 0). Stopping watchdog.")
            state["status"] = "stopped_clean"
            save_state(state)
            break

        # /restart command (42) = instant restart, don't count as crash
        if exit_code == RESTART_EXIT_CODE:
            log("Bot restart requested (exit code 42). Restarting immediately...")
            consecutive_crashes = 0
            total_restarts += 1
            state["total_restarts"] = total_restarts
            state["status"] = "restarting"
            save_state(state)
            continue

        # Self-update (43) = git pull + restart
        if exit_code == UPDATE_EXIT_CODE:
            log("Self-update requested (exit code 43)")
            do_self_update()
            consecutive_crashes = 0
            total_restarts += 1
            state["total_restarts"] = total_restarts
            state["status"] = "updating"
            save_state(state)
            continue

        # Crash — restart with exponential backoff
        consecutive_crashes += 1
        total_restarts += 1
        restart_times.append(time.monotonic())

        # Exponential backoff: 5s, 10s, 20s, 40s, 60s, 60s...
        delay = min(BASE_RESTART_DELAY * (2 ** (consecutive_crashes - 1)), MAX_RESTART_DELAY)

        state["status"] = "crashed"
        state["last_crash"] = datetime.now().isoformat()
        state["consecutive_crashes"] = consecutive_crashes
        state["total_restarts"] = total_restarts
        save_state(state)

        log(
            f"Bot crashed (exit code {exit_code}, uptime {bot_uptime:.0f}s). "
            f"Restarting in {delay}s... "
            f"({len(restart_times)}/{MAX_RESTARTS} in window, "
            f"consecutive: {consecutive_crashes})"
        )

        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            log("Watchdog interrupted during restart delay")
            state["status"] = "stopped_by_user"
            save_state(state)
            break

    log("Watchdog stopped")


if __name__ == "__main__":
    main()
