"""
设置路由
GET  /api/settings/system-prompt/{mode}      - 获取指定模式的 System Prompt
PUT  /api/settings/system-prompt/{mode}      - 保存指定模式的 System Prompt
DELETE /api/settings/system-prompt/{mode}    - 重置指定模式的 System Prompt
GET  /api/settings/system-prompts            - 批量获取三种模式的 System Prompt
PUT  /api/settings/system-prompts            - 批量保存三种模式的 System Prompt
GET  /api/settings/system-prompt-presets     - 获取已保存的 System Prompt 预设
POST /api/settings/system-prompt-presets     - 保存一个 System Prompt 预设
DELETE /api/settings/system-prompt-presets/{id} - 删除一个 System Prompt 预设
GET  /api/settings/prompt-templates          - 获取提示词模板列表
POST /api/settings/prompt-templates          - 创建提示词模板
PUT  /api/settings/prompt-templates/{id}     - 更新提示词模板
DELETE /api/settings/prompt-templates/{id}   - 删除提示词模板
GET  /api/settings/prompt-config/{mode}      - 获取指定模式的模板挂载配置
PUT  /api/settings/prompt-config/{mode}      - 保存指定模式的模板挂载配置
DELETE /api/settings/prompt-config/{mode}    - 重置指定模式的模板挂载配置
GET  /api/settings/embedding                 - 获取 Embedding API 配置
PUT  /api/settings/embedding                 - 保存 Embedding API 配置
DELETE /api/settings/embedding               - 清除 Embedding API 配置
POST /api/settings/embedding/test            - 测试 Embedding 连通性
"""
import json
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.prompt_template_service import (
    DEFAULT_SYSTEM_PROMPTS,
    VALID_PROMPT_MODES,
    VALID_PROMPT_SCOPES,
    prompt_template_service,
)
from services.storage import storage, utc_now_iso

router = APIRouter()

VALID_MODES = VALID_PROMPT_MODES
_SYSTEM_PROMPT_PRESETS_KEY = "system_prompt_presets"


class SystemPromptRequest(BaseModel):
    prompt: str


class SystemPromptBundleRequest(BaseModel):
    prompts: dict[str, str] = Field(default_factory=dict)


class SystemPromptPresetRequest(BaseModel):
    name: str
    mode: str
    prompt: str


class PromptTemplateRequest(BaseModel):
    name: str
    description: str = ""
    scope: str = "global"
    content: str
    variables: dict[str, str] = Field(default_factory=dict)


class PromptTemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scope: Optional[str] = None
    content: Optional[str] = None
    variables: Optional[dict[str, str]] = None


class PromptConfigRequest(BaseModel):
    template_ids: list[str] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    extra_prompt: str = ""


class PromptPackApplyRequest(BaseModel):
    modes: list[str] = Field(default_factory=list)
    strategy: str = "append"


class EmbeddingConfigRequest(BaseModel):
    api_url: str = ""
    api_key: str = ""
    model: str = "text-embedding-3-small"


def _settings_key(mode: str) -> str:
    return f"system_prompt_{mode}"


def _ensure_mode(mode: str) -> str:
    normalized = (mode or "").strip()
    if normalized not in VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的模式：{mode}，可选值：{', '.join(sorted(VALID_MODES))}",
        )
    return normalized


def _default_prompt(mode: str) -> str:
    return DEFAULT_SYSTEM_PROMPTS.get(mode, "")


async def _get_prompt(mode: str) -> tuple[str, bool]:
    normalized_mode = _ensure_mode(mode)
    value = await storage.get_setting(_settings_key(normalized_mode), default="")
    if value:
        return value, True
    return _default_prompt(normalized_mode), False


async def _get_prompt_bundle() -> dict:
    prompts: dict[str, str] = {}
    defaults: dict[str, str] = {}
    custom_modes: list[str] = []
    for mode in sorted(VALID_MODES):
        prompt, is_custom = await _get_prompt(mode)
        prompts[mode] = prompt
        defaults[mode] = _default_prompt(mode)
        if is_custom:
            custom_modes.append(mode)
    return {
        "prompts": prompts,
        "defaults": defaults,
        "custom_modes": custom_modes,
    }


