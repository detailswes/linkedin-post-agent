"""
Per-user tone & writing memory built from approved LinkedIn posts.

LinkedIn-only by design. The agents service receives a compact "memory context"
string before each generation, which conditions the model on the user's past
voice, structure and signature vocabulary.
"""
from __future__ import annotations

import uuid

from app.core.settings import MAX_APPROVED_SAMPLES, MAX_FEEDBACK_STORED, STYLE_LOOKBACK_N
from app.mongo import mongo_db, now_ts
from app.services.security import ensure_tone_profile
from app.services.suggestions import _tokenize_words as _tokenize_words_shared


def extract_style_metadata(content: str) -> dict:
    text = content.strip()
    lines = [ln.rstrip() for ln in text.splitlines()]
    nonempty = [ln for ln in lines if ln.strip()]
    paragraphs: list[str] = []
    buf: list[str] = []
    for ln in lines:
        if ln.strip():
            buf.append(ln.strip())
        else:
            if buf:
                paragraphs.append(" ".join(buf))
                buf = []
    if buf:
        paragraphs.append(" ".join(buf))

    words = _tokenize_words_shared(text)
    word_count = len(words)
    first_line = nonempty[0] if nonempty else ""
    first_line_words = len(_tokenize_words_shared(first_line))

    hashtags = [w for w in text.split() if w.startswith("#") and len(w) > 1]
    hashtag_count = len(hashtags)

    emoji_count = sum(1 for ch in text if ord(ch) > 0x1F000)
    bullet_lines = [ln for ln in nonempty if ln.lstrip().startswith(("-", "*", "•"))]
    bullet_line_count = len(bullet_lines)
    question_count = text.count("?")

    freq: dict[str, int] = {}
    for t in words:
        if len(t) <= 2:
            continue
        freq[t] = freq.get(t, 0) + 1
    top_terms = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:15]

    return {
        "word_count": word_count,
        "line_count": len(lines),
        "paragraph_count": len(paragraphs) if paragraphs else (1 if text else 0),
        "avg_paragraph_words": int(word_count / max(1, len(paragraphs))) if text else 0,
        "first_line_word_count": first_line_words,
        "hashtag_count": hashtag_count,
        "emoji_count": emoji_count,
        "bullet_line_count": bullet_line_count,
        "question_count": question_count,
        "top_terms": [{"term": t, "count": c} for t, c in top_terms],
    }


