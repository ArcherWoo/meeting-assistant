from __future__ import annotations

from services.agent_runtime.errors import RoleNotAllowedForSurfaceError
from services.agent_runtime.models import RolePolicy
from services.role_config import parse_string_list, resolve_agent_preflight, resolve_chat_capabilities
from services.system_prompt_defaults import DEFAULT_SYSTEM_PROMPTS


def normalize_agent_role_id(role_id: str) -> str:
    normalized = (role_id or "").strip()
    if normalized == "agent":
        return "executor"
    return normalized


def _default_allowed_surfaces(role_id: str) -> list[str]:
    if role_id == "executor":
        return ["agent"]
    if role_id == "builder":
        return ["chat", "agent"]
    return ["chat"]


def _default_allowed_tools(capabilities: list[str], agent_preflight: list[str]) -> list[str]:
    tools = [
        "get_skill_definition",
        "extract_file_text",
        "search_knowhow_rules",
        "run_excel_category_mapping",
    ]
    if "rag" in capabilities or "auto_knowledge" in agent_preflight:
        tools.append("query_knowledge")
    return tools


def build_agent_instructions(
    role: dict,
    *,
    agent_preflight: list[str],
    allowed_tools: list[str],
) -> str:
    system_prompt = str(role.get("system_prompt") or "").strip()
    agent_prompt = str(role.get("agent_prompt") or "").strip()
    base_prompt = "\n\n".join(part for part in [system_prompt, agent_prompt] if part)
    if not base_prompt:
        base_prompt = DEFAULT_SYSTEM_PROMPTS.get(str(role.get("id") or ""), "")

    suffix_parts = [
        "你当前运行在 agent surface 下，不是普通聊天模式。",
        "优先通过工具获取事实依据，再给出结果。",
        "执行过程保持透明，结论清晰，引用尽量来自知识库、规则库或技能定义。",
        "如果工具不足以支撑结论，要明确说明依据不足。",
    ]
    if "pre_match_skill" in agent_preflight:
        suffix_parts.append("当前角色已启用 Skill 预匹配，可先判断当前任务是否适合复用现有 Skill。")
    if "auto_knowledge" in agent_preflight or "auto_knowhow" in agent_preflight:
        enabled_sources = []
        if "auto_knowledge" in agent_preflight:
            enabled_sources.append("知识库")
        if "auto_knowhow" in agent_preflight:
            enabled_sources.append("规则库")
        suffix_parts.append(f"当前角色已启用执行前上下文检索：{', '.join(enabled_sources)}。")
    if allowed_tools:
        suffix_parts.append(f"当前可用工具：{', '.join(allowed_tools)}。")
    else:
        suffix_parts.append("当前未配置专用工具，请直接进行规划、分析，并输出结构化最终结果。")

    return "\n\n".join(part for part in [base_prompt, *suffix_parts] if part)


async def load_agent_role_policy(storage, role_id: str) -> tuple[dict, RolePolicy]:
    normalized_role_id = normalize_agent_role_id(role_id)
    role = await storage.get_role(normalized_role_id)
    if not role and normalized_role_id == "executor":
        role = await storage.get_role("agent")
    if not role:
        raise RoleNotAllowedForSurfaceError(f"角色 {normalized_role_id} 不存在")

    capabilities = parse_string_list(role.get("capabilities"), fallback=[])
    chat_capabilities = resolve_chat_capabilities(role)
    agent_preflight = resolve_agent_preflight(role)
    allowed_surfaces = parse_string_list(
        role.get("allowed_surfaces"),
        fallback=_default_allowed_surfaces(normalized_role_id),
    )
    if "agent" not in allowed_surfaces:
        raise RoleNotAllowedForSurfaceError(f"当前角色 {normalized_role_id} 不允许在 agent 链路执行")

    raw_allowed_tools = role.get("agent_allowed_tools")
    if raw_allowed_tools is None or (isinstance(raw_allowed_tools, str) and not raw_allowed_tools.strip()):
        allowed_tools = _default_allowed_tools(capabilities, agent_preflight)
    else:
        allowed_tools = parse_string_list(raw_allowed_tools, fallback=[])

    policy = RolePolicy(
        role_id=normalized_role_id,
        allowed=True,
        capabilities=capabilities,
        chat_capabilities=chat_capabilities,
        agent_preflight=agent_preflight,
        allowed_surfaces=allowed_surfaces,
        allowed_tools=allowed_tools,
        enable_rag="auto_knowledge" in agent_preflight,
        enable_skill_matching="pre_match_skill" in agent_preflight,
        instructions=build_agent_instructions(
            role,
            agent_preflight=agent_preflight,
            allowed_tools=allowed_tools,
        ),
        display_name=str(role.get("name") or normalized_role_id),
        icon=str(role.get("icon") or "") or None,
    )
    return role, policy
