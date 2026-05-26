from __future__ import annotations

import secrets
import time
import uuid
from urllib.parse import urlencode

import requests
from fastapi import HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.core.settings import (
    auth_cookie_samesite,
    FRONTEND_ORIGIN,
    LI_CLIENT_ID,
    LI_CLIENT_SECRET,
    LI_REDIRECT_URI,
    LI_SCOPE,
    LINKEDIN_ENABLED,
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_COOKIE_MAX_AGE,
    OAUTH_STATE_TTL_SECONDS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    TOKEN_WARN_SECONDS,
)
from app.mongo import mongo_db, now_ts
from app.services.security import (
    clear_auth_cookies,
    cookie_secure_flag,
    cookie_secure_for_auth,
    create_auth_session,
    ensure_tone_profile,
    get_active_token,
    get_user_id_from_session_cookie,
    hash_session_token,
    issue_csrf_token,
    upsert_connected_account,
    upsert_oauth_token,
)
from app.services.tone_memory import refresh_tone_profile_from_posted, refresh_writer_profile


_used_auth_codes: set[str] = set()


def _prune_used_auth_codes(max_size: int = 2000):
    if len(_used_auth_codes) <= max_size:
        return
    _used_auth_codes.clear()


def _token_status(expires_at) -> str:
    if not expires_at:
        return "ok"
    now = now_ts()
    if int(expires_at) <= now:
        return "expired"
    if int(expires_at) - now <= TOKEN_WARN_SECONDS:
        return "expiring_soon"
    return "ok"


def _days_remaining(expires_at) -> int:
    if not expires_at:
        return 0
    return max(0, int((int(expires_at) - now_ts()) / 86400))


def _linkedin_fetch_recent_ugc_posts(access_token: str, person_urn: str, count: int = 20) -> list[dict]:
    url = (
        "https://api.linkedin.com/v2/ugcPosts"
        f"?q=authors&authors=List({person_urn})&sortBy=LAST_MODIFIED&count={count}"
    )
    res = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        timeout=12,
    )
    if res.status_code != 200:
        return []
    data = res.json()
    return data.get("elements", []) or []


def _extract_text_from_ugc(element: dict) -> str | None:
    try:
        sc = element.get("specificContent", {}).get("com.linkedin.ugc.ShareContent", {})
        commentary = sc.get("shareCommentary", {}) or {}
        text = (commentary.get("text") or "").strip()
        return text or None
    except Exception:
        return None


async def sync_linkedin_posts_into_db(user: dict, token: dict, count: int = 20) -> int:
    """
    Best-effort import of recent LinkedIn posts into MongoDB.
    """
    db = mongo_db()
    elements = _linkedin_fetch_recent_ugc_posts(token["access_token"], user["linkedin_person_urn"], count=count)
    if not elements:
        return 0

    imported = 0
    now = now_ts()
    import_session_id = str(uuid.uuid4())
    await db.generation_sessions.insert_one(
        {
            "id": import_session_id,
            "user_id": user["id"],
            "topic": "(imported from LinkedIn)",
            "status": "approved",
            "iteration": 1,
            "last_feedback": None,
            "created_at": now,
            "updated_at": now,
        }
    )

    for el in elements:
        ugc_id = el.get("id")
        if not ugc_id:
            continue
        if await db.posts.find_one({"linkedin_ugc_id": ugc_id}, projection={"_id": 1}):
            continue

        text = _extract_text_from_ugc(el)
        if not text:
            continue

        await db.posts.insert_one(
            {
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "session_id": import_session_id,
                "topic": "(LinkedIn post)",
                "content": text,
                "outcome": "approved",
                "feedback": None,
                "iteration": 1,
                "variant": None,
                "posted_to_linkedin": True,
                "linkedin_ugc_id": ugc_id,
                "style_metadata": None,
                "style_version": 1,
                "created_at": now_ts(),
            }
        )
        imported += 1

    if imported:
        await refresh_tone_profile_from_posted(user["id"])
        await refresh_writer_profile(user["id"])
    return imported


async def _migrate_guest_into_user(db, guest_id: str, target_user_id: str) -> None:
    """Reassign guest-owned rows to an existing LinkedIn user, then remove the guest row."""
    if guest_id == target_user_id:
        return
    now = now_ts()
    await db.generation_sessions.update_many({"user_id": guest_id}, {"$set": {"user_id": target_user_id}})
    await db.drafts.update_many({"user_id": guest_id}, {"$set": {"user_id": target_user_id}})
    await db.posts.update_many({"user_id": guest_id}, {"$set": {"user_id": target_user_id}})
    await db.generation_jobs.update_many({"user_id": guest_id}, {"$set": {"user_id": target_user_id}})
    await db.saved_post_drafts.update_many({"user_id": guest_id}, {"$set": {"user_id": target_user_id}})
    await db.tone_profiles.delete_many({"user_id": guest_id})
    await db.connected_accounts.delete_many({"user_id": guest_id})
    await db.oauth_tokens.delete_many({"user_id": guest_id})
    await db.auth_sessions.update_many(
        {"user_id": guest_id, "revoked_at": None},
        {"$set": {"revoked_at": now}},
    )
    await db.users.delete_one({"id": guest_id})


