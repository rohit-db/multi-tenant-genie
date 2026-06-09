#!/usr/bin/env bash
# edge/run.sh — run the edge / token-broker front door locally.
#
# Reads edge/.env (copy from edge/.env.example first). The edge listens on
# EDGE_PORT (default 9000) and reverse-proxies into the deployed Databricks
# App, injecting the edge SP bearer. Open http://localhost:<EDGE_PORT>.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f edge/.env ]; then
  echo "✗ edge/.env not found. Copy edge/.env.example to edge/.env and fill it in." >&2
  exit 1
fi

# Export EDGE_PORT for uvicorn (config.py also reads edge/.env directly).
PORT="$(awk -F= '/^EDGE_PORT=/{print $2}' edge/.env | tr -d '[:space:]')"
PORT="${PORT:-9000}"

echo "▸ Edge front door on http://127.0.0.1:${PORT}  (Ctrl-C to stop)" >&2
exec uvicorn edge.app:app --reload --host 127.0.0.1 --port "${PORT}"
