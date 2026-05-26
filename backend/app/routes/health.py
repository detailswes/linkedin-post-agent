from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.settings import ENV
from app.mongo import mongo_client


router = APIRouter()


@router.get("/health")
async def health():
    try:
        await mongo_client().admin.command("ping")
        return {"ok": True, "env": ENV}
    except Exception as exc:
        raise HTTPException(503, f"unhealthy: {exc}")

