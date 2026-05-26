"""Job queue: enqueue requests, claim them in the worker, persist SSE events."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException, Request
from pymongo import ReturnDocument

from app.core.rate_limit import token_bucket_allow
from app.core.settings import GEN_BURST, GEN_RATE_PER_MIN
from app.core.sse import make_event
from app.mongo import mongo_db, now_ts
from app.services.security import require_csrf, require_user_id
from app.services.tone_memory import build_memory_context_db

from .models import GenerateRequest
from .pipeline import persisting_event_stream
import time as _time

def _ts() -> str:
    return _time.strftime("%H:%M:%S")

async def enqueue_generation(req: GenerateRequest, request: Request):
    try:
        uuid.UUID(req.session_id)
    except Exception:
        raise HTTPException(400, "Invalid session_id")

    db = mongo_db()
    require_csrf(request)
    auth_user_id = await require_user_id(request)
    if not token_bucket_allow(f"enqueue:{auth_user_id}", GEN_RATE_PER_MIN, GEN_BURST, cost=1.0):
        raise HTTPException(429, "Too many generation requests. Please wait a minute and try again.")

    sess = await db.generation_sessions.find_one({"id": req.session_id})
    if not sess:
        raise HTTPException(404, "Session not found")
    if sess.get("user_id") != str(auth_user_id):
        raise HTTPException(403, "Forbidden")

    active = await db.generation_jobs.find_one(
        {"session_id": req.session_id, "status": {"$in": ["queued", "running"]}},
        projection={"_id": 1},
    )
    if active:
        raise HTTPException(409, "A generation is already queued or running for this session.")

    iteration = int(sess.get("iteration") or 1)
    job_id = str(uuid.uuid4())
    await db.generation_jobs.insert_one(
        {
            "id": job_id,
            "user_id": str(auth_user_id),
            "session_id": req.session_id,
            "iteration": iteration,
            "variant": req.variant,
            "feedback": (req.feedback or "").strip() or None,
            "status": "queued",
            "error": None,
            "created_at": now_ts(),
            "started_at": None,
            "completed_at": None,
        }
    )
    return {"job_id": job_id}


async def _job_max_seq(job_id: str) -> int:
    db = mongo_db()
    row = await db.generation_job_events.find_one({"job_id": job_id}, sort=[("seq", -1)])
    return int((row or {}).get("seq") or 0)


async def _claim_next_job() -> str | None:
    db = mongo_db()
    now = now_ts()
    job = await db.generation_jobs.find_one_and_update(
        {"status": "queued"},
        {"$set": {"status": "running", "started_at": now}},
        sort=[("created_at", 1)],
        return_document=ReturnDocument.AFTER,
    )
    return (job or {}).get("id")


async def _mark_job_failed(job_id: str, err: str) -> None:
    db = mongo_db()
    job = await db.generation_jobs.find_one({"id": job_id})
    if not job:
        return
    if job.get("status") not in ("running", "queued"):
        return
    now = now_ts()
    await db.generation_jobs.update_one(
        {"id": job_id},
        {"$set": {"status": "failed", "error": err[:2000], "completed_at": now}},
    )
    nxt = (await _job_max_seq(job_id)) + 1
    await db.generation_job_events.insert_one(
        {
            "job_id": job_id,
            "seq": nxt,
            "chunk": make_event("error", {"message": err[:500]}),
            "created_at": now,
        }
    )


async def _run_generation_job_async(job_id: str) -> None:
    db = mongo_db()
    job = await db.generation_jobs.find_one({"id": job_id})
    if not job:
        return
    sess = await db.generation_sessions.find_one({"id": job.get("session_id")})
    if not sess:
        raise RuntimeError("Session not found for job")

    user_id = sess.get("user_id")
    session_id = sess.get("id")
    iteration = int(job.get("iteration") or 1)
    topic = (sess.get("topic") or "").strip()
    variant_id = job.get("variant")
    feedback_override = job.get("feedback")
    session_feedback = sess.get("last_feedback")

    memory_context = await build_memory_context_db(user_id) if user_id else ""

    seq = await _job_max_seq(job_id)
    try:
        async for chunk in persisting_event_stream(
            session_id,
            user_id,
            topic,
            iteration,
            session_feedback,
            memory_context,
            variant_id=variant_id,
            feedback_override=feedback_override,
        ):
            seq += 1
            await db.generation_job_events.insert_one(
                {"job_id": job_id, "seq": seq, "chunk": chunk, "created_at": now_ts()}
            )

        await db.generation_jobs.update_one(
            {"id": job_id},
            {"$set": {"status": "completed", "completed_at": now_ts()}},
        )
    except Exception as e:
        await _mark_job_failed(job_id, str(e))


_worker_lock = asyncio.Lock()


async def run_one_worker_iteration() -> None:
    """Called repeatedly by `backend/worker.py`. Claims and runs one job, if any."""
    async with _worker_lock:
        jid = await _claim_next_job()
        if not jid:
            return
        db = mongo_db()
        job = await db.generation_jobs.find_one(
            {"id": jid},
            projection = {"session_id": 1, "user_id": 1, "iteration": 1, "variant": 1},
        )
        print(
            f"[worker {_ts()}] claimed job {jid}",
             f"session={(job or {}).get('session_id')} "
            f"user={(job or {}).get('user_id')} "
            f"iteration={(job or {}).get('iteration')} "
            f"variant={(job or {}).get('variant')}",
            flush=True,
        )

        started = _time.monotonic()
        try:
            await _run_generation_job_async(jid)
            elapsed = _time.monotonic() - started
            final = await db.generation_jobs.find_one(
                {"id": jid}, projection={"status": 1, "error": 1}
            )
            status = (final or {}).get("status")
            if status == "completed":
                print(f"[worker {_ts()}] completed job={jid} in {elapsed:.2f}s", flush=True)
            else:
                print(
                    f"[worker {_ts()}] finished job={jid} status={status} "
                    f"in {elapsed:.2f}s error={(final or {}).get('error')!r}",
                    flush=True,
                )
        except Exception as e:
            elapsed = _time.monotonic() - started
            print(f"[worker {_ts()}] EXCEPTION job={jid} in {elapsed:.2f}s: {e}", flush=True)
            await _mark_job_failed(jid, str(e))