from __future__ import annotations

import os
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_mongodb_uri() -> str:
    uri = (os.getenv("MONGODB_URI") or "").strip()
    if not uri:
        raise RuntimeError("Missing MONGODB_URI.")
    return uri


def get_db_name() -> str:
    # Allow explicit override; otherwise fall back to a stable default.
    return (os.getenv("MONGODB_DB") or "automatic_post_agent").strip()


def mongo_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(get_mongodb_uri())
    return _client


def mongo_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        _db = mongo_client()[get_db_name()]
    return _db


async def ensure_indexes() -> None:
    """
    Create required indexes for correctness/performance.
    Safe to call on every startup.
    """
    db = mongo_db()

    # users — sparse so many guest rows can omit linkedin_person_urn
    info = await db.users.index_information()
    li_idx = info.get("linkedin_person_urn_1")
    if li_idx and not li_idx.get("sparse"):
        await db.users.drop_index("linkedin_person_urn_1")
    await db.users.create_index("linkedin_person_urn", unique=True, sparse=True)
    await db.users.create_index("linkedin_sub", unique=True, sparse=True)

    # auth_sessions
    await db.auth_sessions.create_index("session_token_hash", unique=True)
    await db.auth_sessions.create_index([("user_id", 1), ("expires_at", 1)])

    # oauth_tokens
    await db.oauth_tokens.create_index([("user_id", 1), ("provider", 1)])
    await db.oauth_tokens.create_index([("provider", 1), ("revoked_at", 1), ("created_at", -1)])

    # connected_accounts
    await db.connected_accounts.create_index([("user_id", 1), ("provider", 1)], unique=True)
    await db.connected_accounts.create_index([("provider", 1), ("external_account_id", 1)], unique=True)

    # generation_sessions
    await db.generation_sessions.create_index([("user_id", 1), ("created_at", -1)])

    # generation_jobs (queue)
    await db.generation_jobs.create_index([("status", 1), ("created_at", 1)])
    await db.generation_jobs.create_index([("session_id", 1), ("status", 1)])
    await db.generation_jobs.create_index([("user_id", 1), ("created_at", -1)])

    # generation_job_events (SSE)
    await db.generation_job_events.create_index([("job_id", 1), ("seq", 1)], unique=True)

    # drafts
    await db.drafts.create_index([("session_id", 1), ("iteration", 1), ("status", 1), ("created_at", -1)])

    # posts
    await db.posts.create_index([("user_id", 1), ("created_at", -1)])
    await db.posts.create_index([("user_id", 1), ("posted_to_linkedin", 1), ("created_at", -1)])

    # tone_profiles
    await db.tone_profiles.create_index("user_id", unique=True)

    # user-saved drafts (not generation pipeline drafts)
    await db.saved_post_drafts.create_index([("user_id", 1), ("created_at", -1)])


def now_ts() -> int:
    # Keep timestamps simple/int for Mongo docs.
    import time

    return int(time.time())


def clean_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not doc:
        return None
    d = dict(doc)
    d.pop("_id", None)
    return d

