"""
健康检查路由
用于 Electron 主进程轮询后端是否就绪
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    """后端健康检查接口"""
    return {"status": "ok", "service": "meeting-assistant-backend"}

