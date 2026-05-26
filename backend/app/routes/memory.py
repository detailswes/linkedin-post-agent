from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.settings import MAX_POSTS_STORED, MAX_SAVED_DRAFTS
from app.mongo import mongo_db, now_ts
from app.services.linkedin import do_linkedin_post, token_status as linkedin_token_status
from app.services.security import get_active_token, require_csrf, require_user_id
from app.services.tone_memory import (
    ensure_post_style_metadata,
    refresh_tone_profile_from_posted,
    refresh_writer_profile,
    update_tone_on_approval,
)


router = APIRouter()


class SaveDraftBody(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=32000)
    session_id: str | None = None
    source_draft_id: str | None = None


@router.get("/api/memory")
async def get_memory(request: Request):
    db = mongo_db()
    user_id = await require_user_id(request)
    user = await db.users.find_one({"id": str(user_id)})
    if not user:
        raise HTTPException(401, "Not authenticated")

    posts = await db.posts.find(
        {"user_id": str(user_id), "posted_to_linkedin": True},
        sort=[("created_at", -1)],
        limit=MAX_POSTS_STORED,
    ).to_list(length=MAX_POSTS_STORED)

    saved = await db.saved_post_drafts.find(
        {"user_id": str(user_id)},
        sort=[("created_at", -1)],
        limit=MAX_SAVED_DRAFTS,
    ).to_list(length=MAX_SAVED_DRAFTS)

    tp = await refresh_tone_profile_from_posted(str(user_id))
    await refresh_writer_profile(str(user_id))

    return {
        "posts": [
            {
                "id": str(p.get("id")),
                "topic": p.get("topic"),
                "content": p.get("content"),
                "outcome": "approved",
                "feedback": None,
                "posted_to_linkedin": bool(p.get("posted_to_linkedin")),
                "created_at": int(p.get("created_at") or int(time.time())),
                "iteration": int(p.get("iteration") or 1),
            }
            for p in posts
        ],
        "saved_drafts": [
            {
                "id": str(s.get("id")),
                "topic": s.get("topic") or "",
                "content": s.get("content") or "",
                "created_at": int(s.get("created_at") or int(time.time())),
            }
            for s in saved
        ],
        "tone_profile": {
            "approved_count": int(tp.get("approved_count") or 0),
            "rejected_count": int(tp.get("rejected_count") or 0),
            "common_feedback": list(tp.get("common_feedback") or []),
            "approved_samples": list(tp.get("approved_samples") or []),
        },
        "writer_profile": tp.get("profile") or {},
    }


@router.post("/api/memory/saved-drafts")
async def save_draft(req: SaveDraftBody, request: Request):
    db = mongo_db()
    require_csrf(request)
    user_id = await require_user_id(request)
    user = await db.users.find_one({"id": str(user_id)})
    if not user:
        raise HTTPException(401, "Not authenticated")

    topic = req.topic.strip()
    content = req.content.strip()
    if not topic or not content:
        raise HTTPException(400, "Topic and content are required")

    token = await get_active_token(user_id, provider="linkedin")
    if not token:
        raise HTTPException(403, "Connect LinkedIn to save drafts.")

    # Same topic + body as an existing saved draft → idempotent (no duplicate rows).
    existing = await db.saved_post_drafts.find_one(
        {"user_id": str(user_id), "topic": topic, "content": content}
    )
    if existing:
        return {
            "id": str(existing.get("id")),
            "created_at": int(existing.get("created_at") or int(time.time())),
            "already_saved": True,
        }

    count = await db.saved_post_drafts.count_documents({"user_id": str(user_id)})
    if count >= MAX_SAVED_DRAFTS:
        raise HTTPException(400, f"Maximum {MAX_SAVED_DRAFTS} saved drafts. Delete one to add more.")

    now = now_ts()
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": str(user_id),
        "topic": topic,
        "content": content,
        "session_id": (req.session_id or "").strip() or None,
        "source_draft_id": (req.source_draft_id or "").strip() or None,
        "created_at": now,
        "updated_at": now,
    }
    await db.saved_post_drafts.insert_one(doc)
    return {"id": doc["id"], "created_at": doc["created_at"], "already_saved": False}


