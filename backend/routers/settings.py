"""
Settings routes.

Exposes:
- Role CRUD
- System prompt CRUD
- System prompt preset CRUD
- Embedding config CRUD + connection test

Prompt Template / Prompt Pack APIs were removed because they were not wired into
the real chat path and would mislead users.
"""
import json
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.role_config import (
    VALID_AGENT_PREFLIGHT,
    VALID_AGENT_TOOLS,
    VALID_CHAT_CAPABILITIES,
    VALID_SURFACES,
    derive_agent_preflight_from_legacy,
    derive_chat_capabilities_from_legacy,
    derive_legacy_capabilities,
    parse_string_list,
    unique_string_list,
)
from services.storage import storage, utc_now_iso
from services.system_prompt_defaults import DEFAULT_SYSTEM_PROMPTS

router = APIRouter()

_SYSTEM_PROMPT_PRESETS_KEY = "system_prompt_presets"
_LEGACY_MODES = {"copilot", "builder", "agent", "executor"}
_EMB_URL_KEY = "embedding_api_url"
_EMB_KEY_KEY = "embedding_api_key"
_EMB_MODEL_KEY = "embedding_model"
_EMB_MODEL_DEFAULT = "text-embedding-3-small"


class RoleCreateRequest(BaseModel):
    name: str
    icon: str = "🤖"
    description: str = ""
    system_prompt: str = ""
    agent_prompt: str = ""
    capabilities: list[str] = Field(default_factory=list)
    chat_capabilities: list[str] = Field(default_factory=list)
    agent_preflight: list[str] = Field(default_factory=list)
    allowed_surfaces: list[str] = Field(default_factory=lambda: ["chat"])
    agent_allowed_tools: list[str] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    agent_prompt: Optional[str] = None
    capabilities: Optional[list[str]] = None
    chat_capabilities: Optional[list[str]] = None
    agent_preflight: Optional[list[str]] = None
    allowed_surfaces: Optional[list[str]] = None
    agent_allowed_tools: Optional[list[str]] = None
    sort_order: Optional[int] = None


class SystemPromptRequest(BaseModel):
    prompt: str


class SystemPromptBundleRequest(BaseModel):
    prompts: dict[str, str] = Field(default_factory=dict)


class SystemPromptPresetRequest(BaseModel):
    name: str
    role_id: str
    prompt: str


class EmbeddingConfigRequest(BaseModel):
    api_url: str = ""
    api_key: str = ""
    model: str = _EMB_MODEL_DEFAULT


def _settings_key(role_id: str) -> str:
    return f"system_prompt_{role_id}"


def _ensure_role_id(role_id: str) -> str:
    normalized = (role_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="角色 ID 不能为空")
    if normalized == "agent":
        return "executor"
    return normalized


def _normalize_role_row(row: dict) -> dict:
    capabilities = parse_string_list(row.get("capabilities"), fallback=[])
    agent_allowed_tools = parse_string_list(row.get("agent_allowed_tools"), fallback=[])
    chat_capabilities = parse_string_list(row.get("chat_capabilities"))
    agent_preflight = parse_string_list(row.get("agent_preflight"))
    if not chat_capabilities:
        chat_capabilities = derive_chat_capabilities_from_legacy(capabilities)
    if not agent_preflight:
        agent_preflight = derive_agent_preflight_from_legacy(capabilities, agent_allowed_tools)

    return {
        **row,
        "capabilities": capabilities,
        "chat_capabilities": chat_capabilities,
        "agent_preflight": agent_preflight,
        "allowed_surfaces": parse_string_list(row.get("allowed_surfaces"), fallback=["chat"]),
        "agent_allowed_tools": agent_allowed_tools,
        "agent_prompt": str(row.get("agent_prompt") or ""),
    }


def _builtin_default_prompt(role_id: str) -> str:
    return DEFAULT_SYSTEM_PROMPTS.get(role_id, "")


