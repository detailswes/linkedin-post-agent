#!/usr/bin/env python3
"""
Background worker: claims queued generation_jobs rows and runs the LLM pipeline.

Run from the backend directory (same as uvicorn), with the same virtualenv:

  cd backend && ../.venv/bin/python worker.py

Keep this running alongside the API server.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure `import app.*` resolves when cwd is backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))


async def main() -> None:
    from app.services.generation import run_one_worker_iteration  # noqa: PLC0415

    tick = 0
    HEARTBEAT_EVERY_TICKS = 200
    while True:
        try:
            await run_one_worker_iteration()
        except Exception as exc:
            print(f"[worker] error: {exc}", flush=True)
        
        tick += 1
        if tick % HEARTBEAT_EVERY_TICKS == 0:
            print(f"[worker] heartbeat tick {tick} (still polling)", flush=True)

        await asyncio.sleep(0.15)


if __name__ == "__main__":
    asyncio.run(main())
