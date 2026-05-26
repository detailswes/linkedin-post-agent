#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif [[ -f "../.venv/bin/python" ]]; then
  PY="../.venv/bin/python"
else
  PY="python3"
fi

exec "$PY" worker.py
