from __future__ import annotations

import random

import requests

from app.core.settings import SERPER_API_KEY


FALLBACK_TOPICS = [
    "The rise of AI agents in 2026",
    "How to build a personal brand on LinkedIn",
    "Remote work vs return-to-office: my take",
    "What I learned shipping my first SaaS product",
    "Why most startups fail in year two",
    "The skill every developer needs in 2026",
    "Lessons from 5 years of engineering leadership",
    "How generative AI is changing content creation",
]

_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "then",
    "so",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "as",
    "at",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "it",
    "this",
    "that",
    "these",
    "those",
    "i",
    "you",
    "we",
    "they",
    "my",
    "your",
    "our",
    "their",
    "me",
    "us",
    "them",
    "from",
    "into",
    "over",
    "under",
    "about",
    "than",
    "too",
    "very",
}


def _tokenize_words(text: str) -> list[str]:
    w = []
    cur = []
    for ch in text.lower():
        if ch.isalnum() or ch in ["'"]:
            cur.append(ch)
        else:
            if cur:
                w.append("".join(cur))
                cur = []
    if cur:
        w.append("".join(cur))
    return [t for t in w if t]


def _extract_keywords_for_suggestions(text: str, k: int = 8) -> list[str]:
    words = _tokenize_words(text)
    freq: dict[str, int] = {}
    for w in words:
        if w in _STOPWORDS:
            continue
        if len(w) <= 3:
            continue
        freq[w] = freq.get(w, 0) + 1
    top = [t for t, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]
    return top


def _extract_keyphrases_for_suggestions(text: str, k: int = 8) -> list[str]:
    words = [w for w in _tokenize_words(text) if w and w not in _STOPWORDS and len(w) > 2]
    if not words:
        return []
    phrases: dict[str, int] = {}
    for n in (2, 3):
        for i in range(0, len(words) - n + 1):
            p = " ".join(words[i : i + n]).strip()
            if len(p) < 8:
                continue
            phrases[p] = phrases.get(p, 0) + 1
    return [p for p, _ in sorted(phrases.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def _suggest_topics_local(post_text: str, seed_topic: str = "") -> list[str]:
    combined = f"{seed_topic}\n{post_text}".strip()
    phrases = _extract_keyphrases_for_suggestions(combined, k=6)
    kws = phrases or _extract_keywords_for_suggestions(combined, k=6)
    if not kws:
        base_seed = seed_topic.strip() or "this topic"
        return [
            "What changed in AI this week (and why it matters)",
            "How to turn learning into leverage on LinkedIn",
            "The most underrated career skill in 2026",
            "How I decide what to build next",
            f"{base_seed}: practical next steps",
        ]
    base = kws[:4]
    seed = seed_topic.strip()
    seed_prefix = f"{seed}: " if seed else ""
    templates = [
        "What most people miss about {}",
        "{} in practice: lessons learned",
        "A practical framework for {}",
        "How {} is changing day-to-day work",
        "The biggest mistakes with {}",
        "A 5-step checklist for {}",
        "How to measure progress in {}",
        "A contrarian take on {}",
    ]
    rnd = random.Random(hash(combined) & 0xFFFFFFFF)
    rnd.shuffle(templates)
    out: list[str] = []
    for i, tmpl in enumerate(templates):
        token = base[i % len(base)] if base else "this"
        out.append(f"{seed_prefix}{tmpl.format(token)}".strip())
        if len(out) >= 8:
            break
    return out


def suggest_topics_serper(
    post_text: str,
    seed_topic: str = "",
    n: int = 6,
    exclude: set[str] | None = None,
) -> list[str]:
    exclude = exclude or set()
    if not SERPER_API_KEY:
        return _suggest_topics_local(post_text, seed_topic=seed_topic)

    combined = f"{seed_topic}\n{post_text}".strip()
    phrases = _extract_keyphrases_for_suggestions(combined, k=6)
    kws = _extract_keywords_for_suggestions(combined, k=8)
    q = " ".join((phrases[:2] + kws)[:6]) if (phrases or kws) else "LinkedIn trending topics"

    seed = seed_topic.strip()
    query_templates = [
        f"LinkedIn post ideas related to {seed} last 7 days {q}"
        if seed
        else f"trending topics on LinkedIn last 7 days {q}",
        f"follow-up post topics after {seed} {q}" if seed else f"LinkedIn post prompts this week {q}",
        f"what should I post next on LinkedIn about {seed} {q}"
        if seed
        else f"what's trending on LinkedIn this week {q}",
    ]
    try:
        titles: list[str] = []
        rnd = random.Random(hash(combined) & 0xFFFFFFFF)
        rnd.shuffle(query_templates)

        for query in query_templates[:2]:
            res = requests.post(
                "https://google.serper.dev/news",
                headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                json={"q": query, "num": 10, "tbs": "qdr:w"},
                timeout=8,
            )
            items = res.json().get("news", []) or []
            for it in items:
                t = (it.get("title") or "").strip()
                if not t:
                    continue
                if len(t) > 95:
                    continue
                if t in titles or t in exclude:
                    continue
                titles.append(t)
                if len(titles) >= max(n, 10):
                    break
            if len(titles) >= max(n, 10):
                break

        merged: list[str] = []
        for t in titles + _suggest_topics_local(post_text, seed_topic=seed_topic):
            tt = (t or "").strip()
            if not tt:
                continue
            if tt in merged or tt in exclude:
                continue
            merged.append(tt)
            if len(merged) >= n:
                break
        return merged or _suggest_topics_local(post_text, seed_topic=seed_topic)[:n]
    except Exception:
        return _suggest_topics_local(post_text, seed_topic=seed_topic)

