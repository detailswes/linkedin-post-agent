"""SSE endpoint that replays persisted generation_job_events to the client."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.sse import make_event
from app.mongo import mongo_db
from app.services.security import require_user_id


async def stream_job_events(job_id: str, request: Request):
    try:
        uuid.UUID(job_id)
    except Exception:
        raise HTTPException(404, "Job not found")

    # Authenticate + authorize ONCE, BEFORE the StreamingResponse is constructed.
    # If we did this inside the generator the 200 OK headers would already be
    # flushed by the time a 401/403 is raised, corrupting the response.
    auth_user_id = await require_user_id(request)
    db = mongo_db()
    initial_job = await db.generation_jobs.find_one({"id": job_id})
    if not initial_job:
        raise HTTPException(404, "Job not found")
    if initial_job.get("user_id") != str(auth_user_id):
        raise HTTPException(403, "Forbidden")

    async def sse():
        last_seq = 0
        idle_ticks = 0
        first = True
        while True:
            had_rows = False
            db = mongo_db()
            job = await db.generation_jobs.find_one({"id": job_id})
            if not job:
                yield make_event("error", {"message": "Job not found"})
                return
            if first and job.get("status") == "queued":
                yield make_event("status", {"message": "Queued — waiting for background worker."})
                first = False

            rows = (
                await db.generation_job_events.find(
                    {"job_id": job_id, "seq": {"$gt": last_seq}},
                    sort=[("seq", 1)],
                ).to_list(length=500)
            )
            had_rows = len(rows) > 0
            for row in rows:
                yield row.get("chunk")
                last_seq = int(row.get("seq") or last_seq)

            st = job.get("status")
            if st in ("completed", "failed"):
                # If the job finished without ever emitting `variants`, emit a terminal error so the
                # client always gets a MessageEvent (not only a silent connection close).
                if st == "completed":
                    has_variants = await db.generation_job_events.find_one(
                        {"job_id": job_id, "chunk": {"$regex": "^event: variants\\n"}},
                    )
                    if not has_variants:
                        yield make_event(
                            "error",
                            {
                                "message": (
                                    "Job completed but no drafts were streamed. "
                                    "Check worker logs and AGENT_SERVICE_URL."
                                ),
                            },
                        )
                return

            if had_rows:
                idle_ticks = 0
            else:
                idle_ticks += 1
            if idle_ticks > 6000:
                yield make_event("error", {"message": "Job stream timed out."})
                return

            await asyncio.sleep(0.15)

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
