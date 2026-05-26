"""Pydantic request models shared across generation route handlers."""
from __future__ import annotations

from pydantic import BaseModel


class StartRequest(BaseModel):
    topic: str


class GenerateRequest(BaseModel):
    session_id: str
    variant: str | None = None
    feedback: str | None = None


class ApprovalRequest(BaseModel):
    session_id: str
    approved: bool
    feedback: str = ""
    draft_id: str | None = None
    variant: str | None = None
