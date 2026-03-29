from __future__ import annotations

from pydantic_ai import RunContext

from services.agent_runtime.errors import AgentToolExecutionError
from services.agent_runtime.models import (
    AgentDeps,
    AgentToolCallRecord,
    GetSkillDefinitionInput,
    GetSkillDefinitionOutput,
)
from services.storage import utc_now_iso


def register_skill_tools(agent, policy) -> None:
    if "get_skill_definition" not in policy.allowed_tools:
        return

    @agent.tool
    async def get_skill_definition(
        ctx: RunContext[AgentDeps],
        input_data: GetSkillDefinitionInput,
    ) -> GetSkillDefinitionOutput:
        started_at = utc_now_iso()
        step_index = await ctx.deps.event_adapter.on_tool_start(
            "get_skill_definition",
            description=f"读取 Skill 定义：{input_data.skill_id}",
            metadata={"args": input_data.model_dump()},
        )
        try:
            if not ctx.deps.skill_manager._loaded:
                await ctx.deps.skill_manager.initialize()

            skill = ctx.deps.skill_manager.get_skill(input_data.skill_id)
            if not skill:
                raise AgentToolExecutionError(f"Skill {input_data.skill_id} 不存在")

            output = GetSkillDefinitionOutput(
                skill_id=skill.id,
                name=skill.name,
                description=skill.description,
                parameters=list(skill.parameters),
                steps=list(skill.steps),
                output_template=skill.output_template,
            )
            summary = f"已读取 Skill「{skill.name}」定义"
            ctx.deps.memory.used_tools.append("get_skill_definition")
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="get_skill_definition",
                    args=input_data.model_dump(),
                    ok=True,
                    summary=summary,
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_complete(
                step_index,
                "get_skill_definition",
                summary,
                metadata={"skill_id": skill.id, "skill_name": skill.name},
            )
            return output
        except Exception as exc:
            ctx.deps.memory.tool_calls.append(
                AgentToolCallRecord(
                    tool_name="get_skill_definition",
                    args=input_data.model_dump(),
                    ok=False,
                    summary=str(exc),
                    started_at=started_at,
                    completed_at=utc_now_iso(),
                )
            )
            await ctx.deps.event_adapter.on_tool_error(
                step_index,
                "get_skill_definition",
                str(exc),
            )
            raise
