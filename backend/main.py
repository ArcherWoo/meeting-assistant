"""
Meeting Assistant - FastAPI 后端入口
所有 AI 推理、文件解析、知识库检索均在此完成，前端仅负责 UI 渲染。
"""
import argparse
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from routers import health, chat, ppt, skills, knowledge, knowhow, agent, settings

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理：启动初始化 + 关闭清理"""
    # === Startup ===
    from services.storage import storage
    await storage.initialize()
    logger.info("SQLite 存储已初始化")

    from services.skill_manager import skill_manager
    await skill_manager.initialize()
    logger.info(f"Skill Manager 已初始化，加载 {len(skill_manager.list_skills())} 个 Skill")

    from services.knowhow_service import knowhow_service
    added = await knowhow_service.ensure_defaults()
    if added:
        logger.info(f"Know-how 已初始化 {added} 条默认规则")

    from services.knowledge_service import knowledge_service
    await knowledge_service.initialize()
    logger.info("知识库服务已初始化")

    yield

    # === Shutdown ===
    await storage.close()
    logger.info("资源已清理")


def _should_serve_frontend() -> bool:
    return os.getenv("MEETING_ASSISTANT_SERVE_FRONTEND", "").strip().lower() in {
        "1", "true", "yes", "on",
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
        logger.warning("前端 dist 目录不存在，跳过静态站点托管: %s", dist_dir)
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
        description="本地 AI 会议助手后端服务",
        lifespan=lifespan,
    )

    # CORS 配置 - 允许本地开发和多端部署
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由 - Phase 1
    app.include_router(health.router, prefix="/api", tags=["Health"])
    app.include_router(chat.router, prefix="/api", tags=["Chat"])
    app.include_router(ppt.router, prefix="/api", tags=["PPT"])

    # 注册路由 - Phase 2
    app.include_router(skills.router, prefix="/api", tags=["Skills"])
    app.include_router(knowledge.router, prefix="/api", tags=["Knowledge"])
    app.include_router(knowhow.router, prefix="/api", tags=["Know-how"])
    app.include_router(agent.router, prefix="/api", tags=["Agent"])
    app.include_router(settings.router, prefix="/api", tags=["Settings"])

    if _should_serve_frontend():
        _configure_frontend_routes(app, _resolve_frontend_dist_dir())

    return app


app = create_app()



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("MEETING_ASSISTANT_PORT", "5173")))
    parser.add_argument("--host", type=str, default=os.getenv("MEETING_ASSISTANT_HOST", "127.0.0.1"))
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)
