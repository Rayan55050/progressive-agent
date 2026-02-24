#!/usr/bin/env python3
"""
Progressive Agent — Interactive Setup Wizard

Creates a .env configuration file by walking the user through
all required and optional API keys / tokens.

Usage:
    python scripts/setup.py

No external dependencies — pure stdlib (Python 3.11+).
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# ANSI color helpers (disabled on Windows terminals that lack VT support)
# ---------------------------------------------------------------------------

_COLORS_ENABLED = False


def _detect_color_support() -> bool:
    """Check whether the terminal supports ANSI escape codes."""
    # Explicit override
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    # Not a TTY — no colors
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    # Windows: enable VT processing if possible
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # STD_OUTPUT_HANDLE = -11
            handle = kernel32.GetStdHandle(-11)
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
            return True
        except Exception:
            return False
    return True


_COLORS_ENABLED = _detect_color_support()


def _c(code: str, text: str) -> str:
    if not _COLORS_ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return _c("1", text)


def green(text: str) -> str:
    return _c("32", text)


def cyan(text: str) -> str:
    return _c("36", text)


def yellow(text: str) -> str:
    return _c("33", text)


def red(text: str) -> str:
    return _c("31", text)


def dim(text: str) -> str:
    return _c("2", text)


def magenta(text: str) -> str:
    return _c("35", text)


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

def hr(char: str = "-", width: int = 60) -> str:
    return dim(char * width)


def section(title: str) -> None:
    print()
    print(hr("="))
    print(bold(cyan(f"  {title}")))
    print(hr("="))
    print()


def info(text: str) -> None:
    for line in textwrap.wrap(text, width=72):
        print(f"  {line}")


def hint(text: str) -> None:
    for line in textwrap.wrap(text, width=72):
        print(f"  {dim(line)}")


def success(text: str) -> None:
    print(f"  {green('[OK]')} {text}")


def warn(text: str) -> None:
    print(f"  {yellow('[!]')} {text}")


def error(text: str) -> None:
    print(f"  {red('[ERROR]')} {text}")


def ask(prompt: str, *, default: str = "", secret: bool = False) -> str:
    """Prompt the user for input with an optional default value."""
    suffix = f" [{dim(default)}]" if default else ""
    display = f"  {bold('>')} {prompt}{suffix}: "
    try:
        value = input(display).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print()
        warn("Setup cancelled by user.")
        sys.exit(1)
    return value if value else default


def ask_yes_no(prompt: str, *, default: bool = True) -> bool:
    """Ask a yes/no question."""
    choices = "Y/n" if default else "y/N"
    suffix = f" [{dim(choices)}]"
    display = f"  {bold('>')} {prompt}{suffix}: "
    try:
        value = input(display).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        print()
        warn("Setup cancelled by user.")
        sys.exit(1)
    if not value:
        return default
    return value in ("y", "yes", "1", "true", "da")


def ask_choice(prompt: str, options: list[str], *, allow_multiple: bool = False) -> list[int]:
    """Present numbered options and return selected indices (0-based)."""
    for i, opt in enumerate(options, 1):
        print(f"    {bold(str(i))}. {opt}")
    print()
    if allow_multiple:
        hint("Enter numbers separated by commas (e.g. 1,3) or press Enter to skip.")
    raw = ask(prompt)
    if not raw:
        return []
    indices: list[int] = []
    for part in raw.replace(" ", "").split(","):
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(options):
                indices.append(idx)
    return indices


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_telegram_token(token: str) -> bool:
    """Telegram bot token format: <digits>:<alphanumeric+dash+underscore>."""
    return bool(re.match(r"^\d{8,}:[A-Za-z0-9_-]{30,}$", token))


def validate_anthropic_key(key: str) -> bool:
    return key.startswith("sk-ant-")


def validate_openai_key(key: str) -> bool:
    return key.startswith("sk-")


# ---------------------------------------------------------------------------
# .env generation
# ---------------------------------------------------------------------------

def generate_env(config: dict[str, str]) -> str:
    """Build the .env file content, matching the structure of .env.example."""

    def val(key: str) -> str:
        return config.get(key, "")

    lines: list[str] = []

    def ln(text: str = "") -> None:
        lines.append(text)

    ln("# Progressive Agent — Environment Variables")
    ln("# Generated by scripts/setup.py")
    ln()

    ln("# === Claude (via Max subscription — free proxy) ===")
    ln(f"CLAUDE_PROXY_URL={val('CLAUDE_PROXY_URL')}")
    ln()

    ln("# === Claude API (paid fallback) ===")
    v = val("ANTHROPIC_API_KEY")
    if v:
        ln(f"ANTHROPIC_API_KEY={v}")
    else:
        ln("# ANTHROPIC_API_KEY=sk-ant-xxx")
    ln()

    ln("# === OpenAI proxy (via ChatGPT subscription) ===")
    v = val("OPENAI_PROXY_URL")
    if v:
        ln(f"OPENAI_PROXY_URL={v}")
    else:
        ln("# OPENAI_PROXY_URL=")
    ln()

    ln("# === Mistral AI (free fallback — 1B tokens/month) ===")
    ln(f"MISTRAL_API_KEY={val('MISTRAL_API_KEY')}")
    ln()

    ln("# === Google Gemini (free fallback — 15 RPM) ===")
    ln(f"GEMINI_API_KEY={val('GEMINI_API_KEY')}")
    ln()

    ln("# === Cloudflare Workers AI (free fallback — 10K neurons/day) ===")
    ln(f"CLOUDFLARE_API_KEY={val('CLOUDFLARE_API_KEY')}")
    ln(f"CLOUDFLARE_ACCOUNT_ID={val('CLOUDFLARE_ACCOUNT_ID')}")
    ln()

    ln("# === Telegram ===")
    ln(f"TELEGRAM_BOT_TOKEN={val('TELEGRAM_BOT_TOKEN')}")
    ln()

    ln("# === OpenAI (embeddings, Whisper STT, DALL-E 3) ===")
    ln(f"OPENAI_API_KEY={val('OPENAI_API_KEY')}")
    ln()

    ln("# === Tavily (web search) ===")
    ln(f"TAVILY_API_KEY={val('TAVILY_API_KEY')}")
    ln(f"TAVILY_API_KEYS={val('TAVILY_API_KEYS')}")
    ln()

    ln("# === SerpApi (Google search) ===")
    ln(f"SERPAPI_API_KEY={val('SERPAPI_API_KEY')}")
    ln()

    ln("# === Firecrawl (web scraping) ===")
    ln(f"FIRECRAWL_API_KEY={val('FIRECRAWL_API_KEY')}")
    ln()

    ln("# === Finnhub (stocks/crypto/forex) ===")
    ln(f"FINNHUB_API_KEY={val('FINNHUB_API_KEY')}")
    ln()

    ln("# === Twitch ===")
    ln(f"TWITCH_CLIENT_ID={val('TWITCH_CLIENT_ID')}")
    ln(f"TWITCH_CLIENT_SECRET={val('TWITCH_CLIENT_SECRET')}")
    ln()

    ln("# === YouTube Data API v3 ===")
    ln(f"YOUTUBE_API_KEY={val('YOUTUBE_API_KEY')}")
    ln()

    ln("# === Monobank ===")
    ln(f"MONOBANK_API_TOKEN={val('MONOBANK_API_TOKEN')}")
    ln()

    ln("# === Nova Poshta ===")
    ln(f"NOVAPOSHTA_API_KEY={val('NOVAPOSHTA_API_KEY')}")
    ln()

    ln("# === DeepL (translation, 500K chars/mo free) ===")
    ln(f"DEEPL_API_KEY={val('DEEPL_API_KEY')}")
    ln()

    ln("# === Alerts.in.ua (Ukrainian air raid alerts) ===")
    ln(f"ALERTS_UA_TOKEN={val('ALERTS_UA_TOKEN')}")
    ln()

    ln("# === TMDB (movies/TV) ===")
    ln(f"TMDB_API_KEY={val('TMDB_API_KEY')}")
    ln()

    ln("# === Telegram whitelist (comma-separated user IDs) ===")
    ln(f"ALLOWED_USERS={val('ALLOWED_USERS')}")
    ln()

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Setup steps
# ---------------------------------------------------------------------------

def step_telegram(config: dict[str, str]) -> None:
    section("Step 1 / 5 — Telegram Bot Token  [REQUIRED]")

    info("You need a Telegram bot token to run Progressive Agent.")
    info("If you don't have one yet, create it in 30 seconds:")
    print()
    info("  1. Open Telegram and search for @BotFather")
    info("  2. Send /newbot and follow the instructions")
    info("  3. Copy the token that looks like:")
    info("     123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
    print()

    while True:
        token = ask("Telegram bot token")
        if not token:
            error("Telegram bot token is required. Cannot continue without it.")
            continue
        if validate_telegram_token(token):
            config["TELEGRAM_BOT_TOKEN"] = token
            success("Telegram token accepted.")
            break
        else:
            warn("Token format looks wrong (expected: digits:alphanumeric).")
            if ask_yes_no("Use it anyway?", default=False):
                config["TELEGRAM_BOT_TOKEN"] = token
                break

    print()
    tg_id = ask("Your Telegram user ID (for whitelist, optional)", default="")
    if tg_id:
        config["ALLOWED_USERS"] = tg_id
        hint("Tip: find your ID by sending /start to @userinfobot")


def step_main_provider(config: dict[str, str]) -> None:
    section("Step 2 / 5 — Main LLM Provider  [REQUIRED — pick at least 1]")

    info("Progressive Agent needs at least one LLM provider to work.")
    info("Pick one or more from the options below:")
    print()

    options = [
        "Claude proxy  (FREE via Claude Max subscription — runs locally)",
        "OpenAI proxy  (FREE via ChatGPT subscription — runs locally)",
        "Claude API    (PAID — needs ANTHROPIC_API_KEY)",
        "OpenAI API    (PAID — needs OPENAI_API_KEY; also enables embeddings + STT)",
    ]
    chosen = ask_choice("Select providers (e.g. 1 or 1,4)", options, allow_multiple=True)

    if not chosen:
        warn("No provider selected! You need at least one LLM provider.")
        warn("Defaulting to Claude proxy (http://127.0.0.1:8317/v1).")
        chosen = [0]

    for idx in chosen:
        if idx == 0:
            # Claude proxy
            print()
            info("Claude proxy uses the 'claude-max-api-proxy' npm package")
            info("to route requests through your Claude Max subscription.")
            print()
            info("Install it:")
            info("  npm install -g claude-max-api-proxy")
            info("  claude-max-api-proxy start")
            print()
            url = ask("Claude proxy URL", default="http://127.0.0.1:8317/v1")
            config["CLAUDE_PROXY_URL"] = url
            success("Claude proxy configured.")

        elif idx == 1:
            # OpenAI proxy
            print()
            info("OpenAI proxy works similarly to Claude proxy, routing")
            info("requests through your ChatGPT subscription locally.")
            print()
            url = ask("OpenAI proxy URL", default="http://127.0.0.1:8318/v1")
            config["OPENAI_PROXY_URL"] = url
            success("OpenAI proxy configured.")

        elif idx == 2:
            # Claude API
            print()
            info("Get your API key at: https://console.anthropic.com/settings/keys")
            print()
            while True:
                key = ask("Anthropic API key (sk-ant-...)")
                if not key:
                    warn("Skipped Claude API key.")
                    break
                if validate_anthropic_key(key):
                    config["ANTHROPIC_API_KEY"] = key
                    success("Anthropic API key accepted.")
                    break
                else:
                    warn("Key should start with 'sk-ant-'. Use it anyway?")
                    if ask_yes_no("Use it anyway?", default=False):
                        config["ANTHROPIC_API_KEY"] = key
                        break

        elif idx == 3:
            # OpenAI API
            print()
            info("Get your API key at: https://platform.openai.com/api-keys")
            info("This key is also used for embeddings (text-embedding-3-small),")
            info("Whisper STT (voice messages), and DALL-E 3 (image generation).")
            print()
            while True:
                key = ask("OpenAI API key (sk-...)")
                if not key:
                    warn("Skipped OpenAI API key.")
                    break
                if validate_openai_key(key):
                    config["OPENAI_API_KEY"] = key
                    success("OpenAI API key accepted.")
                    break
                else:
                    warn("Key should start with 'sk-'. Use it anyway?")
                    if ask_yes_no("Use it anyway?", default=False):
                        config["OPENAI_API_KEY"] = key
                        break


def step_fallback_providers(config: dict[str, str]) -> None:
    section("Step 3 / 5 — Fallback LLM Providers  [OPTIONAL]")

    info("Fallback providers kick in automatically when the main provider")
    info("is unavailable (e.g. your PC is off and the proxy is unreachable).")
    info("All options below are FREE. Highly recommended for reliability.")
    print()

    # --- Gemini ---
    print(f"  {bold('a) Google Gemini')} — free, 15 requests/min, multimodal")
    hint("Get key: https://aistudio.google.com/apikey")
    key = ask("Gemini API key (or Enter to skip)")
    if key:
        config["GEMINI_API_KEY"] = key
        success("Gemini configured.")
    print()

    # --- Mistral ---
    print(f"  {bold('b) Mistral AI')} — free, 1B tokens/month (1 req/sec rate limit)")
    hint("Get key: https://console.mistral.ai/api-keys")
    key = ask("Mistral API key (or Enter to skip)")
    if key:
        config["MISTRAL_API_KEY"] = key
        success("Mistral configured.")
    print()

    # --- Cloudflare ---
    print(f"  {bold('c) Cloudflare Workers AI')} — free, 10K neurons/day, Llama 3.3 70B")
    hint("Get credentials: https://dash.cloudflare.com")
    hint("  Settings > Account > Account ID")
    hint("  API Tokens > Create Token (Workers AI template)")
    key = ask("Cloudflare API key (or Enter to skip)")
    if key:
        config["CLOUDFLARE_API_KEY"] = key
        account = ask("Cloudflare Account ID")
        if account:
            config["CLOUDFLARE_ACCOUNT_ID"] = account
        success("Cloudflare Workers AI configured.")


def step_optional_keys(config: dict[str, str]) -> None:
    section("Step 4 / 5 — Optional API Keys  [for extra features]")

    info("Each key below unlocks specific tools. All are free-tier or have")
    info("generous free quotas. Press Enter to skip any you don't need.")
    print()

    # ---- Tavily ----
    print(f"  {bold('Tavily')} — web search (primary search engine for the agent)")
    hint("Free dev tier: 1000 searches/month")
    hint("Get key: https://app.tavily.com/home")
    key = ask("Tavily API key (tvly-...)")
    if key:
        config["TAVILY_API_KEY"] = key
        keys = ask("Additional Tavily keys for rotation (comma-separated, optional)")
        if keys:
            config["TAVILY_API_KEYS"] = keys
        success("Tavily configured.")
    print()

    # ---- OpenAI (if not already set) ----
    if not config.get("OPENAI_API_KEY"):
        print(f"  {bold('OpenAI')} — embeddings (memory search), Whisper (voice-to-text), DALL-E 3")
        hint("Pay-as-you-go: embeddings are very cheap (~$0.02/1M tokens)")
        hint("Get key: https://platform.openai.com/api-keys")
        key = ask("OpenAI API key (sk-...)")
        if key:
            config["OPENAI_API_KEY"] = key
            success("OpenAI configured.")
        print()

    # ---- Finnhub ----
    print(f"  {bold('Finnhub')} — real-time stocks, crypto, forex data")
    hint("Free: 60 API calls/min")
    hint("Get key: https://finnhub.io/register")
    key = ask("Finnhub API key")
    if key:
        config["FINNHUB_API_KEY"] = key
        success("Finnhub configured.")
    print()

    # ---- Twitch ----
    print(f"  {bold('Twitch')} — monitor live streams, get notifications")
    hint("Free: register an app at https://dev.twitch.tv/console")
    client_id = ask("Twitch Client ID")
    if client_id:
        config["TWITCH_CLIENT_ID"] = client_id
        client_secret = ask("Twitch Client Secret")
        if client_secret:
            config["TWITCH_CLIENT_SECRET"] = client_secret
        success("Twitch configured.")
    print()

    # ---- YouTube ----
    print(f"  {bold('YouTube Data API v3')} — monitor channels, search videos")
    hint("Free quota: 10,000 units/day")
    hint("Enable API in Google Cloud Console, create an API key")
    hint("https://console.cloud.google.com/apis/library/youtube.googleapis.com")
    key = ask("YouTube API key")
    if key:
        config["YOUTUBE_API_KEY"] = key
        success("YouTube configured.")
    print()

    # ---- Monobank ----
    print(f"  {bold('Monobank')} — Ukrainian banking: balance, transactions, currency rates")
    hint("Free personal token")
    hint("Get token: https://api.monobank.ua/ (authorize via Monobank app)")
    key = ask("Monobank API token")
    if key:
        config["MONOBANK_API_TOKEN"] = key
        success("Monobank configured.")
    print()

    # ---- Nova Poshta ----
    print(f"  {bold('Nova Poshta')} — Ukrainian parcel tracking & delivery service")
    hint("Free, no rate limits")
    hint("Get key: new.novaposhta.ua > Settings > Security > API key")
    key = ask("Nova Poshta API key")
    if key:
        config["NOVAPOSHTA_API_KEY"] = key
        success("Nova Poshta configured.")
    print()

    # ---- SerpApi ----
    print(f"  {bold('SerpApi')} — Google search results (structured data)")
    hint("Free: 100 searches/month")
    hint("Get key: https://serpapi.com/manage-api-key")
    key = ask("SerpApi API key")
    if key:
        config["SERPAPI_API_KEY"] = key
        success("SerpApi configured.")
    print()

    # ---- Firecrawl ----
    print(f"  {bold('Firecrawl')} — advanced web scraping & crawling")
    hint("Free tier: 500 pages/month")
    hint("Get key: https://firecrawl.dev/app/api-keys")
    key = ask("Firecrawl API key")
    if key:
        config["FIRECRAWL_API_KEY"] = key
        success("Firecrawl configured.")
    print()

    # ---- DeepL ----
    print(f"  {bold('DeepL')} — high-quality translation (supports 30+ languages)")
    hint("Free: 500,000 characters/month")
    hint("Get key: https://www.deepl.com/pro-api (sign up for free plan)")
    key = ask("DeepL API key")
    if key:
        config["DEEPL_API_KEY"] = key
        success("DeepL configured.")
    print()

    # ---- Alerts.in.ua ----
    print(f"  {bold('Alerts.in.ua')} — Ukrainian air raid alert monitoring")
    hint("Register at https://alerts.in.ua to request API access")
    key = ask("Alerts.in.ua token")
    if key:
        config["ALERTS_UA_TOKEN"] = key
        success("Alerts.in.ua configured.")
    print()

    # ---- TMDB ----
    print(f"  {bold('TMDB')} — movies, TV shows, ratings, recommendations")
    hint("Free API key")
    hint("Get key: https://www.themoviedb.org/settings/api")
    key = ask("TMDB API key")
    if key:
        config["TMDB_API_KEY"] = key
        success("TMDB configured.")


def step_write_env(config: dict[str, str], project_root: Path) -> None:
    section("Step 5 / 5 — Generate .env file")

    env_path = project_root / ".env"

    if env_path.exists():
        warn(f".env already exists at: {env_path}")
        if not ask_yes_no("Overwrite it?", default=False):
            # Offer to write to a different name
            alt = ask("Alternative filename", default=".env.new")
            env_path = project_root / alt
            info(f"Will write to: {env_path}")

    content = generate_env(config)

    try:
        env_path.write_text(content, encoding="utf-8")
        success(f".env written to: {env_path}")
    except OSError as exc:
        error(f"Failed to write .env: {exc}")
        print()
        info("You can manually create the file with this content:")
        print(hr())
        print(content)
        print(hr())
        return

    # --- Summary ---
    print()
    configured = [k for k, v in config.items() if v and k != "ALLOWED_USERS"]
    skipped_keys = {
        "CLAUDE_PROXY_URL", "OPENAI_PROXY_URL", "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY",
        "CLOUDFLARE_API_KEY", "CLOUDFLARE_ACCOUNT_ID",
        "TELEGRAM_BOT_TOKEN", "TAVILY_API_KEY", "TAVILY_API_KEYS",
        "SERPAPI_API_KEY", "FIRECRAWL_API_KEY", "FINNHUB_API_KEY",
        "TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "YOUTUBE_API_KEY",
        "MONOBANK_API_TOKEN", "NOVAPOSHTA_API_KEY", "DEEPL_API_KEY",
        "ALERTS_UA_TOKEN", "TMDB_API_KEY",
    }
    not_set = sorted(skipped_keys - set(configured))

    info(f"Configured: {len(configured)} key(s)")
    if not_set:
        hint(f"Skipped: {', '.join(not_set)}")
        hint("You can add them later by editing .env directly.")

    # --- Launch instructions ---
    print()
    print(hr("="))
    print(bold(green("  Setup complete! Here's how to launch:")))
    print(hr("="))
    print()
    info("1. Install dependencies (if you haven't already):")
    print(f"     {cyan('uv sync')}")
    print()
    info("2. Start the agent:")
    print(f"     {cyan('python -m src.main')}")
    print()
    info("3. Open Telegram and message your bot. Enjoy!")
    print()

    if config.get("CLAUDE_PROXY_URL"):
        hint("Remember to start the Claude proxy before launching:")
        hint("  npm install -g claude-max-api-proxy")
        hint("  claude-max-api-proxy start")
        print()

    if config.get("OPENAI_PROXY_URL"):
        hint("Remember to start the OpenAI proxy before launching.")
        print()

    hint("Docs: https://github.com/niceprogressive/progressive-agent")
    hint("Issues? Open a GitHub issue or check docs/STATUS.md")
    print()


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = r"""
  ____                                    _
 |  _ \ _ __ ___   __ _ _ __ ___  ___ ___(_)_   _____
 | |_) | '__/ _ \ / _` | '__/ _ \/ __/ __| \ \ / / _ \
 |  __/| | | (_) | (_| | | |  __/\__ \__ \ |\ V /  __/
 |_|   |_|  \___/ \__, |_|  \___||___/___/_| \_/ \___|
                   |___/
                 _                    _
     /\         | |                  | |
    /  \   __ _ | |__   __ _  _ __  | |_
   / /\ \ / _` || '_ \ / _` || '_ \ | __|
  / ____ \| (_| || |_) || (_| || | | || |_
 /_/    \_\\__, ||_.__/  \__, ||_| |_| \__|
            __/ |         __/ |
           |___/         |___/
"""


def print_banner() -> None:
    if _COLORS_ENABLED:
        print(cyan(BANNER))
    else:
        print(BANNER)

    print(bold("  Progressive Agent — Interactive Setup Wizard"))
    print()
    info("An open-source personal AI agent for Telegram.")
    info("Built with Claude, Python, and love.")
    print()
    info("This wizard will walk you through configuring your .env file")
    info("with all the API keys and tokens the agent needs to run.")
    print()
    hint("Required: Telegram bot token + at least 1 LLM provider.")
    hint("Everything else is optional and can be added later.")
    print()
    print(hr())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Determine project root (parent of scripts/ directory)
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    # Sanity check — we expect to find pyproject.toml or .env.example
    if not (project_root / "pyproject.toml").exists() and not (project_root / ".env.example").exists():
        warn(f"Project root detected as: {project_root}")
        warn("Could not find pyproject.toml or .env.example there.")
        if not ask_yes_no("Continue anyway?", default=False):
            sys.exit(1)

    config: dict[str, str] = {}

    print_banner()

    step_telegram(config)
    step_main_provider(config)
    step_fallback_providers(config)
    step_optional_keys(config)
    step_write_env(config, project_root)


if __name__ == "__main__":
    main()
