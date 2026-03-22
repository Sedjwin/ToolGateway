#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
source .venv/bin/activate
uvicorn app.main:app --host "${TOOLGATEWAY_HOST:-127.0.0.1}" --port "${TOOLGATEWAY_PORT:-8006}" --reload
