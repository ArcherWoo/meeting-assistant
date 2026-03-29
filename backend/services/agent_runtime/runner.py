from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from typing import Any

from services.agent_runtime.agent_factory import create_runtime_agent
from services.agent_runtime.deps import build_agent_deps
from services.agent_runtime.errors import AgentContinuationError
from services.agent_runtime.event_adapter import AgentEventAdapter
from services.agent_runtime.history import (
    load_agent_run,
    load_latest_message_history,
    load_run_message_history,
    serialize_message_history,
)
from services.agent_runtime.models import AgentCitation, AgentExecuteRequest
from services.agent_runtime.result_mapper import map_final_result
from services.agent_runtime.run_registry import run_registry
from services.agent_runtime.role_policy import normalize_agent_role_id
from services.retrieval_planner import RetrievalPlannerSettings


def _build_runtime_prompt(request: AgentExecuteRequest, context_suffix: str = "") -> str:
    params = json.dumps(request.params, ensure_ascii=False)
    lines = [
        f"任务目标：{request.query}",
        f"当前显式参数：{params}",
    ]
    if request.skill_id:
        lines.append(f"建议优先读取 Skill 定义：{request.skill_id}")
    if request.continue_from_run_id:
        mode_label = "失败后重试" if request.continue_mode == "retry" else "继续执行"
        lines.append(f"本次为基于上一轮 run 的{mode_label}：{request.continue_from_run_id}")
        if request.continue_notes:
            lines.append(f"补充说明：{request.continue_notes}")
    if context_suffix.strip():
        lines.extend(
            [
                "",
                "以下是预先检索到的可参考上下文：",
                context_suffix.strip(),
            ]
        )
    lines.append("请按需调用工具，并输出结构化的最终结果。")
    return "\n".join(lines)


def _append_skill_context(prompt: str, deps) -> str:
    if not deps.skill:
        return prompt

    skill = deps.skill
    profile = deps.skill_execution_profile
    lines = [
        prompt,
        "",
        "以下是当前 Skill 的执行配置：",
        f"Skill 名称：{skill.name}",
    ]
    if skill.description:
        lines.append(f"Skill 描述：{skill.description}")
    if profile:
        if profile.preferred_role_id:
            lines.append(f"推荐角色：{profile.preferred_role_id}")
        if profile.allowed_tools:
            lines.append(f"Skill 允许工具：{', '.join(profile.allowed_tools)}")
        if profile.output_kind:
            lines.append(f"预期输出类型：{profile.output_kind}")
        if profile.output_sections:
            lines.append(f"建议输出章节：{'、'.join(profile.output_sections)}")
        if profile.notes:
            lines.append(f"执行提醒：{'；'.join(profile.notes)}")
    if skill.output_template:
        lines.extend(["", "输出模板参考：", skill.output_template.strip()])
    return "\n".join(lines)


def _enabled_retrieval_surfaces(policy) -> set[str]:
    surfaces: set[str] = set()
    if "auto_knowledge" in getattr(policy, "agent_preflight", []):
        surfaces.add("knowledge")
    if "auto_knowhow" in getattr(policy, "agent_preflight", []):
        surfaces.add("knowhow")
    if "pre_match_skill" in getattr(policy, "agent_preflight", []):
        surfaces.add("skill")
    return surfaces


def _capture_run_messages_context():
    try:
        from pydantic_ai import capture_run_messages
    except (ImportError, AttributeError):
        return nullcontext([])
    return capture_run_messages()


def _extract_message_history(result: Any, captured_messages: Any) -> str:
    if result is not None and hasattr(result, "all_messages_json"):
        try:
            return serialize_message_history(result.all_messages_json())
        except Exception:
            pass
    if result is not None and hasattr(result, "all_messages"):
        try:
            return serialize_message_history(result.all_messages())
        except Exception:
            pass
    return serialize_message_history(captured_messages)


