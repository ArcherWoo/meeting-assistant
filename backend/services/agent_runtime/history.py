from __future__ import annotations

import json
from typing import Any

from services.agent_runtime.models import AgentExecutionState, AgentFinalResult
from services.storage import storage


def _message_history_adapter() -> Any | None:
    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter
    except ImportError:
        return None
    return ModelMessagesTypeAdapter


def serialize_message_history(messages: Any) -> str:
    if messages is None:
        return "[]"
    if isinstance(messages, (bytes, bytearray)):
        return messages.decode("utf-8", errors="ignore") or "[]"
    if isinstance(messages, str):
        return messages or "[]"

    adapter = _message_history_adapter()
    if adapter is not None:
        try:
            payload = adapter.dump_json(messages)
            if isinstance(payload, (bytes, bytearray)):
                return payload.decode("utf-8", errors="ignore") or "[]"
            return str(payload or "[]")
        except Exception:
            pass

    try:
        return json.dumps(messages, ensure_ascii=False)
    except TypeError:
        return "[]"


def deserialize_message_history(payload: Any) -> list[Any]:
    text = serialize_message_history(payload)
    adapter = _message_history_adapter()
    if adapter is not None:
        try:
            return list(adapter.validate_json(text))
        except Exception:
            pass

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


async def initialize_agent_run(
    state: AgentExecutionState,
    *,
    params: dict,
    model: str,
    llm_profile_id: str | None,
    continue_from_run_id: str | None = None,
    continue_mode: str = "",
    message_history: Any = None,
) -> dict:
    return await storage.create_agent_run(
        run_id=state.run_id,
        conversation_id=state.conversation_id,
        role_id=state.role_id,
        query=state.query,
        params=params,
        continue_from_run_id=continue_from_run_id,
        continue_mode=continue_mode,
        skill_id=state.skill_id,
        skill_name=state.skill_name,
        model=model,
        llm_profile_id=llm_profile_id,
        message_history=serialize_message_history(message_history),
        status=state.status,
        surface=state.surface,
        started_at=state.started_at,
    )


async def persist_agent_steps(state: AgentExecutionState) -> None:
    for step in state.steps:
        await storage.upsert_agent_run_step(
            run_id=state.run_id,
            step_index=step.index,
            step_key=step.step_key,
            description=step.description,
            status=step.status,
            result=step.result or "",
            error=step.error or "",
            tool_name=step.tool_name or "",
            metadata=step.metadata,
            started_at=step.started_at,
            completed_at=step.completed_at,
        )


async def persist_agent_state(
    state: AgentExecutionState,
    *,
    final_result: AgentFinalResult | None = None,
    error: str | None = None,
    message_history: Any = None,
) -> dict | None:
    await persist_agent_steps(state)
    return await storage.update_agent_run(
        state.run_id,
        status=state.status,
        skill_id=state.skill_id,
        skill_name=state.skill_name,
        message_history=serialize_message_history(message_history) if message_history is not None else None,
        final_result=final_result.model_dump() if final_result else None,
        error=error,
        started_at=state.started_at,
        completed_at=state.completed_at,
    )


async def load_agent_run(run_id: str) -> dict | None:
    return await storage.get_agent_run(run_id)


async def load_run_message_history(run_id: str) -> list[Any]:
    payload = await storage.get_agent_run_message_history(run_id)
    return deserialize_message_history(payload)


async def load_latest_message_history(
    conversation_id: str | None,
    role_id: str,
    *,
    exclude_run_id: str | None = None,
) -> list[Any]:
    payload = await storage.get_latest_agent_message_history(
        conversation_id,
        role_id,
        exclude_run_id=exclude_run_id,
    )
    return deserialize_message_history(payload)
