#!/usr/bin/env bash
# Progressive Agent -- Quick Start
# Clone, install, setup, and run in one script

set -e

echo "=== Progressive Agent Quick Start ==="
echo ""

# Clone the repository
if [ ! -d "progressive-agent" ]; then
    echo "[1/4] Cloning repository..."
    git clone https://github.com/progressive-ai-community/progressive-agent.git
else
    echo "[1/4] Repository already exists, pulling latest..."
    cd progressive-agent && git pull && cd ..
fi

cd progressive-agent

# Install dependencies
echo "[2/4] Installing dependencies..."
pip install -e .

# Run setup (copies .env.example, creates data directory, etc.)
echo "[3/4] Running setup..."
python scripts/setup.py

echo ""
echo "=== Setup complete ==="
echo ""
echo "Before starting, make sure you have filled in your API keys in .env:"
echo "  ANTHROPIC_API_KEY=sk-ant-..."
echo "  TELEGRAM_BOT_TOKEN=123456:ABC..."
echo "  OPENAI_API_KEY=sk-..."
echo "  TAVILY_API_KEY=tvly-..."
echo ""
echo "[4/4] Starting Progressive Agent..."
python -m src.main