def linkedin_login():
    if not LINKEDIN_ENABLED:
        raise HTTPException(501, "LinkedIn OAuth is not configured. Set LI_CLIENT_ID and LI_CLIENT_SECRET.")
    state = secrets.token_urlsafe(16)
    auth_qs = urlencode(
        {
            "response_type": "code",
            "client_id": LI_CLIENT_ID or "",
            "redirect_uri": LI_REDIRECT_URI,
            "scope": LI_SCOPE,
            "state": state,
        },
    )
    response = RedirectResponse(
        f"https://www.linkedin.com/oauth/v2/authorization?{auth_qs}",
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=OAUTH_STATE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=cookie_secure_flag(),
    )
    return response


async def linkedin_callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    request: Request = None,
):
    if not LINKEDIN_ENABLED:
        raise HTTPException(501, "LinkedIn OAuth is not configured. Set LI_CLIENT_ID and LI_CLIENT_SECRET.")
    if error:
        raise HTTPException(400, f"LinkedIn OAuth error: {error} — {error_description}")
    if not code:
        raise HTTPException(400, "No authorization code returned from LinkedIn.")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE) if request else None
    if not state or not cookie_state or state != cookie_state:
        raise HTTPException(400, "Invalid or expired OAuth state. Click Connect LinkedIn again.")

    _prune_used_auth_codes()
    if code in _used_auth_codes:
        raise HTTPException(400, "Authorization code already used. Click Connect LinkedIn again.")
    _used_auth_codes.add(code)

    token_res = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LI_REDIRECT_URI,
            "client_id": LI_CLIENT_ID,
            "client_secret": LI_CLIENT_SECRET,
        },
    )
    token_data = token_res.json()
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in")
    if not access_token:
        raise HTTPException(400, f"Token exchange failed: {token_data.get('error_description', str(token_data))}")

    userinfo = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    ).json()
    person_id = userinfo.get("sub")
    if not person_id:
        raise HTTPException(400, f"Could not fetch LinkedIn profile: {userinfo}")

    name = (
        userinfo.get("name")
        or f"{userinfo.get('given_name','')} {userinfo.get('family_name','')}".strip()
        or "LinkedIn User"
    )
    person_urn = f"urn:li:person:{person_id}"
    email = userinfo.get("email")

    db = mongo_db()
    now = now_ts()
    issued_at = now
    expires_at = (now + int(expires_in)) if expires_in else None

    sess_uid = await get_user_id_from_session_cookie(request)
    guest_doc = await db.users.find_one({"id": str(sess_uid)}) if sess_uid else None
    is_guest = bool(guest_doc and guest_doc.get("is_guest") is True)

    existing_li = await db.users.find_one({"linkedin_person_urn": person_urn})

    if existing_li and is_guest and str(sess_uid) != str(existing_li.get("id")):
        await _migrate_guest_into_user(db, str(sess_uid), str(existing_li["id"]))
        user = await db.users.find_one({"id": str(existing_li["id"])})
        if not user:
            raise HTTPException(500, "User merge failed after LinkedIn login.")
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"display_name": name, "email": email or user.get("email"), "updated_at": now}},
        )
        user["display_name"] = name
        if email:
            user["email"] = email
    elif existing_li:
        user = existing_li
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"display_name": name, "email": email or user.get("email"), "updated_at": now}},
        )
        user["display_name"] = name
        if email:
            user["email"] = email
    elif is_guest:
        await db.users.update_one(
            {"id": guest_doc["id"]},
            {
                "$set": {
                    "linkedin_person_urn": person_urn,
                    "linkedin_sub": person_id,
                    "display_name": name,
                    "email": email,
                    "is_guest": False,
                    "updated_at": now,
                }
            },
        )
        user = await db.users.find_one({"id": guest_doc["id"]})
        if not user:
            raise HTTPException(500, "Guest upgrade failed after LinkedIn login.")
    else:
        user = {
            "id": str(uuid.uuid4()),
            "linkedin_person_urn": person_urn,
            "linkedin_sub": person_id,
            "display_name": name,
            "email": email,
            "is_guest": False,
            "created_at": now,
            "updated_at": now,
        }
        await db.users.insert_one(user)

    await upsert_connected_account(
        user_id=uuid.UUID(user["id"]),
        provider="linkedin",
        external_account_id=person_urn,
        display_name=name,
        email=email,
        extra_metadata={},
    )
    await ensure_tone_profile(uuid.UUID(user["id"]))

    await upsert_oauth_token(
        user_id=uuid.UUID(user["id"]),
        provider="linkedin",
        access_token=access_token,
        refresh_token=None,
        scopes=token_data.get("scope"),
        issued_at=issued_at,
        expires_at=expires_at,
        last_used_at=issued_at,
    )

    token = await get_active_token(uuid.UUID(user["id"]), provider="linkedin")
    if token:
        await sync_linkedin_posts_into_db(user, token, count=20)

    raw_session_token = secrets.token_urlsafe(32)
    await create_auth_session(uuid.UUID(user["id"]), raw_session_token)

    response = RedirectResponse(FRONTEND_ORIGIN, status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_session_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite=auth_cookie_samesite(),
        secure=cookie_secure_for_auth(),
        path="/",
    )
    issue_csrf_token(response)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


