from __future__ import annotations

import random

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.settings import SERPER_API_KEY
from app.services.suggestions import FALLBACK_TOPICS, suggest_topics_serper


router = APIRouter()


@router.get("/api/trending-topics")
async def trending_topics():
    if not SERPER_API_KEY:
        return {"topics": FALLBACK_TOPICS}
    try:
        q_templates = [
            "trending topics on LinkedIn last 7 days",
            "what's trending on LinkedIn this week",
            "LinkedIn trending discussions this week",
            "LinkedIn posts topics trending this week",
            "LinkedIn creator trends last 7 days",
        ]
        q = random.choice(q_templates)
        res = requests.post(
            "https://google.serper.dev/news",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": q, "num": 12, "tbs": "qdr:w"},
            timeout=8,
        )
        topics = [
            item["title"].strip()
            for item in res.json().get("news", [])[:10]
            if item.get("title") and len(item["title"]) < 90
        ]
        return {"topics": topics or FALLBACK_TOPICS}
    except Exception:
        return {"topics": FALLBACK_TOPICS}


class SuggestionsRequest(BaseModel):
    post_text: str = ""
    topic: str = ""
    exclude: list[str] = []


@router.post("/api/suggestions")
def suggestions(req: SuggestionsRequest, request: Request):
    text = (req.post_text or "").strip()
    if not text:
        raise HTTPException(400, "post_text is required")
    exclude = {t.strip() for t in (req.exclude or []) if t and t.strip()}
    topics = suggest_topics_serper(text, seed_topic=(req.topic or "").strip(), n=6, exclude=exclude)
    return {"topics": topics}

