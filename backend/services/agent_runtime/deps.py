from __future__ import annotations

from dataclasses import asdict

from services.agent_runtime.errors import AgentConfigurationError
from services.agent_runtime.models import (
    AgentDeps,
    AgentExecuteRequest,
    AgentRuntimeMemory,
    AgentSkillExecutionProfile,
)
from services.agent_runtime.role_policy import load_agent_role_policy
from services.context_assembler import context_assembler
from services.knowhow_service import knowhow_service
from services.knowledge_service import knowledge_service
from services.llm_profiles import get_runtime_llm_config
from services.skill_manager import skill_manager
from services.access_control import is_admin
from services.storage import gen_id, storage


def _apply_skill_profile(policy, skill):
    execution_profile = AgentSkillExecutionProfile(**asdict(skill.execution_profile))
    if execution_profile.allowed_tools:
        allowed_tools = [
            tool_name
            for tool_name in policy.allowed_tools
            if tool_name in execution_profile.allowed_tools
        ]
    else:
        allowed_tools = list(policy.allowed_tools)

    instruction_lines = [policy.instructions]
    if execution_profile.allowed_tools:
        instruction_lines.append(
            f"当前 Skill 允许使用的工具仅限：{', '.join(allowed_tools) if allowed_tools else '无'}。"
        )
    if execution_profile.output_kind:
        instruction_lines.append(f"本次结果应优先组织成 {execution_profile.output_kind} 风格。")
    if execution_profile.output_sections:
        instruction_lines.append(
            f"建议输出章节：{'、'.join(execution_profile.output_sections)}。"
        )

    updated_policy = policy.model_copy(
        update={
            "allowed_tools": allowed_tools,
            "instructions": "\n\n".join(part for part in instruction_lines if part),
        }
    )
    return execution_profile, updated_policy


async def build_agent_deps(request: AgentExecuteRequest, user: dict | None = None) -> AgentDeps:
    llm_config = await get_runtime_llm_config(
        profile_id=request.llm_profile_id,
        api_url=request.api_url,
        api_key=request.api_key,
        model=request.model,
    )
    if not llm_config["api_url"] or not llm_config["api_key"]:
        raise AgentConfigurationError("Agent 执行需要可用的模型配置，请先由管理员完成配置")

    role, policy = await load_agent_role_policy(storage, request.role_id)
    run_id = request.run_id or gen_id()
    active_skill = None
    skill_execution_profile = None

    if request.skill_id:
        if not skill_manager._loaded:
            await skill_manager.initialize()
        active_skill = skill_manager.get_skill(request.skill_id)
        if active_skill:
            skill_execution_profile, policy = _apply_skill_profile(policy, active_skill)

    return AgentDeps(
        role_id=policy.role_id,
        surface="agent",
        policy=policy,
        role=role,
        storage=storage,
        knowledge_service=knowledge_service,
        knowhow_service=knowhow_service,
        skill_manager=skill_manager,
        context_assembler=context_assembler,
        api_url=llm_config["api_url"],
        api_key=llm_config["api_key"],
        model=llm_config["model"],
        run_id=run_id,
        request_params=dict(request.params),
        user_id=str((user or {}).get("id") or "") or None,
        group_id=str((user or {}).get("group_id") or "") or None,
        is_admin=is_admin(user),
        conversation_id=request.conversation_id,
        llm_profile_id=llm_config["profile_id"],
        skill=active_skill,
        skill_execution_profile=skill_execution_profile,
        memory=AgentRuntimeMemory(),
    )
