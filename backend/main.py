"""
Meeting Assistant - FastAPI 后端入口
所有 AI 推理、文件解析、知识库检索均在此完成，前端仅负责 UI 渲染。
"""
import argparse
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import health, chat, ppt, skills, knowledge, knowhow, agent

logger = logging.getLogger(__name__)


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


app = FastAPI(
    title="Meeting Assistant Backend",
    version="0.1.0",
    description="本地 AI 会议助手后端服务",
    lifespan=lifespan,
)

# CORS 配置 - 允许 Electron 渲染进程访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Electron 本地访问，允许所有来源
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



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)

