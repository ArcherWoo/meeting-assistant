"""
Meeting Assistant backend entrypoint.

This module wires up the FastAPI app, lifecycle hooks, and optional static
frontend serving for packaged deployments.
"""

import argparse
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from routers import agent, auth, chat, conversations, health, knowhow, knowledge, ppt, settings, skills

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize shared services on startup and close them on shutdown."""
    from services.storage import storage

    await storage.initialize()
    logger.info("Storage initialized")

    from services.skill_manager import skill_manager

    await skill_manager.initialize()
    logger.info("Skill manager initialized with %s skills", len(skill_manager.list_skills()))

    from services.knowhow_service import knowhow_service

    added = await knowhow_service.ensure_defaults()
    if added:
        logger.info("Seeded %s default know-how rules", added)

    from services.knowledge_service import knowledge_service

    await knowledge_service.initialize()
    logger.info("Knowledge service initialized")

    try:
        yield
    except asyncio.CancelledError:
        # On Windows, Ctrl+C during uvicorn shutdown can cancel the lifespan
        # receive loop. Treat that as a normal shutdown path instead of
        # surfacing a noisy traceback.
        logger.info("Lifespan cancelled during shutdown")
    finally:
        await storage.close()
        logger.info("Resources cleaned up")


def _should_serve_frontend() -> bool:
    return os.getenv("MEETING_ASSISTANT_SERVE_FRONTEND", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_frontend_dist_dir() -> Path:
    configured = os.getenv("MEETING_ASSISTANT_FRONTEND_DIST", "").strip()
    if not configured:
        return DIST_DIR

    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    return candidate.resolve()


def _configure_frontend_routes(app: FastAPI, dist_dir: Path) -> None:
    index_file = dist_dir / "index.html"

    if not index_file.exists():
        logger.warning("Frontend dist directory does not exist, skipping static hosting: %s", dist_dir)
        return

    @app.get("/", include_in_schema=False)
    async def serve_frontend_index() -> FileResponse:
        return FileResponse(index_file)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend_app(full_path: str) -> FileResponse:
        if full_path.startswith(("api/", "docs", "openapi.json", "redoc")):
            raise HTTPException(status_code=404, detail="Not found")

        requested_path = (dist_dir / full_path).resolve()
        try:
            requested_path.relative_to(dist_dir.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

        if requested_path.is_file():
            return FileResponse(requested_path)
        return FileResponse(index_file)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Meeting Assistant Backend",
        version="0.1.0",
        description="Local AI meeting assistant backend",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/api", tags=["Auth"])
    app.include_router(health.router, prefix="/api", tags=["Health"])
    app.include_router(chat.router, prefix="/api", tags=["Chat"])
    app.include_router(ppt.router, prefix="/api", tags=["PPT"])
    app.include_router(skills.router, prefix="/api", tags=["Skills"])
    app.include_router(knowledge.router, prefix="/api", tags=["Knowledge"])
    app.include_router(knowhow.router, prefix="/api", tags=["Know-how"])
    app.include_router(agent.router, prefix="/api", tags=["Agent"])
    app.include_router(settings.router, prefix="/api", tags=["Settings"])
    app.include_router(conversations.router, prefix="/api", tags=["Conversations"])

    if _should_serve_frontend():
        _configure_frontend_routes(app, _resolve_frontend_dist_dir())

    return app


app = create_app()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("MEETING_ASSISTANT_PORT", "5173")))
    parser.add_argument("--host", type=str, default=os.getenv("MEETING_ASSISTANT_HOST", "0.0.0.0"))
    parser.add_argument("--reload", action="store_true", help="Enable auto reload for development")
    args = parser.parse_args()

    target = "main:app" if args.reload else app
    try:
        uvicorn.run(target, host=args.host, port=args.port, reload=args.reload)
    except KeyboardInterrupt:
        logger.info("Backend stopped by user")
