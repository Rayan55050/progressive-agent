# Deployment Guide

This guide covers how to deploy Progressive Agent on various platforms.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Initial Setup (All Platforms)](#initial-setup-all-platforms)
3. [Windows Deployment](#windows-deployment)
4. [Linux / macOS Deployment](#linux--macos-deployment)
5. [Docker Deployment](#docker-deployment)
6. [Oracle Cloud Free Tier](#oracle-cloud-free-tier)
7. [Post-Deployment Checks](#post-deployment-checks)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **uv** package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **Telegram Bot Token** from [@BotFather](https://t.me/BotFather)
- At least one LLM provider configured (see [LLM Providers](#llm-providers) below)

### LLM Providers

You need at least one of these:

| Provider | Cost | Setup |
|----------|------|-------|
| Claude Proxy (CLIProxyAPI) | Free (with Claude subscription) | Run local proxy on `localhost:8317` |
| Anthropic API | Paid (~$15/MTok Opus) | Set `ANTHROPIC_API_KEY` in `.env` |
| Mistral AI | Free (1B tokens/mo) | Set `MISTRAL_API_KEY` in `.env` |
| OpenAI | Paid (~$5/MTok GPT-5.2) | Set `OPENAI_API_KEY` in `.env` |
| Google Gemini | Free (15 RPM) | Set `GEMINI_API_KEY` in `.env` |
| Cloudflare Workers AI | Free (10K/day) | Set `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID` in `.env` |

The agent builds a fallback chain from all available providers. If the primary fails, it automatically switches to the next.

---

## Initial Setup (All Platforms)

### 1. Clone the Repository

```bash
git clone https://github.com/YourUsername/progressive-agent.git
cd progressive-agent
```

### 2. Install Dependencies

```bash
uv sync
```

Or with system Python:

```bash
pip install -e .
```

### 3. Create Configuration

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys:

```bash
# Required
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# At least one LLM provider (pick one or more)
ANTHROPIC_API_KEY=sk-ant-xxx
# or
MISTRAL_API_KEY=xxx
# or
OPENAI_API_KEY=sk-xxx
```

### 4. Configure Agent Settings

Edit `config/agent.toml`:

```toml
[telegram]
# Your Telegram user ID (get it from @userinfobot)
allowed_users = [YOUR_TELEGRAM_USER_ID]

[agent]
# Choose your primary model
default_model = "claude-opus-4-6"  # or "claude-sonnet-4-5-20250929"
max_tokens = 16384

[weather]
default_city = "Your City"

[scheduler]
timezone = "Your/Timezone"  # e.g., "America/New_York", "Europe/London"
```

### 5. Create Data Directory

```bash
mkdir -p data
```

### 6. Test Run

```bash
python -m src.main
```

If everything is configured correctly, you will see:
```
Progressive Agent started!
LLM: fallback(claude-subscription)
Tools: 63
Skills: 16
```

Send a message to your bot on Telegram to verify.

---

## Windows Deployment

### Manual Start

```powershell
cd C:\path\to\progressive-agent
python -m src.main
```

### Background Service (Watchdog)

The watchdog (`src/watchdog.py`) runs the bot as a supervised subprocess with automatic crash recovery:

```powershell
python -m src.watchdog
```

Features:
- Automatic restart on crash with exponential backoff (5s, 10s, 20s, 40s, 60s max).
- Crash loop protection: max 5 restarts in 10 minutes, then 5-minute cooldown.
- Health state saved to `data/watchdog_state.json`.
- Special exit codes: `42` = restart, `43` = git pull + restart.

### Auto-Start on Boot (Silent)

The project includes `start_silent.vbs` which launches both CLIProxyAPI and the bot with no visible windows.

**Setup:**

1. Edit `start_silent.vbs` to match your paths:

```vbs
projectDir = "C:\path\to\progressive-agent"
proxyDir   = projectDir & "\CLIProxyAPI"
pythonExe  = "C:\path\to\python.exe"
```

2. Create a shortcut to `start_silent.vbs`.
3. Place the shortcut in the Windows Startup folder:

```
Win+R -> shell:startup -> [paste shortcut here]
```

The VBS script will:
- Check if CLIProxyAPI is already running (skip if yes).
- Start CLIProxyAPI in the background.
- Wait 5 seconds for the proxy to initialize.
- Check if the bot is already running (skip if yes).
- Start the bot via the watchdog in the background.

### Windows Task Scheduler (Alternative)

1. Open Task Scheduler (`taskschd.msc`).
2. Create Basic Task:
   - **Name**: Progressive Agent
   - **Trigger**: At startup (or At log on)
   - **Action**: Start a program
   - **Program**: `wscript.exe`
   - **Arguments**: `"C:\path\to\progressive-agent\start_silent.vbs"`
3. Check "Run with highest privileges" if needed.

---

## Linux / macOS Deployment

### Manual Start

```bash
cd /path/to/progressive-agent
python -m src.main
```

### Using the Watchdog

```bash
python -m src.watchdog
```

### systemd Service (Linux)

Create `/etc/systemd/system/progressive-agent.service`:

```ini
[Unit]
Description=Progressive Agent - Personal AI Assistant
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/progressive-agent
ExecStart=/home/YOUR_USERNAME/.local/bin/uv run python -m src.watchdog
Restart=always
RestartSec=10

# Environment
Environment=HOME=/home/YOUR_USERNAME
EnvironmentFile=/home/YOUR_USERNAME/progressive-agent/.env

# Logging
StandardOutput=append:/home/YOUR_USERNAME/progressive-agent/data/service.log
StandardError=append:/home/YOUR_USERNAME/progressive-agent/data/service.log

[Install]
WantedBy=multi-user.target
```

If `uv` is not installed, use the system Python path instead:

```ini
ExecStart=/usr/bin/python3 -m src.watchdog
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable progressive-agent
sudo systemctl start progressive-agent

# Check status
sudo systemctl status progressive-agent

# View logs
journalctl -u progressive-agent -f
```

### Start Script (scripts/start.sh)

Create `scripts/start.sh`:

```bash
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Load .env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Ensure data directory exists
mkdir -p data

# Start with watchdog
echo "Starting Progressive Agent ($(date))"
exec python -m src.watchdog
```

```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

### Screen / tmux (Quick & Dirty)

```bash
# Screen
screen -S agent
python -m src.watchdog
# Detach: Ctrl+A, D
# Reattach: screen -r agent

# tmux
tmux new-session -s agent
python -m src.watchdog
# Detach: Ctrl+B, D
# Reattach: tmux attach -t agent
```

---

## Docker Deployment

### Dockerfile

Create `Dockerfile` in the project root:

```dockerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files first (for Docker layer caching)
COPY pyproject.toml ./

# Install Python dependencies
RUN uv sync --no-dev

# Copy project files
COPY . .

# Create data directory
RUN mkdir -p data

# Run the bot via watchdog
CMD ["python", "-m", "src.watchdog"]
```

### docker-compose.yml

```yaml
version: "3.8"

services:
  agent:
    build: .
    container_name: progressive-agent
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data          # Persist database and logs
      - ./config:/app/config      # Configuration
      - ./soul:/app/soul          # Soul files
      - ./skills:/app/skills      # Skill definitions
    environment:
      - TZ=Europe/Kiev
```

### Build and Run

```bash
# Build
docker compose build

# Run
docker compose up -d

# View logs
docker compose logs -f agent

# Stop
docker compose down
```

### Notes on Docker

- The `data/` volume persists the SQLite databases (memory, costs) and logs across restarts.
- If you use CLIProxyAPI (Claude subscription proxy), it must run on the host machine. Use `host.docker.internal` as the proxy URL:

```bash
# In .env
CLAUDE_PROXY_URL=http://host.docker.internal:8317/v1
```

- Some tools that depend on the local system (clipboard, screenshots, browser automation) will not work inside Docker.
- For full functionality, native deployment (systemd or Windows service) is recommended.

---

## Oracle Cloud Free Tier

Oracle Cloud offers an always-free VM (1 OCPU, 1 GB RAM, ARM) that can run the bot 24/7 at zero cost.

### 1. Create an Oracle Cloud Account

Go to [cloud.oracle.com](https://cloud.oracle.com/) and sign up for a free account. You get:
- 2 AMD VMs (1/8 OCPU, 1 GB RAM each)
- or 4 ARM VMs (up to 4 OCPU, 24 GB RAM total, Ampere A1)

The ARM instance (4 OCPU, 24 GB RAM) is recommended for running the bot with local embeddings.

### 2. Create a Compute Instance

1. Go to Compute > Instances > Create Instance.
2. Choose:
   - **Shape**: VM.Standard.A1.Flex (ARM, Always Free)
   - **OCPU**: 1 (or more, up to 4 free)
   - **Memory**: 6 GB (or more, up to 24 GB free)
   - **Image**: Ubuntu 22.04 (or 24.04)
3. Add your SSH public key.
4. Create the instance.

### 3. Connect and Set Up

```bash
ssh ubuntu@YOUR_VM_IP

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.12
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt install python3.12 python3.12-venv python3.12-dev -y

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Install ffmpeg (for STT/TTS)
sudo apt install ffmpeg -y

# Install git
sudo apt install git -y
```

### 4. Deploy the Bot

```bash
# Clone the repo
git clone https://github.com/YourUsername/progressive-agent.git
cd progressive-agent

# Install dependencies
uv sync

# Create config
cp .env.example .env
nano .env  # Fill in your API keys

# Edit agent.toml
nano config/agent.toml  # Set allowed_users, timezone, etc.

# Create data directory
mkdir -p data

# Test run
python -m src.main
```

### 5. Set Up systemd Service

Create the service file as described in the [Linux section](#systemd-service-linux), then:

```bash
sudo systemctl enable progressive-agent
sudo systemctl start progressive-agent
```

### 6. Open Firewall (Oracle Cloud)

By default, Oracle Cloud blocks all incoming traffic except SSH. Since the bot only makes outgoing connections (to Telegram API, LLM APIs, etc.), no firewall changes are needed.

If you later add a web dashboard (Phase 4), you will need to:
1. Add an ingress rule in the VCN Security List for port 8080.
2. Open the port in the VM's iptables: `sudo iptables -I INPUT -p tcp --dport 8080 -j ACCEPT`.

### Important Notes for Oracle Cloud

- **No CLIProxyAPI**: The Claude subscription proxy requires a desktop with Claude Code CLI. On a headless server, use `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, or other cloud LLM providers instead.
- **ARM Architecture**: Most Python packages support ARM (aarch64). fastembed (ONNX Runtime) works on ARM.
- **Disk Space**: The free tier includes 50 GB boot volume. The bot uses ~2 GB (dependencies + data).
- **Auto-updates**: Set up a cron job or use the bot's built-in self-update (exit code 43 triggers `git pull` via the watchdog).

---

## Post-Deployment Checks

After deploying, verify everything works:

### 1. Bot Responds

Send a message to your bot on Telegram. You should get a response within a few seconds.

### 2. Check Logs

```bash
# Application log
tail -f data/agent.log

# Watchdog state
cat data/watchdog_state.json
```

### 3. Verify Tools

Send these test messages to the bot:

| Message | Expected Tool |
|---------|---------------|
| "What's the weather?" | `weather` |
| "Search for latest AI news" | `web_search` |
| "What time is it?" | Direct response (no tool needed) |
| "List files on Desktop" | `file_list` |

### 4. Check Monitors

Look for monitor registration in the startup log:

```
Crypto monitor scheduled (every 2 min)
Subscription monitor scheduled (daily at 09:00)
NewsRadar monitor scheduled (every 4 hours)
```

### 5. Startup Notification

If configured correctly, the bot sends a startup message to the owner with a summary of loaded tools, skills, and monitors.

---

## Troubleshooting

### Bot does not respond

1. Check that `TELEGRAM_BOT_TOKEN` is correct in `.env`.
2. Check that your Telegram user ID is in `config/agent.toml` under `[telegram] allowed_users`.
3. Check `data/agent.log` for errors.

### "No LLM provider available"

At least one LLM provider must be configured:
- Set `CLAUDE_PROXY_URL` and ensure CLIProxyAPI is running, or
- Set `ANTHROPIC_API_KEY`, or
- Set `MISTRAL_API_KEY` (free), or
- Set `OPENAI_API_KEY`.

### Memory/embedding errors on first run

The first run downloads the fastembed model (~90 MB). Ensure internet access is available. The model is cached in `~/.cache/fastembed/`.

### SQLite errors

Ensure the `data/` directory exists and is writable:

```bash
mkdir -p data
chmod 755 data
```

### High memory usage

The bot uses ~300-500 MB RAM under normal operation. If memory is tight:
- Reduce `max_context_memories` in `config/agent.toml`.
- Disable monitors you do not need (remove their config sections or API keys).
- Use a smaller embedding model (not recommended for multilingual support).

### Watchdog keeps restarting

Check `data/watchdog_state.json` for crash details. Common causes:
- Missing API keys
- Network connectivity issues
- Python dependency conflicts

If the watchdog detects a crash loop (5 restarts in 10 minutes), it pauses for 5 minutes before trying again.