@router.delete("/api/memory/saved-drafts/{draft_id}")
async def delete_saved_draft(draft_id: str, request: Request):
    try:
        uuid.UUID(draft_id)
    except Exception:
        raise HTTPException(400, "Invalid draft id")
    db = mongo_db()
    require_csrf(request)
    user_id = await require_user_id(request)
    res = await db.saved_post_drafts.delete_one({"id": draft_id, "user_id": str(user_id)})
    if res.deleted_count == 0:
        raise HTTPException(404, "Draft not found")
    return {"status": "deleted"}


@router.post("/api/memory/saved-drafts/{draft_id}/publish")
async def publish_saved_draft(draft_id: str, request: Request):
    try:
        uuid.UUID(draft_id)
    except Exception:
        raise HTTPException(400, "Invalid draft id")

    db = mongo_db()
    require_csrf(request)
    user_id = await require_user_id(request)

    user = await db.users.find_one({"id": str(user_id)})
    if not user:
        raise HTTPException(401, "Not authenticated")

    doc = await db.saved_post_drafts.find_one({"id": draft_id, "user_id": str(user_id)})
    if not doc:
        raise HTTPException(404, "Draft not found")

    topic = (doc.get("topic") or "").strip()
    content = (doc.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "Draft has no content")

    token = await get_active_token(user_id, provider="linkedin")
    if not token:
        raise HTTPException(403, "Connect LinkedIn to post.")

    if linkedin_token_status(token.get("expires_at")) == "expired":
        await db.oauth_tokens.update_one(
            {"user_id": str(user_id), "provider": "linkedin", "revoked_at": None},
            {"$set": {"revoked_at": now_ts()}},
        )
        return {
            "linkedin_posted": False,
            "needs_reconnect": True,
            "linkedin_result": {"success": False, "expired": True, "error": "LinkedIn token expired — reconnect."},
        }

    urn = user.get("linkedin_person_urn")
    if not urn:
        raise HTTPException(400, "LinkedIn profile not linked.")

    try:
        result = do_linkedin_post(token["access_token"], urn, content)
    except Exception as e:  # noqa: BLE001
        return {"linkedin_posted": False, "needs_reconnect": False, "linkedin_result": {"success": False, "error": str(e)}}

    await db.oauth_tokens.update_one(
        {"user_id": str(user_id), "provider": "linkedin", "revoked_at": None},
        {"$set": {"last_used_at": now_ts()}},
    )

    if result.get("expired"):
        await db.oauth_tokens.update_one(
            {"user_id": str(user_id), "provider": "linkedin", "revoked_at": None},
            {"$set": {"revoked_at": now_ts()}},
        )
        return {"linkedin_posted": False, "needs_reconnect": True, "linkedin_result": result}

    if result.get("success"):
        now = now_ts()
        post_doc = {
            "id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "session_id": doc.get("session_id"),
            "topic": topic or (doc.get("topic") or ""),
            "content": content,
            "outcome": "approved",
            "feedback": None,
            "iteration": 1,
            "variant": None,
            "posted_to_linkedin": True,
            "linkedin_ugc_id": result.get("id"),
            "style_metadata": None,
            "style_version": 1,
            "created_at": now,
        }
        await ensure_post_style_metadata(post_doc)
        await db.posts.insert_one(post_doc)
        await db.saved_post_drafts.delete_one({"id": draft_id, "user_id": str(user_id)})
        await refresh_tone_profile_from_posted(str(user_id))
        await refresh_writer_profile(str(user_id))
        await update_tone_on_approval(str(user_id), content)
        return {"linkedin_posted": True, "needs_reconnect": False, "linkedin_result": result}

    return {"linkedin_posted": False, "needs_reconnect": False, "linkedin_result": result}


@router.delete("/api/memory")
async def clear_memory(request: Request):
    db = mongo_db()
    require_csrf(request)
    user_id = await require_user_id(request)
    user = await db.users.find_one({"id": str(user_id)})
    if not user:
        raise HTTPException(401, "Not authenticated")

    await db.posts.delete_many({"user_id": str(user_id)})
    now = now_ts()
    await db.tone_profiles.update_one(
        {"user_id": str(user_id)},
        {"$set": {"approved_count": 0, "rejected_count": 0, "common_feedback": [], "approved_samples": [], "profile": {}, "updated_at": now}},
        upsert=True,
    )
    return {"status": "memory cleared"}
