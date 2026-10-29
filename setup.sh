#!/usr/bin/env bash
# One-time setup + deterministic demo seed. Requires Python 3.12 and Node 20+.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv backend/.venv
backend/.venv/bin/pip install -q -r backend/requirements.txt
(cd frontend && npm install --no-audit --no-fund)
backend/.venv/bin/python scripts/seed_demo.py
echo "Setup complete. Run ./start.sh"
