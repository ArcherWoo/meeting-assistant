"""Agent routes backed by Agent Runtime V2."""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from services.agent_runtime.errors import (
    AgentConfigurationError,
    AgentContinuationError,
    RoleNotAllowedForSurfaceError,
)
from services.agent_runtime.history import load_agent_run
from services.agent_runtime.models import (
    AgentExecuteRequest,
    AgentMatchRequest,
    AgentMatchResponse,
    AgentSkillExecutionProfile,
)
from services.agent_runtime.role_policy import (
    load_agent_role_policy,
    normalize_agent_role_id,
)
from services.agent_runtime.run_registry import run_registry
from services.agent_runtime.runner import execute_agent_stream
from services.skill_manager import skill_manager
from services.skill_matcher import skill_matcher
from services.storage import storage
from routers.auth import get_current_user

router = APIRouter()


@router.post("/agent/match")
async def match_intent(request: AgentMatchRequest, user: dict = Depends(get_current_user)) -> AgentMatchResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    normalized_role_id = normalize_agent_role_id(request.role_id or "executor")
    try:
        _, policy = await load_agent_role_policy(storage, normalized_role_id)
    except RoleNotAllowedForSurfaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if "pre_match_skill" not in policy.agent_preflight:
        return AgentMatchResponse(
            matched=False,
            role_id=normalized_role_id,
            message="当前角色未启用 Skill 预匹配",
        )

    if not skill_manager._loaded:
        await skill_manager.initialize()

    skills = skill_manager.list_skills()
    if not skills:
        return AgentMatchResponse(
            matched=False,
            role_id=normalized_role_id,
            message="未找到可用的 Skill",
        )

    results = skill_matcher.match(query, skills)
    if not results:
        return AgentMatchResponse(
            matched=False,
            role_id=normalized_role_id,
            message="未找到匹配的 Skill",
        )

    best = results[0]
    return AgentMatchResponse(
        matched=True,
        skill_id=best.skill.id,
        skill_name=best.skill.name,
        score=best.score,
        confidence=best.confidence,
        matched_keywords=best.matched_keywords,
        parameters=list(best.skill.parameters),
        execution_profile=AgentSkillExecutionProfile(**best.skill.execution_profile.__dict__),
        role_id=normalized_role_id,
    )


@router.post("/agent/execute")
async def execute_skill(request: AgentExecuteRequest, user: dict = Depends(get_current_user)):
    async def event_stream():
        try:
            async for event in execute_agent_stream(request):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except (RoleNotAllowedForSurfaceError, AgentContinuationError) as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        except AgentConfigurationError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # pragma: no cover
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
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


@router.get("/agent/runs/{run_id}")
async def get_agent_run(run_id: str, user: dict = Depends(get_current_user)) -> dict:
    run = await load_agent_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run 不存在")
    return {"run": run}


@router.post("/agent/runs/{run_id}/cancel")
async def cancel_agent_run(run_id: str, user: dict = Depends(get_current_user)) -> dict:
    run = await load_agent_run(run_id)
    if run and run.get("status") in {"completed", "failed", "cancelled"}:
        return {
            "run": run,
            "cancel_requested": False,
            "message": f"当前 run 已处于 {run.get('status')} 状态",
        }

    registered_and_cancelled = await run_registry.request_cancel(run_id)
    updated_run = await load_agent_run(run_id) or run
    message = "取消请求已提交，等待后端停止"
    if registered_and_cancelled or (updated_run and updated_run.get("status") == "cancelled"):
        message = "执行已取消"

    return {
        "run": updated_run,
        "cancel_requested": True,
        "message": message,
    }
