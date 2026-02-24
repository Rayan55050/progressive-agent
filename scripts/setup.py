#!/usr/bin/env python3
"""
Progressive Agent — Interactive Setup

Creates .env from user input. No GUI, no dependencies.
Run: python scripts/setup.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
REQ_FILE = PROJECT_ROOT / "requirements.txt"


def ask(prompt: str, default: str = "", required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"  {prompt}{suffix}: ").strip()
        if not value and default:
            return default
        if not value and required:
            print("    Required. Please enter a value.")
            continue
        return value


def ask_yn(prompt: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    value = input(f"  {prompt} {suffix}: ").strip().lower()
    if not value:
        return default
    return value in ("y", "yes", "1")


def install_deps() -> bool:
    print("\n  Installing dependencies...")
    python = sys.executable
    cmd = [python, "-m", "pip", "install", "-r", str(REQ_FILE),
           "--disable-pip-version-check"]
    try:
        result = subprocess.run(cmd, timeout=600)
        if result.returncode == 0:
            print("  Done!")
            return True
        print("  Some packages failed. Trying core packages only...")
        core = [
            "anthropic", "openai", "mistralai", "aiogram",
            "pydantic", "python-dotenv", "aiohttp", "aiofiles",
            "apscheduler", "pyyaml", "tavily-python",
        ]
        result2 = subprocess.run(
            [python, "-m", "pip", "install"] + core,
            timeout=300,
        )
        if result2.returncode == 0:
            print("  Core dependencies installed (some optional skipped).")
            return True
        print("  Failed. Run manually: pip install -r requirements.txt")
        return False
    except subprocess.TimeoutExpired:
        print("  Timed out. Run manually: pip install -r requirements.txt")
        return False


def setup_env() -> dict[str, str]:
    config: dict[str, str] = {}

    print("\n=== LLM Provider ===")
    print("  Choose your main LLM:\n")
    print("  1. Claude API key (pay-per-use)")
    print("  2. OpenAI API key (pay-per-use)")
    print("  3. Claude subscription proxy (free with Max/Pro)")
    print("  4. Skip (configure later in .env)")

    choice = ask("Choice", "1")

    if choice == "1":
        key = ask("Claude API key (sk-ant-...)", required=True)
        config["ANTHROPIC_API_KEY"] = key
    elif choice == "2":
        key = ask("OpenAI API key (sk-...)", required=True)
        config["OPENAI_API_KEY"] = key
    elif choice == "3":
        config["CLAUDE_PROXY_URL"] = "http://127.0.0.1:8317/v1"
        print("  Note: install claude-max-api-proxy separately.")
        print("  See: npm install -g claude-max-api-proxy")

    print("\n=== Telegram Bot ===")
    print("  Create a bot via @BotFather (https://t.me/BotFather)")
    token = ask("Bot token", required=True)
    config["TELEGRAM_BOT_TOKEN"] = token

    print("\n=== Optional: Web Search ===")
    if ask_yn("Add Tavily key for web search? (free at tavily.com)", False):
        key = ask("Tavily API key")
        if key:
            config["TAVILY_API_KEY"] = key

    print("\n=== Optional: OpenAI ===")
    if "OPENAI_API_KEY" not in config:
        if ask_yn("Add OpenAI key? (embeddings, voice, images)", False):
            key = ask("OpenAI API key")
            if key:
                config["OPENAI_API_KEY"] = key

    return config


def write_env(config: dict[str, str]) -> None:
    if ENV_EXAMPLE.exists():
        content = ENV_EXAMPLE.read_text(encoding="utf-8")
    else:
        content = ""

    lines = content.splitlines()
    result_lines = []
    for line in lines:
        replaced = False
        for key, value in config.items():
            if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
                result_lines.append(f"{key}={value}")
                replaced = True
                break
        if not replaced:
            result_lines.append(line)

    ENV_FILE.write_text("\n".join(result_lines), encoding="utf-8")
    print(f"\n  .env saved to {ENV_FILE}")


def main():
    print("\nProgressive Agent — Setup")
    print("=" * 40)

    if sys.version_info < (3, 11):
        print(f"  Warning: Python {sys.version_info.major}.{sys.version_info.minor}. "
              "Python 3.11+ recommended.")

    if ask_yn("Install Python dependencies?", True):
        install_deps()

    config = setup_env()
    write_env(config)

    (PROJECT_ROOT / "data").mkdir(exist_ok=True)

    print("\n=== Ready! ===")
    print(f"\n  Start the bot:")
    print(f"    cd {PROJECT_ROOT}")
    print(f"    python -m src.main")
    print(f"\n  Then open Telegram, find your bot, and press /start\n")


if __name__ == "__main__":
    main()
