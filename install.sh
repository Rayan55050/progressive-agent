#!/usr/bin/env bash
# Progressive Agent — Setup (Linux / macOS)
# Run: chmod +x install.sh && ./install.sh

set -e
cd "$(dirname "$0")"

echo ""
echo "Progressive Agent — Setup"
echo "========================"
echo ""

# Find Python 3.11+
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Python 3.11+ not found."
    echo "Install it:"
    echo "  macOS:  brew install python@3.12"
    echo "  Ubuntu: sudo apt install python3.12 python3-pip"
    echo "  Fedora: sudo dnf install python3.12"
    exit 1
fi

echo "Using: $PYTHON ($($PYTHON --version 2>&1))"
echo ""

# Install dependencies
echo "Installing dependencies..."
$PYTHON -m pip install -r requirements.txt --disable-pip-version-check
echo ""

# Run interactive setup
$PYTHON scripts/setup.py
