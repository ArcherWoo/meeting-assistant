"""Agent routes backed by Agent Runtime V2."""

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from routers.auth import get_current_user
from services.access_control import can_access_role, filter_accessible_skills, get_accessible_skill
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
from services.observability import log_structured, new_request_id, publish_runtime_metrics, runtime_metrics
from services.runtime_paths import CLASSIFICATION_OUTPUTS_DIR
from services.skill_manager import skill_manager
from services.skill_matcher import skill_matcher
from services.storage import storage

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/agent/match")
async def match_intent(request: AgentMatchRequest, user: dict = Depends(get_current_user)) -> AgentMatchResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    normalized_role_id = normalize_agent_role_id(request.role_id or "executor")
    role = await storage.get_role(normalized_role_id)
    if not role:
        raise HTTPException(status_code=404, detail=f"角色 {normalized_role_id} 不存在")
    if isinstance(user, dict) and not await can_access_role(role, user):
        raise HTTPException(status_code=403, detail="无权使用该角色")

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

    skills = await filter_accessible_skills(skill_manager.list_skills(), user)
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
    request_id = new_request_id("agent")
    user_id = str((user or {}).get("id") or "")

    role = await storage.get_role(normalize_agent_role_id(request.role_id))
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if isinstance(user, dict) and not await can_access_role(role, user):
        raise HTTPException(status_code=403, detail="无权使用该角色")

    if request.skill_id and isinstance(user, dict):
        skill = await get_accessible_skill(request.skill_id, user)
        if not skill:
            raise HTTPException(status_code=403, detail="无权使用该 Skill")

    runtime_metrics.record_agent_started()
    await publish_runtime_metrics()
    log_structured(
        logger,
        "info",
        "agent.request.started",
        request_id=request_id,
        user_id=user_id,
        run_id=request.run_id,
        conversation_id=request.conversation_id,
        role_id=request.role_id,
        skill_id=request.skill_id,
    )

    async def event_stream():
        status = "completed"
        terminal_event_emitted = False
        try:
            async for event in execute_agent_stream(request, user=user):
                if isinstance(event, dict):
                    event.setdefault("request_id", request_id)
                    event_type = str(event.get("type") or "")
                    if event_type == "error":
                        status = "failed"
                        terminal_event_emitted = True
                    elif event_type == "cancelled":
                        status = "cancelled"
                        terminal_event_emitted = True
                    elif event_type == "complete":
                        status = "completed"
                        terminal_event_emitted = True
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except (RoleNotAllowedForSurfaceError, AgentContinuationError) as exc:
            status = "failed"
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc), 'request_id': request_id}, ensure_ascii=False)}\n\n"
        except AgentConfigurationError as exc:
            status = "failed"
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc), 'request_id': request_id}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # pragma: no cover
            status = "failed"
            log_structured(
                logger,
                "exception",
                "agent.request.failed",
                request_id=request_id,
                user_id=user_id,
                run_id=request.run_id,
                conversation_id=request.conversation_id,
                role_id=request.role_id,
                skill_id=request.skill_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc), 'request_id': request_id}, ensure_ascii=False)}\n\n"
        finally:
            runtime_metrics.record_agent_finished(status=status)
            await publish_runtime_metrics(force=True)
            log_structured(
                logger,
                "info" if status == "completed" else "warning",
                "agent.request.completed" if status == "completed" else "agent.request.failed",
                request_id=request_id,
                user_id=user_id,
                run_id=request.run_id,
                conversation_id=request.conversation_id,
                role_id=request.role_id,
                skill_id=request.skill_id,
                status=status,
                terminal_event_emitted=terminal_event_emitted,
            )
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        },
    )


@router.get("/agent/runs/{run_id}")
async def get_agent_run(run_id: str, user: dict = Depends(get_current_user)) -> dict:
    run = await load_agent_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run 不存在")
    return {"run": run}


@router.get("/agent/artifacts/classification/{file_name}")
async def download_classification_artifact(file_name: str, user: dict = Depends(get_current_user)):
    normalized_user_id = str((user or {}).get("id") or "").strip()
    safe_segment = re.sub(r"[^a-zA-Z0-9._-]+", "_", normalized_user_id) if normalized_user_id else "anonymous"
    base_dir = (CLASSIFICATION_OUTPUTS_DIR / safe_segment).resolve()
    candidate = (base_dir / Path(file_name).name).resolve()
    if not candidate.is_relative_to(base_dir):
        raise HTTPException(status_code=400, detail="无效的文件名")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="结果文件不存在")
    return FileResponse(
        candidate,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=candidate.name,
    )


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
