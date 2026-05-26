from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.services.linkedin import linkedin_callback, linkedin_login, linkedin_logout, linkedin_me
from app.services.security import bootstrap_anonymous_session, get_user_id_from_session_cookie, issue_csrf_token

router = APIRouter()


@router.post("/auth/bootstrap")
async def _bootstrap(request: Request, response: Response):
    """Create a guest session when none exists; always (re)issues CSRF for credentialed fetches."""
    _uid, created_guest, csrf = await bootstrap_anonymous_session(request, response)
    return {"csrf_token": csrf, "guest": created_guest}


@router.get("/auth/csrf")
async def _csrf(request: Request, response: Response):
    uid = await get_user_id_from_session_cookie(request)
    if not uid:
        raise HTTPException(401, "No session — call POST /auth/bootstrap first.")
    token = issue_csrf_token(response)
    return {"csrf_token": token}


@router.get("/auth/linkedin/login")
def _login():
    return linkedin_login()


@router.get("/auth/linkedin/callback")
async def _callback(
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
    error_description: str = Query(None),
    request: Request = None,
):
    return await linkedin_callback(
        code=code,
        state=state,
        error=error,
        error_description=error_description,
        request=request,
    )


@router.get("/auth/linkedin/me")
async def _me(request: Request):
    return await linkedin_me(request)


@router.post("/auth/linkedin/logout")
async def _logout(request: Request, response: Response):
    return await linkedin_logout(request, response)