async def _resolve_continuation_request(
    request: AgentExecuteRequest,
) -> tuple[AgentExecuteRequest, dict | None]:
    if not request.continue_from_run_id:
        return request, None

    source_run = await load_agent_run(request.continue_from_run_id)
    if not source_run:
        raise AgentContinuationError(f"待继续的 run 不存在：{request.continue_from_run_id}")

    if source_run.get("status") in {"pending", "running"}:
        raise AgentContinuationError("当前 run 仍在执行中，暂时不能继续")

    source_role_id = normalize_agent_role_id(str(source_run.get("roleId") or source_run.get("role_id") or ""))
    request_role_id = normalize_agent_role_id(request.role_id)
    if request_role_id != source_role_id:
        raise AgentContinuationError("继续执行时必须沿用同一个 Agent 角色")

    source_skill_id = str(source_run.get("skillId") or source_run.get("skill_id") or "").strip()
    if request.skill_id and source_skill_id and request.skill_id != source_skill_id:
        raise AgentContinuationError("继续执行时暂不支持切换 Skill，请新建一次执行")

    source_conversation_id = str(source_run.get("conversationId") or source_run.get("conversation_id") or "").strip() or None
    if request.conversation_id and source_conversation_id and request.conversation_id != source_conversation_id:
        raise AgentContinuationError("继续执行时不能切换到其他会话")

    source_params = source_run.get("params") or {}
    if not isinstance(source_params, dict):
        source_params = {}
    merged_params = {**source_params, **request.params}

    effective_query = request.query or str(source_run.get("query") or "").strip()
    if not effective_query:
        raise AgentContinuationError("上一轮执行缺少可继续的任务描述")

    effective_request = request.model_copy(
        update={
            "query": effective_query,
            "skill_id": request.skill_id or source_skill_id or None,
            "params": merged_params,
            "conversation_id": request.conversation_id or source_conversation_id,
        }
    )
    return effective_request, source_run


async def execute_agent_stream(request: AgentExecuteRequest):
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    effective_request, source_run = await _resolve_continuation_request(request)
    deps = await build_agent_deps(effective_request)

    if source_run:
        prior_message_history = await load_run_message_history(source_run["runId"])
    else:
        prior_message_history = await load_latest_message_history(
            deps.conversation_id,
            deps.role_id,
            exclude_run_id=deps.run_id,
        )

    skill_name = deps.skill.name if deps.skill else None
    adapter = AgentEventAdapter(
        queue=queue,
        run_id=deps.run_id,
        role_id=deps.role_id,
        query=effective_request.query,
        policy=deps.policy,
        skill_id=effective_request.skill_id,
        skill_name=skill_name,
        conversation_id=deps.conversation_id,
        request_params=deps.request_params,
        model=deps.model,
        llm_profile_id=deps.llm_profile_id,
        continue_from_run_id=effective_request.continue_from_run_id,
        continue_mode=effective_request.continue_mode,
    )
    deps.event_adapter = adapter
    task: asyncio.Task | None = None

    async def _run() -> None:
        result = None
        with _capture_run_messages_context() as captured_messages:
            try:
                prompt = _append_skill_context(_build_runtime_prompt(effective_request), deps)
                surfaces = _enabled_retrieval_surfaces(deps.policy)
                if surfaces:
                    retrieval_query = effective_request.continue_notes or effective_request.query
                    assembled = await deps.context_assembler.assemble(
                        user_query=retrieval_query,
                        role_id=deps.role_id,
                        planner_settings=RetrievalPlannerSettings(
                            api_url=deps.api_url,
                            api_key=deps.api_key,
                            model=deps.model,
                        ),
                        enabled_surfaces=surfaces,
                        trace_handler=adapter,
                    )
                    prompt_ctx = assembled.fit_to_budget(3200)
                    if prompt_ctx.has_context:
                        prompt = _append_skill_context(
                            _build_runtime_prompt(
                                effective_request,
                                context_suffix=prompt_ctx.to_prompt_suffix(),
                            ),
                            deps,
                        )
                        for _raw in prompt_ctx.to_metadata_payload().get("citations", []):
                            _c = AgentCitation(**_raw) if isinstance(_raw, dict) else _raw
                            if _c not in deps.memory.citations:
                                deps.memory.citations.append(_c)

                agent = create_runtime_agent(deps)
                result = await agent.run(
                    prompt,
                    deps=deps,
                    message_history=prior_message_history or None,
                )
                final_result = map_final_result(result.output, deps)
                await adapter.emit_complete(
                    final_result,
                    message_history=_extract_message_history(result, captured_messages),
                )
            except asyncio.CancelledError:
                await adapter.emit_cancelled(
                    message_history=_extract_message_history(result, captured_messages),
                )
            except Exception as exc:
                await adapter.emit_error(
                    str(exc),
                    message_history=_extract_message_history(result, captured_messages),
                )
            finally:
                await run_registry.unregister(deps.run_id, task)
                await run_registry.clear_cancel_request(deps.run_id)
                await queue.put(None)

    await adapter.emit_execution_start()
    if await run_registry.is_cancel_requested(deps.run_id):
        await adapter.emit_cancelled()
        await run_registry.clear_cancel_request(deps.run_id)
        await queue.put(None)
    else:
        task = asyncio.create_task(_run())
        await run_registry.register(deps.run_id, task)

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        if task is not None:
            await task
