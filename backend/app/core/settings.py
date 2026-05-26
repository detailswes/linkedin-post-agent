from __future__ import annotations

import os
import warnings
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


def split_origins(raw: str) -> list[str]:
    return [o.strip() for o in (raw or "").split(",") if o and o.strip()]


ENV = os.getenv("ENV", os.getenv("APP_ENV", "development")).strip().lower()
IS_PROD = ENV in ("prod", "production")

# Local/dev only: load backend/.env. In production (Render, etc.) rely on the process environment only —
# otherwise an empty SESSION_SECRET= line in a stray .env inside the image would win and hide dashboard secrets.
if not IS_PROD:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").strip()
ALLOWED_ORIGINS = split_origins(os.getenv("ALLOWED_ORIGINS", FRONTEND_ORIGIN))
API_PUBLIC_BASE_URL = os.getenv("API_PUBLIC_BASE_URL", "http://localhost:8000").strip()


def _origin_host(origin: str) -> str:
    try:
        return (urlparse(origin).hostname or "").lower()
    except Exception:
        return ""


def _is_loopback_api_host(hostname: str) -> bool:
    return hostname in ("localhost", "127.0.0.1")


def auth_cookie_samesite() -> str:
    """
    lax: same hostname as API (typical local http://localhost with different ports).
    none: split hosting (e.g. Vercel frontend + Render API) so browsers attach cookies on credentialed fetches.
    """
    raw = (os.getenv("AUTH_COOKIE_SAMESITE") or "").strip().lower()
    if raw in ("none", "lax", "strict"):
        return raw
    fe = _origin_host(FRONTEND_ORIGIN)
    api = _origin_host(API_PUBLIC_BASE_URL)
    if fe and api and fe != api:
        return "none"
    return "lax"

# ── Throttling ────────────────────────────────────────────────────────────────
GEN_RATE_PER_MIN = float(os.getenv("GEN_RATE_PER_MIN", "6"))  # refill tokens per minute
GEN_BURST = float(os.getenv("GEN_BURST", "3"))  # max bucket size

# ── Memory limits ─────────────────────────────────────────────────────────────
MAX_POSTS_STORED = 20
MAX_SAVED_DRAFTS = 50
MAX_APPROVED_SAMPLES = 3
MAX_FEEDBACK_STORED = 10
STYLE_LOOKBACK_N = 30

# ── LinkedIn OAuth config ─────────────────────────────────────────────────────
LI_CLIENT_ID = os.getenv("LI_CLIENT_ID")
LI_CLIENT_SECRET = os.getenv("LI_CLIENT_SECRET")
# Avoid https://host//auth/... if API_PUBLIC_BASE_URL has a trailing slash. Must match LinkedIn app exactly.
_li_explicit = (os.getenv("LI_REDIRECT_URI") or "").strip()
_api_host = _origin_host(API_PUBLIC_BASE_URL)
_li_host = _origin_host(_li_explicit) if _li_explicit else ""
# Dev: duplicate LI_REDIRECT_URI lines in .env often make the *last* value win (e.g. production Render URL).
# Login then sets the OAuth state cookie on localhost, but LinkedIn sends the browser to another host —
# the cookie is missing and the callback fails with "Invalid or expired OAuth state".
if (
    not IS_PROD
    and _li_explicit
    and _api_host
    and _li_host
    and _api_host != _li_host
    and _is_loopback_api_host(_api_host)
):
    warnings.warn(
        "LI_REDIRECT_URI points at a different host than API_PUBLIC_BASE_URL while the API is on "
        f"loopback ({_api_host!r} vs {_li_host!r}). Using the callback derived from API_PUBLIC_BASE_URL "
        "so the OAuth state cookie matches. Remove the extra LI_REDIRECT_URI line or set both to the "
        "same public base (e.g. ngrok) if you need a non-local redirect.",
        UserWarning,
        stacklevel=1,
    )
    _li_explicit = ""
LI_REDIRECT_URI = (
    _li_explicit
    if _li_explicit
    else f"{API_PUBLIC_BASE_URL.rstrip('/')}/auth/linkedin/callback"
).rstrip("/")
LI_SCOPE = "openid profile email w_member_social"
LINKEDIN_ENABLED = bool((LI_CLIENT_ID or "").strip() and (LI_CLIENT_SECRET or "").strip())

SESSION_COOKIE_NAME = "session"
CSRF_COOKIE_NAME = "csrf_token"
COOKIE_MAX_AGE = 60 * 60 * 24 * 60
OAUTH_STATE_COOKIE = "li_oauth_state"
OAUTH_STATE_COOKIE_MAX_AGE = 15 * 60

SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
# Render / other hosts sometimes use SECRET_KEY; accept common aliases (first non-empty wins).
SESSION_SECRET = next(
    (
        (os.getenv(k) or "").strip()
        for k in ("SESSION_SECRET", "SECRET_KEY", "APP_SESSION_SECRET")
        if (os.getenv(k) or "").strip()
    ),
    "",
)

TOKEN_WARN_SECONDS = 55 * 86400
TOKEN_EXPIRY_SECONDS = 59 * 86400
OAUTH_STATE_TTL_SECONDS = 15 * 60  # 15 minutes

if IS_PROD and not SESSION_SECRET:
    raise RuntimeError(
        "Missing session signing secret in production. On Render: open the **postforge-api** service -> "
        "Environment -> add **SESSION_SECRET** (preferred) or **SECRET_KEY** with the same long random value -> "
        "Save -> Manual Deploy. Confirm the variable is on **postforge-api**, not only the web frontend. "
        "Environment Groups must be linked to this service. Do not wrap values in quotes."
    )

# ── External services ─────────────────────────────────────────────────────────
SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
AGENT_SERVICE_URL = os.getenv("AGENT_SERVICE_URL", "").strip().rstrip("/")

