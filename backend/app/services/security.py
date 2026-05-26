from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid

from fastapi import HTTPException, Request, Response

from app.core.settings import (
    COOKIE_MAX_AGE,
    CSRF_COOKIE_NAME,
    IS_PROD,
    SESSION_COOKIE_NAME,
    SESSION_SECRET,
    SESSION_TTL_SECONDS,
    auth_cookie_samesite,
)
from app.mongo import mongo_db, now_ts


def cookie_secure_flag() -> bool:
    default = "1" if IS_PROD else "0"
    return os.getenv("COOKIE_SECURE", default).strip() in ("1", "true", "True")


def cookie_secure_for_auth() -> bool:
    """SameSite=None requires Secure; cross-site auth always uses HTTPS in production."""
    if auth_cookie_samesite() == "none":
        return True
    return cookie_secure_flag()


def hash_session_token(raw_token: str) -> str:
    if not SESSION_SECRET:
        raise RuntimeError("Missing SESSION_SECRET. Set it in backend/.env for secure sessions.")
    mac = hmac.new(SESSION_SECRET.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def issue_csrf_token(response: Response) -> str:
    csrf = secrets.token_urlsafe(32)
    ss = auth_cookie_samesite()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf,
        max_age=COOKIE_MAX_AGE,
        httponly=False,
        samesite=ss,
        secure=cookie_secure_for_auth(),
        path="/",
    )
    return csrf


def clear_auth_cookies(response: Response) -> None:
    ss = auth_cookie_samesite()
    sec = cookie_secure_for_auth()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite=ss, secure=sec, httponly=True)
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", samesite=ss, secure=sec, httponly=False)


async def create_auth_session(user_id: uuid.UUID, raw_token: str) -> dict:
    db = mongo_db()
    now = now_ts()
    doc = {
        "user_id": str(user_id),
        "session_token_hash": hash_session_token(raw_token),
        "expires_at": now + int(SESSION_TTL_SECONDS),
        "last_seen_at": now,
        "revoked_at": None,
        "created_at": now,
    }
    await db.auth_sessions.insert_one(doc)
    return doc


async def get_user_id_from_session_cookie(request: Request) -> uuid.UUID | None:
    db = mongo_db()
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return None
    try:
        token_hash = hash_session_token(raw)
    except Exception:
        return None
    row = await db.auth_sessions.find_one(
        {"session_token_hash": token_hash, "revoked_at": None},
        sort=[("created_at", -1)],
    )
    if not row:
        return None
    now = now_ts()
    if int(row.get("expires_at") or 0) <= now:
        await db.auth_sessions.update_one(
            {"session_token_hash": token_hash, "revoked_at": None},
            {"$set": {"revoked_at": now}},
        )
        return None
    await db.auth_sessions.update_one(
        {"session_token_hash": token_hash, "revoked_at": None},
        {"$set": {"last_seen_at": now}},
    )
    try:
        return uuid.UUID(str(row.get("user_id") or ""))
    except Exception:
        return None


async def require_user_id(request: Request) -> uuid.UUID:
    uid = await get_user_id_from_session_cookie(request)
    if not uid:
        raise HTTPException(401, "Not authenticated")
    return uid


async def bootstrap_anonymous_session(request: Request, response: Response) -> tuple[uuid.UUID, bool, str]:
    """
    Ensure a browser session maps to a user row (creates a guest if needed).
    Returns (user_id, created_new_guest, csrf_token_plaintext).
    """
    uid = await get_user_id_from_session_cookie(request)
    if uid:
        return uid, False, issue_csrf_token(response)

    db = mongo_db()
    now = now_ts()
    user_id = str(uuid.uuid4())
    await db.users.insert_one(
        {
            "id": user_id,
            "display_name": "Guest",
            "email": None,
            "is_guest": True,
            "created_at": now,
            "updated_at": now,
        }
    )
    await ensure_tone_profile(uuid.UUID(user_id))
    raw_session_token = secrets.token_urlsafe(32)
    await create_auth_session(uuid.UUID(user_id), raw_session_token)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_session_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite=auth_cookie_samesite(),
        secure=cookie_secure_for_auth(),
        path="/",
    )
    return uuid.UUID(user_id), True, issue_csrf_token(response)


def require_csrf(request: Request):
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    csrf_header = request.headers.get("x-csrf-token")
    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(403, "Missing or invalid CSRF token")


async def get_active_token(user_id: uuid.UUID, *, provider: str = "linkedin") -> dict | None:
    db = mongo_db()
    provider = (provider or "linkedin").strip().lower()
    return await db.oauth_tokens.find_one(
        {"user_id": str(user_id), "provider": provider, "revoked_at": None},
        sort=[("created_at", -1)],
    )


async def ensure_tone_profile(user_id: uuid.UUID) -> dict:
    db = mongo_db()
    row = await db.tone_profiles.find_one({"user_id": str(user_id)})
    if row:
        return row
    now = now_ts()
    row = {
        "user_id": str(user_id),
        "approved_count": 0,
        "rejected_count": 0,
        "approved_samples": [],
        "common_feedback": [],
        "profile": {},
        "profile_version": 1,
        "source_post_count": 0,
        "last_analyzed_at": None,
        "updated_at": now,
        "created_at": now,
    }
    await db.tone_profiles.insert_one(row)
    return row


async def upsert_oauth_token(
    *,
    user_id: uuid.UUID,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    scopes: str | None,
    issued_at,
    expires_at,
    last_used_at,
) -> dict:
    db = mongo_db()
    provider = (provider or "").strip().lower()
    now = now_ts()
    doc = {
        "user_id": str(user_id),
        "provider": provider,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "scopes": scopes,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "revoked_at": None,
        "last_used_at": last_used_at,
        "updated_at": now,
    }
    await db.oauth_tokens.update_one(
        {"user_id": str(user_id), "provider": provider},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return await db.oauth_tokens.find_one({"user_id": str(user_id), "provider": provider})


async def upsert_connected_account(
    *,
    user_id: uuid.UUID,
    provider: str,
    external_account_id: str,
    display_name: str | None = None,
    email: str | None = None,
    extra_metadata: dict | None = None,
) -> dict:
    db = mongo_db()
    provider = (provider or "").strip().lower()
    now = now_ts()
    await db.connected_accounts.update_one(
        {"user_id": str(user_id), "provider": provider},
        {
            "$set": {
                "external_account_id": external_account_id,
                "display_name": display_name,
                "email": email,
                "extra_metadata": extra_metadata or {},
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return await db.connected_accounts.find_one({"user_id": str(user_id), "provider": provider})