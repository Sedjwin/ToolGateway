#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

source .venv/bin/activate

HOST="${TOOLGATEWAY_HOST:-127.0.0.1}"
PORT="${TOOLGATEWAY_PORT:-13377}"

exec uvicorn app.main:app --host "$HOST" --port "$PORT"