def _median(values: list[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) // 2


def build_writer_profile_from_posts(posts: list[dict]) -> dict:
    metas = [p.get("style_metadata") for p in posts if p.get("style_metadata")]
    if not metas:
        return {}

    word_counts = [m.get("word_count") or 0 for m in metas]
    para_counts = [m.get("paragraph_count") or 0 for m in metas]
    hashtag_counts = [m.get("hashtag_count") or 0 for m in metas]
    emoji_counts = [m.get("emoji_count") or 0 for m in metas]
    bullet_counts = [m.get("bullet_line_count") or 0 for m in metas]
    question_counts = [m.get("question_count") or 0 for m in metas]
    first_line_counts = [m.get("first_line_word_count") or 0 for m in metas]

    term_freq: dict[str, int] = {}
    for m in metas:
        for t in m.get("top_terms") or []:
            term = t.get("term")
            if not term:
                continue
            term_freq[term] = term_freq.get(term, 0) + int(t.get("count") or 0)
    signature_terms = [
        t for t, _ in sorted(term_freq.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    ]

    return {
        "structure": {
            "preferred_paragraph_count": _median(para_counts),
            "preferred_word_count": _median(word_counts),
            "preferred_hashtag_count": _median(hashtag_counts),
            "preferred_hook_max_words": _median(first_line_counts) or 12,
            "uses_bullets_often": _median(bullet_counts) > 0,
            "uses_questions_often": _median(question_counts) > 0,
        },
        "tone": {
            "emoji_light": _median(emoji_counts) <= 1,
        },
        "vocabulary": {
            "signature_terms": signature_terms,
        },
    }


async def ensure_post_style_metadata(post_doc: dict) -> dict:
    """Compute style_metadata in-place if missing. Mutates and returns the dict."""
    if post_doc.get("style_metadata"):
        return post_doc
    post_doc["style_metadata"] = extract_style_metadata(post_doc.get("content") or "")
    post_doc["style_version"] = 1
    return post_doc


async def refresh_writer_profile(user_id: str) -> dict:
    """Recompute the writer profile from the user's most recent posted LinkedIn posts."""
    db = mongo_db()
    posted = await db.posts.find(
        {"user_id": user_id, "posted_to_linkedin": True},
        sort=[("created_at", -1)],
        limit=STYLE_LOOKBACK_N,
    ).to_list(length=STYLE_LOOKBACK_N)

    for p in posted:
        if not p.get("style_metadata") and p.get("content"):
            meta = extract_style_metadata(p["content"])
            await db.posts.update_one(
                {"id": p.get("id")},
                {"$set": {"style_metadata": meta, "style_version": 1}},
            )
            p["style_metadata"] = meta

    profile = build_writer_profile_from_posts(posted)
    now = now_ts()
    await db.tone_profiles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "profile": profile,
                "profile_version": 1,
                "source_post_count": len(posted),
                "last_analyzed_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return await db.tone_profiles.find_one({"user_id": user_id}) or {}


async def refresh_tone_profile_from_posted(user_id: str) -> dict:
    """Update approved_count + approved_samples from posted LinkedIn posts."""
    db = mongo_db()
    approved_count = await db.posts.count_documents(
        {"user_id": user_id, "posted_to_linkedin": True}
    )
    samples_docs = await db.posts.find(
        {"user_id": user_id, "posted_to_linkedin": True},
        projection={"content": 1, "_id": 0},
        sort=[("created_at", -1)],
        limit=MAX_APPROVED_SAMPLES,
    ).to_list(length=MAX_APPROVED_SAMPLES)
    samples = [d.get("content") for d in reversed(samples_docs) if d.get("content")]

    now = now_ts()
    await db.tone_profiles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "approved_count": int(approved_count),
                "approved_samples": samples,
                "rejected_count": 0,
                "common_feedback": [],
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return await db.tone_profiles.find_one({"user_id": user_id}) or {}


async def build_memory_context_db(user_id: str | None) -> str:
    """Return the personalised memory context string for the agents service."""
    if not user_id:
        return ""
    db = mongo_db()
    recent_posted = await db.posts.find(
        {"user_id": user_id, "posted_to_linkedin": True},
        sort=[("created_at", -1)],
        limit=5,
    ).to_list(length=5)
    if not recent_posted:
        return ""

    tp = await refresh_writer_profile(user_id)

    lines = ["=== USER MEMORY (use this to personalise the post) ===\n"]
    profile = tp.get("profile") or {}
    structure = profile.get("structure") or {}
    vocab = profile.get("vocabulary") or {}
    tone = profile.get("tone") or {}

    rules: list[str] = []
    if structure.get("preferred_paragraph_count"):
        rules.append(f"- Aim for ~{structure['preferred_paragraph_count']} paragraphs with blank lines.")
    if structure.get("preferred_word_count"):
        rules.append(f"- Aim for ~{structure['preferred_word_count']} words (same ballpark).")
    if structure.get("preferred_hashtag_count") is not None:
        rules.append(f"- Use ~{structure.get('preferred_hashtag_count', 0)} hashtags.")
    if structure.get("preferred_hook_max_words"):
        rules.append(f"- Keep the first line hook under {structure['preferred_hook_max_words']} words.")
    if structure.get("uses_bullets_often"):
        rules.append("- Bullets/checklists are welcome if helpful.")
    if structure.get("uses_questions_often"):
        rules.append("- End with a thoughtful question/CTA.")
    if tone.get("emoji_light") is True:
        rules.append("- Keep emojis minimal (0–1).")

    if rules:
        lines.append("Writer profile (follow these defaults unless feedback overrides):")
        lines.extend(rules)

    sig_terms = vocab.get("signature_terms") or []
    if sig_terms:
        lines.append("\nSignature vocabulary (sprinkle naturally, don't force):")
        lines.append(", ".join(sig_terms[:12]))

    lines.append("\nRecently posted topics (avoid repeating these):")
    for p in recent_posted:
        lines.append(f"  - {p.get('topic')}")

    lines.append("\nRecently posted writing samples (match this tone and style closely):")
    for i, p in enumerate(recent_posted[:MAX_APPROVED_SAMPLES], 1):
        content = p.get("content") or ""
        preview = content[:300] + "..." if len(content) > 300 else content
        lines.append(f"\n[Sample {i}]\n{preview}")

    lines.append("\n=== END MEMORY ===")
    return "\n".join(lines)


async def update_tone_on_approval(user_id: str, post_text: str) -> None:
    db = mongo_db()
    now = now_ts()
    tp = await db.tone_profiles.find_one({"user_id": user_id}) or {}
    approved_count = int(tp.get("approved_count") or 0) + 1
    samples = list(tp.get("approved_samples") or [])
    samples.append(post_text)
    samples = samples[-MAX_APPROVED_SAMPLES:]
    await db.tone_profiles.update_one(
        {"user_id": user_id},
        {"$set": {"approved_count": approved_count, "approved_samples": samples, "updated_at": now}},
        upsert=True,
    )


async def update_tone_on_rejection(user_id: str, feedback: str | None) -> None:
    db = mongo_db()
    now = now_ts()
    tp = await db.tone_profiles.find_one({"user_id": user_id}) or {}
    rejected_count = int(tp.get("rejected_count") or 0) + 1
    common = list(tp.get("common_feedback") or [])
    if feedback:
        common.append(feedback)
        common = common[-MAX_FEEDBACK_STORED:]
    await db.tone_profiles.update_one(
        {"user_id": user_id},
        {"$set": {"rejected_count": rejected_count, "common_feedback": common, "updated_at": now}},
        upsert=True,
    )


def _uuid_from_str(s: str) -> uuid.UUID:
    return uuid.UUID(str(s))