def _normalize_prompt_payload(prompts: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for mode in sorted(VALID_MODES):
        value = str(prompts.get(mode, "") or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail=f"{mode} 模式的 System Prompt 不能为空")
        normalized[mode] = value
    return normalized


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

        mode = str(item.get("mode") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if mode in VALID_MODES and prompt:
            presets.append({
                "id": preset_id,
                "name": name,
                "mode": mode,
                "prompt": prompt,
                "created_at": str(item.get("created_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            })
            continue

        prompts = item.get("prompts") if isinstance(item.get("prompts"), dict) else {}
        if prompts:
            needs_migration = True
            for legacy_mode in sorted(VALID_MODES):
                legacy_prompt = str(prompts.get(legacy_mode) or "").strip()
                if not legacy_prompt:
                    continue
                presets.append({
                    "id": f"{preset_id}:{legacy_mode}",
                    "name": f"{name} / {legacy_mode}",
                    "mode": legacy_mode,
                    "prompt": legacy_prompt,
                    "created_at": str(item.get("created_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                })

    if needs_migration:
        await _save_system_prompt_presets(presets)

    return presets


async def _save_system_prompt_presets(presets: list[dict]) -> None:
    await storage.set_setting(
        _SYSTEM_PROMPT_PRESETS_KEY,
        json.dumps(presets, ensure_ascii=False),
    )


@router.get("/settings/system-prompt/{mode}")
async def get_system_prompt(mode: str) -> dict:
    normalized_mode = _ensure_mode(mode)
    prompt, is_custom = await _get_prompt(normalized_mode)
    return {
        "mode": normalized_mode,
        "prompt": prompt,
        "is_custom": is_custom,
        "resolved_prompt": prompt,
        "template_ids": [],
        "missing_variables": [],
    }


@router.put("/settings/system-prompt/{mode}")
async def update_system_prompt(mode: str, request: SystemPromptRequest) -> dict:
    normalized_mode = _ensure_mode(mode)
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="System Prompt 不能为空")

    await storage.set_setting(_settings_key(normalized_mode), prompt)
    return {
        "mode": normalized_mode,
        "prompt": prompt,
        "resolved_prompt": prompt,
        "message": f"{normalized_mode} 模式的 System Prompt 已保存",
    }


@router.delete("/settings/system-prompt/{mode}")
async def reset_system_prompt(mode: str) -> dict:
    normalized_mode = _ensure_mode(mode)
    await storage.set_setting(_settings_key(normalized_mode), "")
    prompt = _default_prompt(normalized_mode)
    return {
        "mode": normalized_mode,
        "prompt": prompt,
        "resolved_prompt": prompt,
        "message": f"{normalized_mode} 模式的 System Prompt 已重置为默认值",
    }


@router.get("/settings/system-prompts")
async def get_system_prompts() -> dict:
    return await _get_prompt_bundle()


@router.put("/settings/system-prompts")
async def update_system_prompts(request: SystemPromptBundleRequest) -> dict:
    normalized_prompts = _normalize_prompt_payload(request.prompts)
    for mode, prompt in normalized_prompts.items():
        await storage.set_setting(_settings_key(mode), prompt)
    bundle = await _get_prompt_bundle()
    return {
        **bundle,
        "message": "System Prompts 已保存",
    }


@router.get("/settings/system-prompt-presets")
async def list_system_prompt_presets() -> dict:
    presets = await _load_system_prompt_presets()
    return {"presets": presets, "total": len(presets)}


@router.post("/settings/system-prompt-presets")
async def create_system_prompt_preset(request: SystemPromptPresetRequest) -> dict:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="预设名称不能为空")

    normalized_mode = _ensure_mode(request.mode)
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="预设内容不能为空")
    presets = await _load_system_prompt_presets()
    now = utc_now_iso()
    preset = {
        "id": f"preset_{now}",
        "name": name,
        "mode": normalized_mode,
        "prompt": prompt,
        "created_at": now,
        "updated_at": now,
    }
    presets.insert(0, preset)
    await _save_system_prompt_presets(presets)
    return {
        "preset": preset,
        "message": f"预设“{name}”已保存",
    }


@router.delete("/settings/system-prompt-presets/{preset_id}")
async def delete_system_prompt_preset(preset_id: str) -> dict:
    presets = await _load_system_prompt_presets()
    remaining = [preset for preset in presets if preset["id"] != preset_id]
    if len(remaining) == len(presets):
        raise HTTPException(status_code=404, detail="预设不存在")
    await _save_system_prompt_presets(remaining)
    return {"id": preset_id, "message": "预设已删除"}


@router.get("/settings/prompt-templates")
async def list_prompt_templates(scope: Optional[str] = None) -> dict:
    normalized_scope = None
    if scope is not None:
        normalized_scope = scope.strip()
        if normalized_scope not in VALID_PROMPT_SCOPES:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的作用域：{scope}，可选值：{', '.join(sorted(VALID_PROMPT_SCOPES))}",
            )

    templates = await prompt_template_service.list_templates(normalized_scope if normalized_scope and normalized_scope != "global" else normalized_scope)
    if normalized_scope == "global":
        templates = [template for template in templates if template["scope"] == "global"]
    return {"templates": templates, "total": len(templates)}


@router.get("/settings/prompt-packs")
async def list_prompt_packs() -> dict:
    packs = await prompt_template_service.list_builtin_packs()
    return {"packs": packs, "total": len(packs)}


@router.post("/settings/prompt-templates")
async def create_prompt_template(request: PromptTemplateRequest) -> dict:
    try:
        template = await prompt_template_service.create_template(
            name=request.name,
            description=request.description,
            scope=request.scope,
            content=request.content,
            variables=request.variables,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "template": template,
        "message": f"模板“{template['name']}”已创建",
    }


@router.put("/settings/prompt-templates/{template_id}")
async def update_prompt_template(template_id: str, request: PromptTemplateUpdateRequest) -> dict:
    try:
        template = await prompt_template_service.update_template(
            template_id,
            name=request.name,
            description=request.description,
            scope=request.scope,
            content=request.content,
            variables=request.variables,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "template": template,
        "message": f"模板“{template['name']}”已更新",
    }


@router.delete("/settings/prompt-templates/{template_id}")
async def delete_prompt_template(template_id: str) -> dict:
    try:
        await prompt_template_service.delete_template(template_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"id": template_id, "message": "模板已删除"}


@router.get("/settings/prompt-config/{mode}")
async def get_prompt_config(mode: str) -> dict:
    normalized_mode = _ensure_mode(mode)
    base_prompt = await storage.get_setting(_settings_key(normalized_mode), default="")
    if not base_prompt:
        base_prompt = DEFAULT_SYSTEM_PROMPTS.get(normalized_mode, "")
    return await prompt_template_service.resolve_mode_prompt(normalized_mode, base_prompt)


@router.put("/settings/prompt-config/{mode}")
async def update_prompt_config(mode: str, request: PromptConfigRequest) -> dict:
    normalized_mode = _ensure_mode(mode)
    try:
        await prompt_template_service.save_mode_config(
            normalized_mode,
            template_ids=request.template_ids,
            variables=request.variables,
            extra_prompt=request.extra_prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base_prompt = await storage.get_setting(_settings_key(normalized_mode), default="")
    if not base_prompt:
        base_prompt = DEFAULT_SYSTEM_PROMPTS.get(normalized_mode, "")

    resolved = await prompt_template_service.resolve_mode_prompt(normalized_mode, base_prompt)
    return {
        **resolved,
        "message": f"{normalized_mode} 模式的提示词挂载配置已保存",
    }


@router.post("/settings/prompt-packs/{pack_id}/apply")
async def apply_prompt_pack(pack_id: str, request: PromptPackApplyRequest) -> dict:
    try:
        result = await prompt_template_service.apply_builtin_pack(
            pack_id,
            modes=request.modes,
            strategy=request.strategy,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    result["message"] = "模板包已应用到所选模式"
    return result


@router.delete("/settings/prompt-config/{mode}")
async def reset_prompt_config(mode: str) -> dict:
    normalized_mode = _ensure_mode(mode)
    await prompt_template_service.reset_mode_config(normalized_mode)
    base_prompt = await storage.get_setting(_settings_key(normalized_mode), default="")
    if not base_prompt:
        base_prompt = DEFAULT_SYSTEM_PROMPTS.get(normalized_mode, "")

    resolved = await prompt_template_service.resolve_mode_prompt(normalized_mode, base_prompt)
    return {
        **resolved,
        "message": f"{normalized_mode} 模式的提示词挂载配置已重置",
    }


# ===== Embedding 配置 =====

_EMB_URL_KEY = "embedding_api_url"
_EMB_KEY_KEY = "embedding_api_key"
_EMB_MODEL_KEY = "embedding_model"
_EMB_MODEL_DEFAULT = "text-embedding-3-small"


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
            dim = len(data["data"][0]["embedding"]) if data.get("data") else 0
            return {"success": True, "message": f"连接成功，向量维度: {dim}", "dimension": dim}

        detail = response.json().get("error", {}).get("message", response.text[:200])
        return {"success": False, "message": f"连接失败: {detail}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}