async def linkedin_me(request: Request):
    if not LINKEDIN_ENABLED:
        return {"connected": False, "name": None, "reason": "linkedin_oauth_not_configured"}
    db = mongo_db()
    user_id = await get_user_id_from_session_cookie(request)
    if not user_id:
        return {"connected": False, "name": None}
    user = await db.users.find_one({"id": str(user_id)})
    if not user:
        return {"connected": False, "name": None}

    token = await get_active_token(user_id, provider="linkedin")
    if not token:
        tp = await ensure_tone_profile(user_id)
        total_posts = await db.posts.count_documents({"user_id": str(user_id), "posted_to_linkedin": True})
        saved_drafts_count = await db.saved_post_drafts.count_documents({"user_id": str(user_id)})
        return {
            "connected": False,
            "name": user.get("display_name"),
            "person_urn": user.get("linkedin_person_urn"),
            "token_status": None,
            "guest": user.get("is_guest") is True,
            "days_remaining": 0,
            "memory": {
                "total_posts": int(total_posts),
                "approved_count": int(tp.get("approved_count") or 0),
                "rejected_count": 0,
                "has_tone_profile": int(total_posts) > 0,
                "saved_drafts_count": int(saved_drafts_count),
            },
        }

    status = _token_status(token.get("expires_at") if token else None)
    if status == "expired":
        if token:
            await db.oauth_tokens.update_one(
                {"user_id": str(user_id), "provider": "linkedin", "revoked_at": None},
                {"$set": {"revoked_at": now_ts()}},
            )
        return {"connected": False, "name": None, "token_status": "expired"}

    tp = await ensure_tone_profile(user_id)
    total_posts = await db.posts.count_documents({"user_id": str(user_id), "posted_to_linkedin": True})
    saved_drafts_count = await db.saved_post_drafts.count_documents({"user_id": str(user_id)})

    return {
        "connected": True,
        "name": user.get("display_name"),
        "person_urn": user.get("linkedin_person_urn"),
        "token_status": status,
        "days_remaining": _days_remaining(token.get("expires_at") if token else None) if token else 0,
        "memory": {
            "total_posts": int(total_posts),
            "approved_count": int(tp.get("approved_count") or 0),
            "rejected_count": 0,
            "has_tone_profile": int(total_posts) > 0,
            "saved_drafts_count": int(saved_drafts_count),
        },
    }


async def linkedin_logout(request: Request, response: Response):
    db = mongo_db()
    user_id = await get_user_id_from_session_cookie(request)
    if user_id:
        await db.oauth_tokens.update_many(
            {"user_id": str(user_id), "provider": "linkedin", "revoked_at": None},
            {"$set": {"revoked_at": now_ts()}},
        )
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if raw:
        try:
            token_hash = hash_session_token(raw)
            await db.auth_sessions.update_many(
                {"session_token_hash": token_hash, "revoked_at": None},
                {"$set": {"revoked_at": now_ts()}},
            )
        except Exception:
            pass

    clear_auth_cookies(response)
    return {"status": "logged out"}


def do_linkedin_post(access_token: str, person_urn: str, text: str) -> dict:
    res = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        },
        json={
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        },
        timeout=12,
    )
    if res.status_code == 201:
        return {"success": True, "id": res.headers.get("x-restli-id", "")}
    if res.status_code == 401:
        return {"success": False, "expired": True, "error": "LinkedIn rejected the token. Please reconnect."}
    return {"success": False, "expired": False, "status": res.status_code, "error": res.text}


def token_status(expires_at) -> str:
    return _token_status(expires_at)

