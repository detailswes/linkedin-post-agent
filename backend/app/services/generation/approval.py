"""
Approval / rejection flow.

Approve → publish the selected draft to LinkedIn → record the post & update
tone memory. Reject → optionally feed feedback back into a regeneration job.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, Request

from app.mongo import mongo_db, now_ts
from app.services.linkedin import do_linkedin_post, token_status
from app.services.security import get_active_token, require_csrf, require_user_id
from app.services.tone_memory import (
    ensure_post_style_metadata,
    refresh_tone_profile_from_posted,
    refresh_writer_profile,
    update_tone_on_approval,
    update_tone_on_rejection,
)

from .models import ApprovalRequest


async def _select_pending_draft(db, req: ApprovalRequest, iteration: int, auth_user_id) -> dict | None:
    if req.draft_id:
        try:
            uuid.UUID(req.draft_id)
        except Exception:
            raise HTTPException(400, "Invalid draft_id")
        draft = await db.drafts.find_one({"id": req.draft_id, "session_id": req.session_id})
        if not draft:
            raise HTTPException(404, "Draft not found for this session")
        if draft.get("user_id") and draft.get("user_id") != str(auth_user_id):
            raise HTTPException(403, "Forbidden")
        return draft

    q: dict = {"session_id": req.session_id, "status": "pending", "iteration": iteration}
    if req.variant:
        q["variant"] = req.variant
    return await db.drafts.find_one(q, sort=[("created_at", -1)])


async def _publish_to_linkedin(db, sess, draft: dict, iteration: int) -> dict:
    user = await db.users.find_one({"id": sess.get("user_id")})
    if not user:
        return {"success": False, "expired": True, "error": "User not found."}

    token = await get_active_token(uuid.UUID(user["id"]), provider="linkedin")
    if not token:
        return {
            "success": False,
            "expired": True,
            "error": "LinkedIn not connected — please reconnect.",
        }
    if token_status(token.get("expires_at")) == "expired":
        await db.oauth_tokens.update_one(
            {"user_id": user["id"], "provider": "linkedin", "revoked_at": None},
            {"$set": {"revoked_at": now_ts()}},
        )
        return {
            "success": False,
            "expired": True,
            "error": "LinkedIn token expired — please reconnect.",
        }

    try:
        result = do_linkedin_post(
            token["access_token"],
            user["linkedin_person_urn"],
            draft.get("content") or "",
        )
    except Exception as e:  # noqa: BLE001 - surfaced verbatim to the client
        return {"success": False, "expired": False, "error": str(e)}

    await db.oauth_tokens.update_one(
        {"user_id": user["id"], "provider": "linkedin", "revoked_at": None},
        {"$set": {"last_used_at": now_ts()}},
    )

    if result.get("expired"):
        await db.oauth_tokens.update_one(
            {"user_id": user["id"], "provider": "linkedin", "revoked_at": None},
            {"$set": {"revoked_at": now_ts()}},
        )
        return result

    if result.get("success"):
        post_doc = {
            "id": str(uuid.uuid4()),
            "user_id": user["id"],
            "session_id": draft.get("session_id"),
            "topic": draft.get("topic"),
            "content": draft.get("content"),
            "outcome": "approved",
            "feedback": None,
            "iteration": iteration,
            "variant": draft.get("variant"),
            "posted_to_linkedin": True,
            "linkedin_ugc_id": result.get("id"),
            "style_metadata": None,
            "style_version": 1,
            "created_at": now_ts(),
        }
        await ensure_post_style_metadata(post_doc)
        await db.posts.insert_one(post_doc)
        await refresh_tone_profile_from_posted(user["id"])
        await refresh_writer_profile(user["id"])
        await update_tone_on_approval(user["id"], draft.get("content") or "")

    return result


async def approve_post(req: ApprovalRequest, request: Request):
    try:
        uuid.UUID(req.session_id)
    except Exception:
        raise HTTPException(404, "Session not found")

    db = mongo_db()
    require_csrf(request)
    auth_user_id = await require_user_id(request)

    sess = await db.generation_sessions.find_one({"id": req.session_id})
    if not sess:
        raise HTTPException(404, "Session not found")
    if sess.get("user_id") != str(auth_user_id):
        raise HTTPException(403, "Forbidden")

    iteration = int(sess.get("iteration") or 1)
    pending_draft = await _select_pending_draft(db, req, iteration, auth_user_id)

    # ── APPROVE ────────────────────────────────────────────────────────────
    if req.approved:
        if not pending_draft:
            raise HTTPException(400, "No pending draft selected to approve")

        now = now_ts()
        await db.generation_sessions.update_one(
            {"id": req.session_id}, {"$set": {"status": "approved", "updated_at": now}}
        )
        await db.drafts.update_one(
            {"id": pending_draft["id"]},
            {"$set": {"status": "selected", "feedback": None, "updated_at": now}},
        )

        linkedin_result = await _publish_to_linkedin(db, sess, pending_draft, iteration)

        return {
            "status": "approved",
            "linkedin_posted": bool(linkedin_result.get("success")),
            "linkedin_result": linkedin_result,
            "needs_reconnect": bool(linkedin_result.get("expired")),
            "draft_id": str(pending_draft.get("id")),
            "variant": pending_draft.get("variant"),
        }

    # ── REJECT / REGENERATE ────────────────────────────────────────────────
    feedback_text = req.feedback.strip() or None
    now = now_ts()

    # Regenerate just the selected variant.
    if req.draft_id:
        if not pending_draft:
            raise HTTPException(400, "No pending draft selected to regenerate")
        prev_iteration = iteration
        new_iteration = prev_iteration + 1

        await db.drafts.update_one(
            {"id": pending_draft["id"]},
            {"$set": {"status": "rejected", "feedback": feedback_text, "updated_at": now}},
        )

        others = await db.drafts.find(
            {
                "session_id": req.session_id,
                "iteration": prev_iteration,
                "status": "pending",
                "id": {"$ne": pending_draft["id"]},
            }
        ).to_list(length=50)

        clones = [
            {
                "id": str(uuid.uuid4()),
                "user_id": d.get("user_id"),
                "session_id": d.get("session_id"),
                "topic": d.get("topic"),
                "content": d.get("content"),
                "status": "pending",
                "feedback": None,
                "iteration": new_iteration,
                "variant": d.get("variant"),
                "created_at": now,
                "updated_at": now,
            }
            for d in others
        ]
        if clones:
            await db.drafts.insert_many(clones)
            await db.drafts.update_many(
                {"session_id": req.session_id, "iteration": prev_iteration, "status": "pending"},
                {"$set": {"status": "rejected", "updated_at": now}},
            )

        if feedback_text:
            await update_tone_on_rejection(str(auth_user_id), feedback_text)

        await db.generation_sessions.update_one(
            {"id": req.session_id},
            {"$set": {"status": "pending", "iteration": new_iteration, "updated_at": now}},
        )
        return {
            "status": "regenerating_variant",
            "iteration": int(new_iteration),
            "variant": pending_draft.get("variant"),
            "draft_id": str(pending_draft.get("id")),
            "feedback": feedback_text,
        }

    # Regenerate everything.
    update_doc: dict = {"status": "rejected", "updated_at": now}
    update_doc["feedback"] = feedback_text
    await db.drafts.update_many(
        {"session_id": req.session_id, "iteration": iteration, "status": "pending"},
        {"$set": update_doc},
    )

    if feedback_text:
        await update_tone_on_rejection(str(auth_user_id), feedback_text)

    await db.generation_sessions.update_one(
        {"id": req.session_id},
        {
            "$set": {
                "iteration": iteration + 1,
                "last_feedback": feedback_text,
                "status": "pending",
                "updated_at": now,
            }
        },
    )
    return {"status": "regenerating_all", "iteration": int(iteration + 1)}
