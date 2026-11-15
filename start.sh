#!/bin/bash
#
# Local development launcher: the API and the Vite dev server together, in one
# terminal, stopped together with Ctrl+C. The Windows equivalent is start.ps1.
#
# This is for development only. A deployment runs the single container in the
# Dockerfile, where the backend serves the built frontend itself.

set -u
cd "$(dirname "$0")" || exit 1

API_URL="http://localhost:8001"
UI_URL="http://localhost:5173"

stop_both() {
    kill "$api_pid" "$ui_pid" 2>/dev/null
    exit
}

printf 'Compliance Panel — local development\n\n'

printf 'API  -> %s\n' "$API_URL"
uv run python -m backend.main &
api_pid=$!

# The dev server proxies /api to the backend, so give the backend a moment to
# bind its port before the first proxied request can arrive.
sleep 2

printf 'UI   -> %s\n' "$UI_URL"
(cd frontend && npm run dev) &
ui_pid=$!

trap stop_both SIGINT SIGTERM

printf '\nBoth are up. Open %s — Ctrl+C here stops the pair.\n' "$UI_URL"
wait
