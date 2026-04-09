from __future__ import annotations

import asyncio
from typing import Any

from services.agent_runtime.history import initialize_agent_run, persist_agent_state
from services.agent_runtime.models import (
    AgentEvent,
    AgentExecutionState,
    AgentFinalResult,
    AgentStepState,
    RolePolicy,
)
from services.storage import utc_now_iso


_TRACE_LABELS = {
    "planner": "规划检索策略",
    "retrieve_knowledge": "检索知识库",
    "retrieve_knowhow": "检索规则库",
    "retrieve_skill": "检索技能库",
    "get_skill_definition": "读取 Skill 定义",
    "extract_file_text": "提取文件文本",
    "run_excel_category_mapping": "执行 Excel 分类映射",
    "query_knowledge": "查询知识库",
    "search_knowhow_rules": "查询规则库",
    "finalize": "整理最终结果",
    "cancel": "取消执行",
}


class AgentEventAdapter:
    """Translate runtime activity into the frontend SSE contract."""

    def __init__(
        self,
        queue: "asyncio.Queue[dict[str, Any]]",
        run_id: str,
        role_id: str,
        query: str,
        policy: RolePolicy,
        skill_id: str | None = None,
        skill_name: str | None = None,
        conversation_id: str | None = None,
        request_params: dict[str, Any] | None = None,
        model: str = "",
        llm_profile_id: str | None = None,
        continue_from_run_id: str | None = None,
        continue_mode: str = "",
    ) -> None:
        self._queue = queue
        self._state = AgentExecutionState(
            run_id=run_id,
            role_id=role_id,
            skill_id=skill_id,
            skill_name=skill_name,
            query=query,
            status="pending",
            conversation_id=conversation_id,
        )
        self._policy = policy
        self._request_params = request_params or {}
        self._model = model
        self._llm_profile_id = llm_profile_id
        self._continue_from_run_id = continue_from_run_id
        self._continue_mode = continue_mode
        self._next_step_index = 1

    @property
    def state(self) -> AgentExecutionState:
        return self._state

    async def emit_execution_start(self) -> None:
        self._state.status = "running"
        self._state.started_at = utc_now_iso()
        await initialize_agent_run(
            self._state,
            params=self._request_params,
            model=self._model,
            llm_profile_id=self._llm_profile_id,
            continue_from_run_id=self._continue_from_run_id,
            continue_mode=self._continue_mode,
        )
        await persist_agent_state(self._state)
        await self._emit(
            AgentEvent(
                type="execution_start",
                run_id=self._state.run_id,
                surface="agent",
                role_id=self._state.role_id,
                skill_id=self._state.skill_id,
                skill_name=self._state.skill_name,
                query=self._state.query,
                context=self._build_context_payload(include_result=False),
            )
        )

    async def on_stage_start(
        self,
        step_key: str,
        *,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        step = self._append_step(
            step_key=step_key,
            description=description or _TRACE_LABELS.get(step_key, step_key),
            tool_name=None,
            metadata=metadata,
        )
        await persist_agent_state(self._state)
        await self._emit(
            AgentEvent(
                type="step_start",
                run_id=self._state.run_id,
                step=step.index,
                step_key=step.step_key,
                description=step.description,
                step_state=step,
            )
        )
        return step.index

    async def on_stage_complete(
        self,
        step_index: int,
        step_key: str,
        result: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        step = self._get_step(step_index)
        if not step:
            return
        step.status = "completed"
        step.result = result
        step.completed_at = utc_now_iso()
        step.metadata = self._merge_metadata(step.metadata, metadata)
        await persist_agent_state(self._state)
        await self._emit(
            AgentEvent(
                type="step_complete",
                run_id=self._state.run_id,
                step=step.index,
                step_key=step.step_key,
                result=result,
                step_state=step,
            )
        )

    async def on_stage_error(
        self,
        step_index: int,
        step_key: str,
        error: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        step = self._get_step(step_index)
        if not step:
            return
        step.status = "failed"
        step.error = error
        step.completed_at = utc_now_iso()
        step.metadata = self._merge_metadata(step.metadata, metadata)
        await persist_agent_state(self._state)
        await self._emit(
            AgentEvent(
                type="step_error",
                run_id=self._state.run_id,
                step=step.index,
                step_key=step.step_key,
                error=error,
                step_state=step,
            )
        )

    async def on_tool_start(
        self,
        tool_name: str,
        *,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        step = self._append_step(
            step_key=tool_name,
            description=description or _TRACE_LABELS.get(tool_name, tool_name),
            tool_name=tool_name,
            metadata=metadata,
        )
        await persist_agent_state(self._state)
        await self._emit(
            AgentEvent(
                type="step_start",
                run_id=self._state.run_id,
                step=step.index,
                step_key=step.step_key,
                description=step.description,
                step_state=step,
            )
        )
        return step.index

    async def on_tool_complete(
        self,
        step_index: int,
        tool_name: str,
        result: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        step = self._get_step(step_index)
        if not step:
            return
        step.status = "completed"
        step.tool_name = tool_name
        step.result = result
        step.completed_at = utc_now_iso()
        step.metadata = self._merge_metadata(step.metadata, metadata)
        if tool_name and tool_name not in self._state.used_tools:
            self._state.used_tools.append(tool_name)
        await persist_agent_state(self._state)
        await self._emit(
            AgentEvent(
                type="step_complete",
                run_id=self._state.run_id,
                step=step.index,
                step_key=step.step_key,
                result=result,
                step_state=step,
            )
        )

    async def on_tool_error(
        self,
        step_index: int,
        tool_name: str,
        error: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        step = self._get_step(step_index)
        if not step:
            return
        step.status = "failed"
        step.tool_name = tool_name
        step.error = error
        step.completed_at = utc_now_iso()
        step.metadata = self._merge_metadata(step.metadata, metadata)
        await persist_agent_state(self._state)
        await self._emit(
            AgentEvent(
                type="step_error",
                run_id=self._state.run_id,
                step=step.index,
                step_key=step.step_key,
                error=error,
                step_state=step,
            )
        )

    async def emit_complete(
        self,
        final_result: AgentFinalResult,
        *,
        message_history: Any = None,
    ) -> None:
        finalize_summary = final_result.summary or final_result.raw_text
        finalize_step_index = await self.on_tool_start(
            "finalize",
            description=_TRACE_LABELS["finalize"],
            metadata={
                "used_tools": list(final_result.used_tools),
                "citation_count": len(final_result.citations),
                "artifact_count": len(final_result.artifacts),
            },
        )
        await self.on_tool_complete(
            finalize_step_index,
            "finalize",
            finalize_summary,
        )

        self._state.status = "completed"
        self._state.completed_at = utc_now_iso()
        self._state.final_result = final_result
        await persist_agent_state(
            self._state,
            final_result=final_result,
            message_history=message_history,
        )
        await self._emit(
            AgentEvent(
                type="complete",
                run_id=self._state.run_id,
                result=final_result.raw_text,
                final_result=final_result,
                context=self._build_context_payload(include_result=True),
            )
        )

    async def emit_error(self, message: str, *, message_history: Any = None) -> None:
        self._close_open_steps("failed", message)
        self._state.status = "failed"
        self._state.completed_at = utc_now_iso()
        self._state.error = message
        await persist_agent_state(
            self._state,
            error=message,
            message_history=message_history,
        )
        await self._emit(
            AgentEvent(
                type="error",
                run_id=self._state.run_id,
                message=message,
                context=self._build_context_payload(include_result=False),
            )
        )

    async def emit_cancelled(
        self,
        message: str = "执行已取消",
        *,
        message_history: Any = None,
    ) -> None:
        self._close_open_steps("cancelled", message)
        cancel_step_index = await self.on_tool_start(
            "cancel",
            description=_TRACE_LABELS["cancel"],
            metadata={"message": message},
        )
        await self.on_tool_complete(
            cancel_step_index,
            "cancel",
            message,
        )

        self._state.status = "cancelled"
        self._state.completed_at = utc_now_iso()
        self._state.error = message
        await persist_agent_state(
            self._state,
            error=message,
            message_history=message_history,
        )
        await self._emit(
            AgentEvent(
                type="cancelled",
                run_id=self._state.run_id,
                message=message,
                context=self._build_context_payload(include_result=False),
            )
        )

    def _append_step(
        self,
        *,
        step_key: str,
        description: str,
        tool_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentStepState:
        step = AgentStepState(
            index=self._next_step_index,
            step_key=step_key,
            description=description,
            status="running",
            tool_name=tool_name,
            metadata=metadata or {},
            started_at=utc_now_iso(),
        )
        self._next_step_index += 1
        self._state.steps.append(step)
        return step

    def _get_step(self, step_index: int) -> AgentStepState | None:
        return next((step for step in self._state.steps if step.index == step_index), None)

    @staticmethod
    def _merge_metadata(
        current: dict[str, Any] | None,
        updates: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = dict(current or {})
        if updates:
            merged.update(updates)
        return merged

    def _close_open_steps(self, next_status: str, message: str) -> None:
        for step in self._state.steps:
            if step.status != "running":
                continue
            step.status = next_status  # type: ignore[assignment]
            step.error = message
            step.completed_at = utc_now_iso()

    def _build_context_payload(self, *, include_result: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self._state.status,
            "steps": [step.model_dump() for step in self._state.steps],
        }
        if include_result and self._state.final_result is not None:
            payload["result"] = self._state.final_result.raw_text
        return payload

    async def _emit(self, event: AgentEvent) -> None:
        await self._queue.put(event.model_dump(exclude_none=True))
