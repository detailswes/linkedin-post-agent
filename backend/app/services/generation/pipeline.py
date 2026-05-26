"""
Pipeline that drives a single generation job from start to draft persistence.

Yields SSE event strings as it progresses; the queue worker is responsible for
persisting those events to `generation_job_events` so the SSE endpoint can
replay them to the connected client.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import AsyncGenerator

from app.core.sse import make_event
from app.mongo import mongo_db, now_ts

from .agent_client import call_agent_service, fetch_research_findings
from .tones import TONE_BY_ID, TONE_VARIANTS


_PIPELINE_STAGES = [
    ("writer", "✍️ Writing first draft..."),
    ("editor", "✨ Polishing final post..."),
]


async def _run_one_variant(
    topic: str,
    feedback: str | None,
    memory_context: str,
    variant_id: str,
    variant_label: str,
    tone_instruction: str,
) -> AsyncGenerator[tuple[str, str], None]:
    yield (
        "event",
        make_event("variant_start", {"variant": variant_id, "label": variant_label}),
    )
    for agent_id, label in _PIPELINE_STAGES:
        yield (
            "event",
            make_event(
                "stage",
                {
                    "agent": agent_id,
                    "label": label,
                    "variant": variant_id,
                    "variant_label": variant_label,
                },
            ),
        )
        await asyncio.sleep(0)

    try:
        post = await call_agent_service(topic, feedback, memory_context, tone_instruction)
        yield ("event", make_event("result", {"post": post}))
        yield (
            "variant_result",
            make_event(
                "variant_result",
                {"variant": variant_id, "label": variant_label, "post": post},
            ),
        )
    except Exception as exc:
        yield ("event", make_event("error", {"message": str(exc)[:500]}))


async def _latest_pending_drafts_for_iteration(session_id: str, iteration: int) -> list[dict]:
    db = mongo_db()
    rows = (
        await db.drafts.find(
            {"session_id": session_id, "iteration": int(iteration), "status": "pending"},
            sort=[("created_at", -1)],
        ).to_list(length=200)
    )
    by_variant: dict[str | None, dict] = {}
    for p in rows:
        key = p.get("variant")
        if key not in by_variant:
            by_variant[key] = p
    ordered: list[dict] = []
    for v in TONE_VARIANTS:
        p = by_variant.get(v["id"])
        if p:
            ordered.append(p)
    for k, p in by_variant.items():
        if k not in TONE_BY_ID:
            ordered.append(p)
    return ordered


async def persisting_event_stream(
    session_id: str,
    user_id: str | None,
    topic: str,
    iteration: int,
    session_feedback: str | None,
    memory_context: str,
    variant_id: str | None = None,
    feedback_override: str | None = None,
) -> AsyncGenerator[str, None]:
    yield make_event("status", {"message": f"🚀 Starting (attempt {iteration})..."})
    if memory_context:
        yield make_event("status", {"message": "🧠 Loading your writing memory..."})
    active_feedback = feedback_override if variant_id else session_feedback
    if active_feedback:
        yield make_event("status", {"message": f"📝 Applying feedback: {active_feedback}"})

    yield make_event("stage", {"agent": "research", "label": "🔍 Researching topic..."})
    research_findings = fetch_research_findings(topic)
    topic_with_research = (
        f"{topic}\n\nResearch findings (last 7 days):\n{research_findings}"
        if research_findings
        else topic
    )

    variants_to_run: list[dict]
    if variant_id:
        v = TONE_BY_ID.get(variant_id)
        if not v:
            yield make_event("error", {"message": f"Unknown variant: {variant_id}"})
            return
        variants_to_run = [v]
    else:
        variants_to_run = TONE_VARIANTS

    variants_out: list[dict] = []
    for v in variants_to_run:
        async for kind, chunk in _run_one_variant(
            topic_with_research,
            active_feedback,
            memory_context,
            v["id"],
            v["label"],
            v["instruction"],
        ):
            if kind == "variant_result":
                try:
                    payload = json.loads(chunk.split("data: ", 1)[1])
                    variants_out.append(
                        {
                            "variant": payload.get("variant"),
                            "label": payload.get("label"),
                            "post": payload.get("post"),
                        }
                    )
                except Exception:
                    pass
            else:
                yield chunk
            await asyncio.sleep(0)

    db = mongo_db()
    now = now_ts()

    new_drafts = [
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "topic": topic,
            "content": v["post"],
            "status": "pending",
            "feedback": None,
            "iteration": int(iteration),
            "variant": v.get("variant"),
            "created_at": now_ts(),
            "updated_at": now_ts(),
        }
        for v in variants_out
        if v.get("post")
    ]
    if new_drafts:
        await db.drafts.insert_many(new_drafts)

    drafts_now = await _latest_pending_drafts_for_iteration(session_id, iteration)
    if not drafts_now:
        yield make_event(
            "error",
            {
                "message": (
                    "No drafts were produced. Check AGENT_SERVICE_URL and that the agent returns "
                    'JSON with a non-empty "post" field.'
                ),
            },
        )
        raise RuntimeError("generation produced no drafts")

    await db.generation_sessions.update_one(
        {"id": session_id},
        {"$set": {"status": "awaiting_approval", "updated_at": now}},
    )

    label_map = {v["id"]: v["label"] for v in TONE_VARIANTS}
    yield make_event(
        "variants",
        {
            "session_id": session_id,
            "iteration": iteration,
            "drafts": [
                {
                    "draft_id": str(d.get("id")),
                    "variant": d.get("variant"),
                    "label": label_map.get(d.get("variant")),
                    "topic": d.get("topic"),
                    "content": d.get("content"),
                }
                for d in drafts_now
            ],
        },
    )
