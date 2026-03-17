"""
Agent 执行路由 - PRD §2.4
POST /api/agent/match   - 匹配用户意图到 Skill
POST /api/agent/execute - 执行 Skill（SSE 流式进度）
"""
import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.agent_executor import agent_executor

logger = logging.getLogger(__name__)
router = APIRouter()


class AgentMatchRequest(BaseModel):
    """Agent 意图匹配请求"""
    query: str


class AgentExecuteRequest(BaseModel):
    """Agent 执行请求"""
    skill_id: str
    params: dict = {}
    # LLM 配置（前端传入）
    api_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o"


@router.post("/agent/match")
async def match_intent(request: AgentMatchRequest) -> dict:
    """根据用户输入匹配最佳 Skill"""
    result = await agent_executor.match_skill(request.query)
    if not result:
        return {"matched": False, "message": "未找到匹配的 Skill"}
    return {"matched": True, **result}


@router.post("/agent/execute")
async def execute_skill(request: AgentExecuteRequest):
    """
    执行 Skill - SSE 流式返回执行进度
    每个事件格式: data: {"type": "step_start|step_complete|complete|error", ...}
    """
    # 构建 LLM 调用函数（如果提供了配置）
    llm_fn = None
    if request.api_url and request.api_key:
        from services.llm_service import LLMService
        llm = LLMService()

        async def _llm_call(prompt: str) -> str:
            result = await llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model=request.model,
                temperature=0.3,
                max_tokens=4096,
                api_url=request.api_url,
                api_key=request.api_key,
            )
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")

        llm_fn = _llm_call

    async def event_stream():
        """SSE 事件流生成器"""
        async for event in agent_executor.execute(
            skill_id=request.skill_id,
            params=request.params,
            llm_fn=llm_fn,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

