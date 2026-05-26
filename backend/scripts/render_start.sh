#!/usr/bin/env bash
# Render free tier: one web service runs background job worker and API.
set -euo pipefail
cd "$(dirname "$0")/.."

# Same variables Python reads in app.core.settings (fail before Gunicorn with a clear hint).
if [[ -z "${SESSION_SECRET:-}" && -z "${SECRET_KEY:-}" && -z "${APP_SESSION_SECRET:-}" ]]; then
  echo "[postforge-api] No session secret in container env. Set SESSION_SECRET or SECRET_KEY on this service in Render -> Environment, then redeploy." >&2
  exit 1
fi

python worker.py &
exec gunicorn -k uvicorn.workers.UvicornWorker -w 1 -b "0.0.0.0:${PORT:-8000}" app.main:app
