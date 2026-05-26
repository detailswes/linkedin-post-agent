"""HTTP client for the external agents service + lightweight news fetch."""
from __future__ import annotations

import httpx
import requests

from app.core.settings import AGENT_SERVICE_URL, SERPER_API_KEY


def fetch_research_findings(topic: str) -> str:
    """Pull a few recent news snippets to ground the writer agent. Optional."""
    if not SERPER_API_KEY:
        return ""
    try:
        q = f"{topic} site:news OR announcement OR release last 7 days"
        res = requests.post(
            "https://google.serper.dev/news",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": q, "num": 8, "tbs": "qdr:w"},
            timeout=8,
        )
        items = res.json().get("news", []) or []
        bullets: list[str] = []
        for it in items:
            title = (it.get("title") or "").strip()
            source = (it.get("source") or "").strip()
            date = (it.get("date") or "").strip()
            snippet = (it.get("snippet") or "").strip()
            if not title:
                continue
            line = f"- {title}"
            if source:
                line += f" ({source})"
            if date:
                line += f" — {date}"
            if snippet:
                line += f": {snippet}"
            bullets.append(line)
            if len(bullets) >= 3:
                break
        return "\n".join(bullets)
    except Exception:
        return ""


async def call_agent_service(
    topic: str,
    feedback: str | None,
    memory_context: str,
    tone_instruction: str,
) -> str:
    """Call the external agents service and return the generated LinkedIn post text."""
    if not AGENT_SERVICE_URL:
        raise RuntimeError(
            "Missing AGENT_SERVICE_URL (set it to your agents HTTP base URL)."
        )
    payload = {
        "topic": topic,
        "feedback": feedback,
        "memory_context": memory_context,
        "tone_instruction": tone_instruction,
    }
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.post(f"{AGENT_SERVICE_URL}/generate", json=payload)
        if res.status_code >= 400:
            raise RuntimeError(
                f"Agent service error ({res.status_code}): {res.text[:300]}"
            )
        data = res.json()
        post = str(data.get("post") or "").strip()
        if not post:
            raise RuntimeError("Agent service returned empty post")
        return post
