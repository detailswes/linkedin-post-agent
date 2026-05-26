from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.services.linkedin import sync_linkedin_posts_into_db
from app.services.security import get_active_token, require_csrf, require_user_id


router = APIRouter()


@router.post("/api/linkedin/sync")
async def sync_linkedin_posts(request: Request):
    """
    Fetch the user's recent LinkedIn posts and store them in our DB.
    Best-effort: only imports text-based UGC posts we can access via API.
    """
    from app.mongo import mongo_db

    require_csrf(request)
    user_id = await require_user_id(request)
    db = mongo_db()
    user = await db.users.find_one({"id": str(user_id)})
    if not user:
        raise HTTPException(401, "Not authenticated")
    token = await get_active_token(user_id, provider="linkedin")
    if not token:
        raise HTTPException(400, "No active LinkedIn token. Reconnect LinkedIn.")

    imported = await sync_linkedin_posts_into_db(user, token, count=30)
    return {"imported": imported}

