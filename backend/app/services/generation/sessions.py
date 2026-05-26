"""Generation-session lifecycle: start, get, delete."""
from __future__ import annotations

import uuid

from fastapi import HTTPException, Request

from app.mongo import mongo_db, now_ts
from app.services.security import require_csrf, require_user_id

from .models import StartRequest


async def start_session(req: StartRequest, request: Request):
    if not req.topic.strip():
        raise HTTPException(400, "Topic cannot be empty")

    db = mongo_db()
    require_csrf(request)
    user_id = await require_user_id(request)
    now = now_ts()
    session_id = str(uuid.uuid4())
    await db.generation_sessions.insert_one(
        {
            "id": session_id,
            "user_id": str(user_id),
            "topic": req.topic.strip(),
            "status": "pending",
            "iteration": 1,
            "last_feedback": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    return {"session_id": session_id}


async def get_session(session_id: str, request: Request):
    try:
        uuid.UUID(session_id)
    except Exception:
        raise HTTPException(404, "Session not found")
    db = mongo_db()
    auth_user_id = await require_user_id(request)
    sess = await db.generation_sessions.find_one({"id": session_id})
    if not sess:
        raise HTTPException(404, "Session not found")
    if sess.get("user_id") != str(auth_user_id):
        raise HTTPException(403, "Forbidden")
    return {
        "topic": sess.get("topic"),
        "status": sess.get("status"),
        "feedback": sess.get("last_feedback"),
        "iteration": int(sess.get("iteration") or 1),
    }


async def delete_session(session_id: str, request: Request):
    try:
        uuid.UUID(session_id)
    except Exception:
        return {"status": "deleted"}
    db = mongo_db()
    require_csrf(request)
    auth_user_id = await require_user_id(request)
    sess = await db.generation_sessions.find_one({"id": session_id})
    if sess:
        if sess.get("user_id") != str(auth_user_id):
            raise HTTPException(403, "Forbidden")
        await db.generation_sessions.update_one(
            {"id": session_id},
            {"$set": {"status": "deleted", "updated_at": now_ts()}},
        )
    return {"status": "deleted"}
