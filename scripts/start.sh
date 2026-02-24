#!/usr/bin/env bash
# Progressive Agent — start script (Linux/Mac)

set -e

# cd to project root (parent of scripts/)
cd "$(dirname "$0")/.."

echo "=== Progressive Agent ==="
echo "Project root: $(pwd)"

# Check Python 3.11+
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$cmd"
            echo "Python found: $cmd ($version)"
            break
        else
            echo "Found $cmd ($version) but need 3.11+"
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.11+ not found. Install it first."
    exit 1
fi

# Check .env
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found."
    echo "Run: cp .env.example .env and fill in your API keys."
    exit 1
fi

echo "Starting bot..."
exec "$PYTHON" -m src.main