def _validate_allowed_surfaces(values: list[str]) -> list[str]:
    normalized = unique_string_list(values)
    if not normalized:
        raise HTTPException(status_code=400, detail="角色至少需要启用一个 surface")
    if any(value not in VALID_SURFACES for value in normalized):
        raise HTTPException(status_code=400, detail="allowed_surfaces 仅支持 chat / agent")
    return normalized


def _validate_chat_capabilities(values: list[str]) -> list[str]:
    normalized = unique_string_list(values)
    if any(value not in VALID_CHAT_CAPABILITIES for value in normalized):
        raise HTTPException(status_code=400, detail="chat_capabilities 包含未知能力")
    return normalized


def _validate_agent_preflight(values: list[str]) -> list[str]:
    normalized = unique_string_list(values)
    if any(value not in VALID_AGENT_PREFLIGHT for value in normalized):
        raise HTTPException(status_code=400, detail="agent_preflight 包含未知预处理能力")
    return normalized


def _validate_agent_allowed_tools(values: list[str]) -> list[str]:
    normalized = unique_string_list(values)
    if any(value not in VALID_AGENT_TOOLS for value in normalized):
        raise HTTPException(status_code=400, detail="agent_allowed_tools 包含未知工具")
    return normalized


def _normalize_legacy_capabilities(values: list[str]) -> list[str]:
    return unique_string_list(values)


def _resolve_policy_fields_for_create(request: RoleCreateRequest) -> tuple[list[str], list[str], list[str], list[str]]:
    legacy_capabilities = _normalize_legacy_capabilities(request.capabilities)
    agent_allowed_tools = _validate_agent_allowed_tools(request.agent_allowed_tools)
    chat_capabilities = _validate_chat_capabilities(
        request.chat_capabilities or derive_chat_capabilities_from_legacy(legacy_capabilities)
    )
    agent_preflight = _validate_agent_preflight(
        request.agent_preflight or derive_agent_preflight_from_legacy(legacy_capabilities, agent_allowed_tools)
    )
    capabilities = _normalize_legacy_capabilities(
        legacy_capabilities or derive_legacy_capabilities(chat_capabilities, agent_preflight, agent_allowed_tools)
    )
    return capabilities, chat_capabilities, agent_preflight, agent_allowed_tools


def _resolve_policy_fields_for_update(existing: dict, request: RoleUpdateRequest) -> tuple[list[str], list[str], list[str], list[str]]:
    current = _normalize_role_row(existing)

    if request.agent_allowed_tools is not None:
        agent_allowed_tools = _validate_agent_allowed_tools(request.agent_allowed_tools)
    else:
        agent_allowed_tools = list(current["agent_allowed_tools"])

    if request.chat_capabilities is not None:
        chat_capabilities = _validate_chat_capabilities(request.chat_capabilities)
    elif request.capabilities is not None:
        chat_capabilities = derive_chat_capabilities_from_legacy(_normalize_legacy_capabilities(request.capabilities))
    else:
        chat_capabilities = list(current["chat_capabilities"])

    if request.agent_preflight is not None:
        agent_preflight = _validate_agent_preflight(request.agent_preflight)
    elif request.capabilities is not None:
        agent_preflight = derive_agent_preflight_from_legacy(
            _normalize_legacy_capabilities(request.capabilities),
            agent_allowed_tools,
        )
    else:
        agent_preflight = list(current["agent_preflight"])

    if request.capabilities is not None:
        capabilities = _normalize_legacy_capabilities(request.capabilities)
    elif any(
        value is not None
        for value in (request.chat_capabilities, request.agent_preflight, request.agent_allowed_tools)
    ):
        capabilities = derive_legacy_capabilities(chat_capabilities, agent_preflight, agent_allowed_tools)
    else:
        capabilities = list(current["capabilities"])

    return capabilities, chat_capabilities, agent_preflight, agent_allowed_tools


