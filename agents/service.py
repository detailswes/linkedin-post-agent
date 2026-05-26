from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from crew import ContentCrew

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="LinkedIn Post Agents",
    description="CrewAI-powered service for drafting and editing LinkedIn posts.",
    version="1.0.0",
)


class GenerateRequest(BaseModel):
    topic: str
    feedback: str | None = None
    memory_context: str = ""
    tone_instruction: str = ""


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/generate")
def generate(req: GenerateRequest):
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(400, "topic is required")

    prompt = topic[:4000]

    if req.memory_context:
        prompt = f"{req.memory_context.strip()}\n\nTopic to write about: {prompt}"

    if req.tone_instruction:
        prompt = f"{prompt}\n\nTone requirements: {req.tone_instruction.strip()[:1200]}"

    if req.feedback:
        prompt += f"\n\nRevision feedback: {req.feedback.strip()[:1000]}"

    try:
        crew_instance = ContentCrew().crew()
        result = crew_instance.kickoff(inputs={"topic": prompt})
        return {"post": str(result)}
    except Exception as exc:
        msg = str(exc) or "Generation could not be completed"
        logger.warning("POST /generate failed: %s", msg, exc_info=True)
        if os.getenv("AGENTS_DEBUG", "").strip().lower() in ("1", "true", "yes"):
            raise
        raise HTTPException(500, msg[:500])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "9000")))
