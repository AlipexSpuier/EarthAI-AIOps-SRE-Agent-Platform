#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
args=()
if [[ -f .env ]]; then args+=(--env-file .env); fi
exec .venv/bin/uvicorn backend.main:app --host "${EARTHAI_HOST:-0.0.0.0}" --port "${EARTHAI_PORT:-8000}" --workers 1 "${args[@]}" --proxy-headers --forwarded-allow-ips 127.0.0.1
