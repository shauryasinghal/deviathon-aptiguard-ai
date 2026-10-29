#!/usr/bin/env bash
# One-time setup + deterministic demo seed. Requires Python 3.12 and Node 20+.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Python 3.11+ required (set PYTHON=/path/to/python3.12)"; exit 1; }
command -v node >/dev/null || { echo "Node.js 20+ required"; exit 1; }
"$PY" -m venv backend/.venv
backend/.venv/bin/pip install -q -r backend/requirements.txt
(cd frontend && npm install --no-audit --no-fund)
backend/.venv/bin/python scripts/seed_demo.py
echo "Setup complete. Run ./start.sh"