async def _role_default_prompt(role_id: str) -> str:
    role = await storage.get_role(role_id)
    if role and role.get("system_prompt"):
        return str(role["system_prompt"])
    return _builtin_default_prompt(role_id)


async def _get_prompt(role_id: str) -> tuple[str, bool]:
    normalized_role_id = _ensure_role_id(role_id)
    value = await storage.get_setting(_settings_key(normalized_role_id), default="")
    if value:
        return value, True
    return await _role_default_prompt(normalized_role_id), False


async def _get_prompt_bundle() -> dict:
    roles = await storage.list_roles()
    prompts: dict[str, str] = {}
    defaults: dict[str, str] = {}
    custom_role_ids: list[str] = []

    for role in roles:
        role_id = str(role["id"])
        prompt, is_custom = await _get_prompt(role_id)
        prompts[role_id] = prompt
        defaults[role_id] = _builtin_default_prompt(role_id) or str(role.get("system_prompt") or "")
        if is_custom:
            custom_role_ids.append(role_id)

    return {
        "prompts": prompts,
        "defaults": defaults,
        "custom_role_ids": sorted(custom_role_ids),
    }


async def _load_system_prompt_presets() -> list[dict]:
    raw_value = await storage.get_setting(_SYSTEM_PROMPT_PRESETS_KEY, default="")
    if not raw_value.strip():
        return []

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []

    presets: list[dict] = []
    needs_migration = False

    for item in parsed if isinstance(parsed, list) else []:
        if not isinstance(item, dict):
            continue

        preset_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not preset_id or not name:
            continue

        role_id = _ensure_role_id(str(item.get("role_id") or item.get("mode") or "").strip())
        prompt = str(item.get("prompt") or "").strip()
        if role_id and prompt:
            presets.append(
                {
                    "id": preset_id,
                    "name": name,
                    "role_id": role_id,
                    "prompt": prompt,
                    "created_at": str(item.get("created_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                }
            )
            continue

        legacy_prompts = item.get("prompts") if isinstance(item.get("prompts"), dict) else {}
        if not legacy_prompts:
            continue

        needs_migration = True
        for legacy_mode in sorted(_LEGACY_MODES):
            legacy_prompt = str(legacy_prompts.get(legacy_mode) or "").strip()
            if not legacy_prompt:
                continue
            normalized_role_id = _ensure_role_id(legacy_mode)
            presets.append(
                {
                    "id": f"{preset_id}:{normalized_role_id}",
                    "name": f"{name} / {normalized_role_id}",
                    "role_id": normalized_role_id,
                    "prompt": legacy_prompt,
                    "created_at": str(item.get("created_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                }
            )

    if needs_migration:
        await _save_system_prompt_presets(presets)

    return presets


async def _save_system_prompt_presets(presets: list[dict]) -> None:
    await storage.set_setting(
        _SYSTEM_PROMPT_PRESETS_KEY,
        json.dumps(presets, ensure_ascii=False),
    )


@router.get("/settings/roles")
async def list_roles() -> dict:
    rows = await storage.list_roles()
    return {"roles": [_normalize_role_row(row) for row in rows]}


@router.post("/settings/roles")
async def create_role(request: RoleCreateRequest) -> dict:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="角色名称不能为空")

    capabilities, chat_capabilities, agent_preflight, agent_allowed_tools = _resolve_policy_fields_for_create(request)
    role = await storage.create_role(
        name=name,
        icon=request.icon.strip() or "🤖",
        description=request.description.strip(),
        system_prompt=request.system_prompt.strip(),
        agent_prompt=request.agent_prompt.strip(),
        capabilities=capabilities,
        chat_capabilities=chat_capabilities,
        agent_preflight=agent_preflight,
        allowed_surfaces=_validate_allowed_surfaces(request.allowed_surfaces),
        agent_allowed_tools=agent_allowed_tools,
    )
    return {"role": _normalize_role_row(role), "message": f"角色 '{name}' 已创建"}


@router.put("/settings/roles/{role_id}")
async def update_role(role_id: str, request: RoleUpdateRequest) -> dict:
    existing = await storage.get_role(role_id)
    if not existing:
        raise HTTPException(status_code=404, detail="角色不存在")

    updates: dict = {}
    if request.name is not None:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="角色名称不能为空")
        updates["name"] = name
    if request.icon is not None:
        updates["icon"] = request.icon.strip() or "🤖"
    if request.description is not None:
        updates["description"] = request.description.strip()
    if request.system_prompt is not None:
        updates["system_prompt"] = request.system_prompt.strip()
    if request.agent_prompt is not None:
        updates["agent_prompt"] = request.agent_prompt.strip()
    if request.allowed_surfaces is not None:
        updates["allowed_surfaces"] = _validate_allowed_surfaces(request.allowed_surfaces)
    if request.sort_order is not None:
        updates["sort_order"] = request.sort_order

    if any(
        value is not None
        for value in (
            request.capabilities,
            request.chat_capabilities,
            request.agent_preflight,
            request.agent_allowed_tools,
        )
    ):
        capabilities, chat_capabilities, agent_preflight, agent_allowed_tools = _resolve_policy_fields_for_update(
            existing,
            request,
        )
        updates["capabilities"] = capabilities
        updates["chat_capabilities"] = chat_capabilities
        updates["agent_preflight"] = agent_preflight
        updates["agent_allowed_tools"] = agent_allowed_tools

    updated = await storage.update_role(role_id, **updates)
    return {"role": _normalize_role_row(updated or existing), "message": "角色已更新"}


@router.delete("/settings/roles/{role_id}")
async def delete_role(role_id: str) -> dict:
    try:
        deleted = await storage.delete_role(role_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail="角色不存在")
    return {"id": role_id, "message": "角色已删除"}


@router.get("/settings/system-prompt/{role_id}")
async def get_system_prompt(role_id: str) -> dict:
    normalized_role_id = _ensure_role_id(role_id)
    prompt, is_custom = await _get_prompt(normalized_role_id)
    return {
        "role_id": normalized_role_id,
        "prompt": prompt,
        "default_prompt": _builtin_default_prompt(normalized_role_id),
        "is_custom": is_custom,
        "resolved_prompt": prompt,
    }


@router.put("/settings/system-prompt/{role_id}")
async def update_system_prompt(role_id: str, request: SystemPromptRequest) -> dict:
    normalized_role_id = _ensure_role_id(role_id)
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="System Prompt 不能为空")

    await storage.set_setting(_settings_key(normalized_role_id), prompt)
    return {
        "role_id": normalized_role_id,
        "prompt": prompt,
        "default_prompt": _builtin_default_prompt(normalized_role_id),
        "resolved_prompt": prompt,
        "message": f"{normalized_role_id} 的 System Prompt 已保存",
    }


@router.delete("/settings/system-prompt/{role_id}")
async def reset_system_prompt(role_id: str) -> dict:
    normalized_role_id = _ensure_role_id(role_id)
    await storage.set_setting(_settings_key(normalized_role_id), "")
    prompt = await _role_default_prompt(normalized_role_id)
    return {
        "role_id": normalized_role_id,
        "prompt": prompt,
        "default_prompt": _builtin_default_prompt(normalized_role_id),
        "resolved_prompt": prompt,
        "message": f"{normalized_role_id} 的 System Prompt 已恢复默认",
    }


@router.get("/settings/system-prompts")
async def get_system_prompts() -> dict:
    return await _get_prompt_bundle()


@router.put("/settings/system-prompts")
async def update_system_prompts(request: SystemPromptBundleRequest) -> dict:
    for role_id, prompt in request.prompts.items():
        normalized_role_id = _ensure_role_id(role_id)
        if normalized_role_id:
            await storage.set_setting(_settings_key(normalized_role_id), (prompt or "").strip())

    bundle = await _get_prompt_bundle()
    return {**bundle, "message": "System Prompts 已保存"}


@router.get("/settings/system-prompt-presets")
async def list_system_prompt_presets() -> dict:
    presets = await _load_system_prompt_presets()
    return {"presets": presets, "total": len(presets)}


@router.post("/settings/system-prompt-presets")
async def create_system_prompt_preset(request: SystemPromptPresetRequest) -> dict:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="预设名称不能为空")

    normalized_role_id = _ensure_role_id(request.role_id)
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="预设内容不能为空")

    presets = await _load_system_prompt_presets()
    now = utc_now_iso()
    preset = {
        "id": f"preset_{now}",
        "name": name,
        "role_id": normalized_role_id,
        "prompt": prompt,
        "created_at": now,
        "updated_at": now,
    }
    presets.insert(0, preset)
    await _save_system_prompt_presets(presets)
    return {"preset": preset, "message": f"预设“{name}”已保存"}


@router.delete("/settings/system-prompt-presets/{preset_id}")
async def delete_system_prompt_preset(preset_id: str) -> dict:
    presets = await _load_system_prompt_presets()
    remaining = [preset for preset in presets if preset["id"] != preset_id]
    if len(remaining) == len(presets):
        raise HTTPException(status_code=404, detail="预设不存在")

    await _save_system_prompt_presets(remaining)
    return {"id": preset_id, "message": "预设已删除"}


@router.get("/settings/embedding")
async def get_embedding_config() -> dict:
    api_url = await storage.get_setting(_EMB_URL_KEY, default="")
    api_key = await storage.get_setting(_EMB_KEY_KEY, default="")
    model = await storage.get_setting(_EMB_MODEL_KEY, default=_EMB_MODEL_DEFAULT)
    return {
        "api_url": api_url,
        "api_key": api_key,
        "model": model or _EMB_MODEL_DEFAULT,
        "is_configured": bool(api_url and api_key),
    }


@router.put("/settings/embedding")
async def update_embedding_config(request: EmbeddingConfigRequest) -> dict:
    await storage.set_setting(_EMB_URL_KEY, request.api_url.strip())
    await storage.set_setting(_EMB_KEY_KEY, request.api_key.strip())
    await storage.set_setting(_EMB_MODEL_KEY, request.model.strip() or _EMB_MODEL_DEFAULT)
    return {
        "message": "Embedding 配置已保存",
        "is_configured": bool(request.api_url.strip() and request.api_key.strip()),
    }


@router.delete("/settings/embedding")
async def reset_embedding_config() -> dict:
    await storage.set_setting(_EMB_URL_KEY, "")
    await storage.set_setting(_EMB_KEY_KEY, "")
    await storage.set_setting(_EMB_MODEL_KEY, "")
    return {"message": "Embedding 配置已清除"}


@router.post("/settings/embedding/test")
async def test_embedding_config(request: EmbeddingConfigRequest) -> dict:
    if not request.api_url.strip() or not request.api_key.strip():
        raise HTTPException(status_code=400, detail="请填写 API Base URL 和 API Key")

    url = request.api_url.rstrip("/") + "/embeddings"
    model = request.model.strip() or _EMB_MODEL_DEFAULT

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                json={"model": model, "input": ["连接测试"]},
                headers={
                    "Authorization": f"Bearer {request.api_key}",
                    "Content-Type": "application/json",
                },
            )

        if response.status_code == 200:
            data = response.json()
            dimension = len(data["data"][0]["embedding"]) if data.get("data") else 0
            return {
                "success": True,
                "message": f"连接成功，向量维度 {dimension}",
                "dimension": dimension,
            }

        detail = response.json().get("error", {}).get("message", response.text[:200])
        return {"success": False, "message": f"连接失败: {detail}"}
    except Exception as exc:  # pragma: no cover
        return {"success": False, "message": f"连接失败: {str(exc)}"}
