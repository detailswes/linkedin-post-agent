from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.settings import ALLOWED_ORIGINS
from app.mongo import ensure_indexes
from app.routes import auth, generation, health, linkedin, memory, suggestions


def create_app() -> FastAPI:
    app = FastAPI()

    @app.on_event("startup")
    async def _startup() -> None:
        await ensure_indexes()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(memory.router)
    app.include_router(linkedin.router)
    app.include_router(suggestions.router)
    app.include_router(generation.router)
    return app


app = create_app()

