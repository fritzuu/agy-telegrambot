#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv
    uv pip install "python-telegram-bot[job-queue]" python-dotenv pillow "faster-whisper" "av<14" h2
fi

echo "Starting agy Telegram Bot..."
exec .venv/bin/python bot.py
