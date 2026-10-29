#!/usr/bin/env bash
# Starts the API (http://127.0.0.1:8000) and the web app (http://localhost:5173).
set -euo pipefail
cd "$(dirname "$0")"
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 &
API=$!
trap 'kill $API 2>/dev/null' EXIT
(cd frontend && npm run dev)
