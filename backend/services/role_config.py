from __future__ import annotations

import json
from typing import Any

VALID_SURFACES = {"chat", "agent"}
VALID_AGENT_TOOLS = {
    "get_skill_definition",
    "extract_file_text",
    "query_knowledge",
    "search_knowhow_rules",
}
VALID_CHAT_CAPABILITIES = {
    "auto_knowledge",
    "auto_knowhow",
    "auto_skill_suggestion",
}
VALID_AGENT_PREFLIGHT = {
    "pre_match_skill",
    "auto_knowledge",
    "auto_knowhow",
}


def parse_string_list(raw_value: Any, fallback: list[str] | None = None) -> list[str]:
    if raw_value is None:
        return list(fallback or [])

    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]

    text = str(raw_value).strip()
    if not text:
        return list(fallback or [])

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return list(fallback or [])

    if not isinstance(parsed, list):
        return list(fallback or [])
    return [str(item).strip() for item in parsed if str(item).strip()]


def unique_string_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def derive_chat_capabilities_from_legacy(capabilities: list[str]) -> list[str]:
    derived: list[str] = []
    if "rag" in capabilities:
        derived.extend(["auto_knowledge", "auto_knowhow"])
    if "skills" in capabilities:
        derived.append("auto_skill_suggestion")
    return unique_string_list(derived)


def derive_agent_preflight_from_legacy(
    capabilities: list[str],
    agent_allowed_tools: list[str] | None = None,
) -> list[str]:
    derived: list[str] = []
    tools = set(agent_allowed_tools or [])
    if "skills" in capabilities:
        derived.append("pre_match_skill")
    if "rag" in capabilities or "query_knowledge" in tools:
        derived.append("auto_knowledge")
    if "rag" in capabilities or "search_knowhow_rules" in tools:
        derived.append("auto_knowhow")
    return unique_string_list(derived)


def derive_legacy_capabilities(
    chat_capabilities: list[str] | None = None,
    agent_preflight: list[str] | None = None,
    agent_allowed_tools: list[str] | None = None,
) -> list[str]:
    chat_caps = set(chat_capabilities or [])
    preflight = set(agent_preflight or [])
    tools = set(agent_allowed_tools or [])
    legacy: list[str] = []

    if chat_caps.intersection({"auto_knowledge", "auto_knowhow"}) or preflight.intersection({"auto_knowledge", "auto_knowhow"}) or "query_knowledge" in tools:
        legacy.append("rag")
    if "auto_skill_suggestion" in chat_caps or "pre_match_skill" in preflight or "get_skill_definition" in tools:
        legacy.append("skills")
    return unique_string_list(legacy)


def resolve_chat_capabilities(role: dict) -> list[str]:
    legacy_capabilities = parse_string_list(role.get("capabilities"), fallback=[])
    resolved = parse_string_list(role.get("chat_capabilities"))
    if resolved:
        return resolved
    return derive_chat_capabilities_from_legacy(legacy_capabilities)


def resolve_agent_preflight(role: dict) -> list[str]:
    legacy_capabilities = parse_string_list(role.get("capabilities"), fallback=[])
    allowed_tools = parse_string_list(role.get("agent_allowed_tools"), fallback=[])
    resolved = parse_string_list(role.get("agent_preflight"))
    if resolved:
        return resolved
    return derive_agent_preflight_from_legacy(legacy_capabilities, allowed_tools)
