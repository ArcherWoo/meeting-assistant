"""
聊天路由 - 处理 LLM 对话请求
支持流式 SSE 响应，兼容 OpenAI 协议
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.llm_service import LLMService

router = APIRouter()
llm_service = LLMService()


class ChatMessage(BaseModel):
    """单条消息"""
    role: str  # system / user / assistant / tool
    content: str


class ChatRequest(BaseModel):
    """聊天请求"""
    messages: list[ChatMessage]
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = True
    # LLM 配置（前端传入，避免后端存储敏感信息）
    api_url: str = "https://api.openai.com/v1"
    api_key: str = ""


class ConfigUpdateRequest(BaseModel):
    """LLM 配置更新请求"""
    api_url: str
    api_key: str
    model: str = ""


@router.post("/chat/completions")
async def chat_completions(request: ChatRequest):
    """
    流式聊天接口 - SSE 格式返回 LLM 响应
    兼容 OpenAI Chat Completions API 协议
    """
    if not request.api_key:
        raise HTTPException(status_code=400, detail="API Key is required")

    if request.stream:
        return StreamingResponse(
            llm_service.stream_chat(
                messages=[m.model_dump() for m in request.messages],
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                api_url=request.api_url,
                api_key=request.api_key,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 非流式响应
        result = await llm_service.chat(
            messages=[m.model_dump() for m in request.messages],
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            api_url=request.api_url,
            api_key=request.api_key,
        )
        return result


@router.post("/chat/test-connection")
async def test_connection(config: ConfigUpdateRequest):
    """测试 LLM API 连接是否正常"""
    try:
        result = await llm_service.test_connection(
            api_url=config.api_url,
            api_key=config.api_key,
            model=config.model,
        )
        model_count = len(result.get("available_models", []))
        message = f"连接成功，发现 {model_count} 个可用模型" if model_count else "连接成功"
        return {"success": True, "message": message, **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"连接失败: {str(e)}")

