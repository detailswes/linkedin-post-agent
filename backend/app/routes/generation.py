from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.generation import (
    ApprovalRequest,
    GenerateRequest,
    StartRequest,
    approve_post,
    delete_session,
    enqueue_generation,
    get_session,
    start_session,
    stream_job_events,
)


router = APIRouter()


@router.post("/api/start")
async def _start(req: StartRequest, request: Request):
    return await start_session(req, request)


@router.post("/api/generate")
async def _generate(req: GenerateRequest, request: Request):
    return await enqueue_generation(req, request)


@router.get("/api/stream/jobs/{job_id}")
async def _stream(job_id: str, request: Request):
    return await stream_job_events(job_id, request)


@router.post("/api/approve")
async def _approve(req: ApprovalRequest, request: Request):
    return await approve_post(req, request)


@router.get("/api/session/{session_id}")
async def _get_session(session_id: str, request: Request):
    return await get_session(session_id, request)


@router.delete("/api/session/{session_id}")
async def _delete_session(session_id: str, request: Request):
    return await delete_session(session_id, request)

