# Troubleshooting

Common issues and their solutions. If your problem is not listed here, please [open a GitHub Issue](https://github.com/progressive-ai-community/progressive-agent/issues).

---

## Bot Doesn't Start

### Missing `.env` file

**Symptom:** `FileNotFoundError` or `KeyError` on startup referencing environment variables.

**Fix:**
```bash
cp .env.example .env
```
Then edit `.env` and fill in at least `TELEGRAM_BOT_TOKEN`. See [.env.example](.env.example) for all available variables.

### Wrong Python version

**Symptom:** `SyntaxError` or `ImportError` on startup.

**Fix:** Progressive Agent requires **Python 3.11 or higher**. Check your version:
```bash
python --version
```
If you have multiple versions installed, use the correct one explicitly:
```bash
python3.12 -m src.main
```

### Missing dependencies

**Symptom:** `ModuleNotFoundError` for packages like `aiogram`, `anthropic`, `sqlite_vec`, etc.

**Fix:**
```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

Some tools have heavy optional dependencies that may fail to install on certain platforms (e.g., `faster-whisper`, `rembg`, `rapidocr-onnxruntime`). The bot will start without them -- those specific tools will simply be unavailable.

### Port already in use / Bot instance already running

**Symptom:** `TelegramBadRequest: terminated by other getUpdates request` or similar conflict error.

**Fix:** Only one instance of the bot can poll Telegram at a time. Kill existing processes:
```bash
# Windows
taskkill /F /IM python.exe

# Linux/Mac
pkill -f "python -m src.main"
```

---

## "No LLM Provider Available"

**Symptom:** Bot starts but replies with an error about no available LLM provider, or logs show `All providers failed`.

### Claude proxy not running (primary provider)

The default configuration uses a local Claude proxy (`CLIProxyAPI` or `claude-max-api-proxy`). If this proxy is not running, the primary provider is unavailable.

**Fix:**
1. Start the proxy before starting the bot.
2. Verify it is reachable at `http://127.0.0.1:8317/v1` (or whatever `CLAUDE_PROXY_URL` is set to).

### No API keys configured

If the proxy is unavailable, the bot falls through the **fallback chain**. Each level needs its own API key:

| Level | Provider | Env Variable | Free? |
|-------|----------|-------------|-------|
| 1 | Claude Proxy | `CLAUDE_PROXY_URL` | Uses subscription |
| 2 | Google Gemini | `GEMINI_API_KEY` | Yes (15 RPM) |
| 3 | Mistral | `MISTRAL_API_KEY` | Yes (1 RPS) |
| 4 | Cloudflare Workers AI | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID` | Yes (10K/day) |
| 5 | OpenAI | `OPENAI_API_KEY` | No (paid) |
| 6 | Claude API | `ANTHROPIC_API_KEY` | No (paid) |

**Fix:** Add at least one API key to `.env`. For a free setup, `GEMINI_API_KEY` or `MISTRAL_API_KEY` is sufficient as a fallback.

### All providers returning errors

Check the logs for specific error messages:
```bash
# Check recent logs
tail -100 data/bot_startup.log
```
Common causes: expired API keys, exhausted free tier quotas, network issues.

---

## Telegram Bot Not Responding

### Wrong bot token

**Symptom:** `TelegramUnauthorizedError: Unauthorized` in logs.

**Fix:** Verify `TELEGRAM_BOT_TOKEN` in `.env` matches the token from [@BotFather](https://t.me/BotFather). Regenerate the token if needed.

### User not in whitelist

**Symptom:** Bot receives messages (visible in logs) but does not reply, or replies with troll-mode responses.

**How it works:** The bot uses a **deny-by-default whitelist** defined in `config/agent.toml`:
```toml
[telegram]
allowed_users = [123456789]  # Your Telegram user ID
```

**How to find your Telegram user ID:**
1. Message [@userinfobot](https://t.me/userinfobot) on Telegram.
2. It will reply with your numeric user ID.

**Auto-onboarding:** When a non-whitelisted user messages the bot, the **owner** receives a notification with the stranger's username, ID, and message. The bot responds to strangers in "troll mode" -- friendly but evasive, never revealing owner information or executing tools.

**Fix:** Add your user ID to `allowed_users` in `config/agent.toml` and restart the bot.

### Bot not receiving messages

**Symptom:** No log entries for incoming messages at all.

**Fix:**
1. Make sure the bot is running (`python -m src.main`).
2. Send `/start` to the bot first.
3. Check that no other instance is polling (see "Port already in use" above).
4. Ensure the bot is not blocked in Telegram.

---

## Memory Errors

### SQLite database locked

**Symptom:** `sqlite3.OperationalError: database is locked`

**Cause:** Multiple processes trying to write to the same `data/memory.db` file simultaneously.

**Fix:**
1. Ensure only one bot instance is running.
2. If the issue persists after stopping all instances, the lock file may be stale. Restart the bot -- it uses `asyncio.Lock` internally to prevent concurrent access.

### Disk full

**Symptom:** `sqlite3.OperationalError: disk I/O error` or `database or disk is full`

**Fix:**
1. Free up disk space.
2. The memory database grows over time. You can check its size:
   ```bash
   ls -lh data/memory.db
   ```
3. If necessary, you can delete old conversation memories (the bot will lose history but continue functioning):
   ```bash
   # Back up first!
   cp data/memory.db data/memory.db.bak
   ```

### Database not found on first run

**Symptom:** `FileNotFoundError` for `data/memory.db`.

**Fix:** The bot auto-creates the `data/` directory and database on first startup. If it fails, create the directory manually:
```bash
mkdir data
```

---

## STT (Speech-to-Text) Not Working

### faster-whisper model not downloaded

**Symptom:** First voice message takes very long or fails with a download error.

**Fix:** The model (`large-v3`, ~3 GB) is downloaded automatically on first use. Ensure you have:
- Sufficient disk space (~3 GB for the model).
- A stable internet connection for the initial download.
- Patience -- the first transcription will be slow while the model downloads.

Smaller models are available if disk space is limited. Edit `src/tools/stt_tool.py` and change `DEFAULT_MODEL`:
```python
DEFAULT_MODEL = "base"    # ~150 MB, faster but less accurate
DEFAULT_MODEL = "small"   # ~500 MB, good balance
DEFAULT_MODEL = "medium"  # ~1.5 GB, high accuracy
DEFAULT_MODEL = "large-v3"  # ~3 GB, best accuracy (default)
```

### ffmpeg not installed

**Symptom:** `FileNotFoundError: ffmpeg` or audio conversion errors.

**Fix:** faster-whisper requires `ffmpeg` for audio format conversion.

```bash
# Windows (via winget)
winget install ffmpeg

# Windows (via chocolatey)
choco install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

On Windows, the bot automatically checks the WinGet Links directory for ffmpeg. If installed via other methods, ensure `ffmpeg` is in your system PATH.

### Voice messages not being processed

**Symptom:** Bot acknowledges voice messages but returns no transcription.

**Fix:** Check that `faster-whisper` is installed:
```bash
pip show faster-whisper
```
If not installed, it may have been skipped during dependency installation. Install it manually:
```bash
pip install faster-whisper>=1.0.0
```

---

## Tools Not Loading

### Missing optional dependencies

**Symptom:** Specific tools are unavailable. Log shows `Failed to load tool: <tool_name>`.

Some tools require additional system packages or optional dependencies:

| Tool | Dependency | Install |
|------|-----------|---------|
| STT (voice) | `faster-whisper`, `ffmpeg` | `pip install faster-whisper` + install ffmpeg |
| TTS (voice output) | `edge-tts` | `pip install edge-tts` |
| Media download | `yt-dlp` | `pip install yt-dlp` |
| Image generation | `OPENAI_API_KEY` | Set in `.env` |
| Email | Gmail OAuth credentials | See `config/gmail_credentials.json` setup |
| Browser | System Chrome/Chromium | Install Chrome |
| Screenshots | `mss` | `pip install mss` |
| System monitoring | `psutil` | `pip install psutil` |
| Background removal | `rembg` | `pip install "rembg[cpu]"` |

**Fix:** Install the missing dependency, then restart the bot. Tools that fail to load are simply skipped -- they do not prevent the bot from starting.

### Tool returns errors at runtime

**Symptom:** Tool loads but returns `ToolResult(success=False, error=...)`.

**Common causes:**
- Missing API key for the specific service (check `.env`).
- Service is down or rate-limited.
- Invalid configuration in `config/agent.toml`.

Check the bot logs for the specific error message.

---

## API Rate Limiting

### Tavily search rate limits

**Symptom:** Web search returns errors about rate limits or exhausted credits.

**Fix:** Progressive Agent supports **automatic Tavily key rotation**. Add multiple keys to `.env`:
```env
TAVILY_API_KEYS=tvly-key1,tvly-key2,tvly-key3
```
When credits run out on one key, the bot automatically switches to the next.

### LLM provider rate limits

**Symptom:** Slow responses or `429 Too Many Requests` errors in logs.

**Fix:** The fallback chain handles this automatically. If one provider is rate-limited, the bot tries the next one. To improve reliability:
1. Add more provider API keys to `.env` (see the fallback chain table above).
2. Free tiers have low limits (Gemini: 15 RPM, Mistral: 1 RPS, Cloudflare: 10K/day).
3. For heavy usage, configure a paid provider (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`).

### Telegram rate limits

**Symptom:** `TelegramRetryAfter` errors or delayed message delivery.

**Fix:** Telegram limits bots to ~30 messages per second. The bot handles this internally with retry logic. If you see persistent issues, reduce the streaming chunk frequency in `config/agent.toml`:
```toml
[telegram]
streaming_chunk_size = 100  # Increase to reduce edit frequency
streaming_delay_ms = 200    # Increase delay between edits
```

---

## General Tips

1. **Check the logs.** The bot logs to stderr by default. Redirect to a file for persistent logs:
   ```bash
   python -m src.main 2>&1 | tee bot.log
   ```

2. **Use the watchdog.** The watchdog (`src/watchdog.py`) automatically restarts the bot on crashes with exponential backoff:
   ```bash
   python -m src.watchdog
   ```

3. **Verify configuration.** Most issues come from misconfigured `.env` or `config/agent.toml`. Double-check both files.

4. **Update dependencies.** If you encounter unexpected errors after a git pull:
   ```bash
   uv sync
   ```

5. **Reset memory.** If the database is corrupted:
   ```bash
   mv data/memory.db data/memory.db.bak
   # Bot will create a fresh database on next start
   ```
