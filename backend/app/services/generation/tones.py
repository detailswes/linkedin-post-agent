"""Tone variants the writer/editor agents iterate through."""
from __future__ import annotations


TONE_VARIANTS: list[dict] = [
    {
        "id": "technical_deep_dive",
        "label": "Technical / Deep Dive",
        "instruction": (
            "Write in a technical deep-dive tone. Be precise, include concrete mechanisms, "
            "trade-offs, and 2-3 specific technical details. Avoid vague hype."
        ),
    },
    {
        "id": "thought_leadership",
        "label": "Thought Leadership",
        "instruction": (
            "Write in a thought leadership tone. Provide a clear point of view, a strong stance, "
            "and 1-2 contrarian insights backed by the research."
        ),
    },
    {
        "id": "educational",
        "label": "Educational",
        "instruction": (
            "Write in an educational tone. Teach the concept with clear structure, simple examples, "
            "and a short takeaway checklist."
        ),
    },
    {
        "id": "storytelling",
        "label": "Storytelling",
        "instruction": (
            "Write in a storytelling tone. Start with a personal anecdote-style hook, then connect it "
            "to the research and end with a reflective question."
        ),
    },
]


TONE_BY_ID: dict[str, dict] = {v["id"]: v for v in TONE_VARIANTS}
