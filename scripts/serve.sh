#!/usr/bin/env bash
# Run the Vyuha web console. Defaults to localhost:8601.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/uvicorn vyuha.api.server:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8601}"
