from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, Field

from services.storage import storage


_LLM_PROFILES_KEY = "llm_profiles"
_ACTIVE_LLM_PROFILE_ID_KEY = "active_llm_profile_id"


class StoredLLMProfile(BaseModel):
    id: str
    name: str
    api_url: str
    api_key: str
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = True
    available_models: list[str] = Field(default_factory=list)


def _normalize_profile_payload(item: dict[str, Any], index: int) -> StoredLLMProfile:
    available_models = item.get("available_models")
    if not isinstance(available_models, list):
        available_models = []

    return StoredLLMProfile(
        id=str(item.get("id") or uuid.uuid4()),
        name=str(item.get("name") or "").strip() or f"模型 {index + 1}",
        api_url=str(item.get("api_url") or "").strip(),
        api_key=str(item.get("api_key") or "").strip(),
        model=str(item.get("model") or "gpt-4o").strip() or "gpt-4o",
        temperature=float(item.get("temperature", 0.7) or 0.7),
        max_tokens=int(item.get("max_tokens", 4096) or 4096),
        stream=bool(item.get("stream", True)),
        available_models=[
            str(model_name).strip()
            for model_name in available_models
            if str(model_name).strip()
        ],
    )


async def list_llm_profiles() -> list[StoredLLMProfile]:
    raw_value = await storage.get_setting(_LLM_PROFILES_KEY, default="")
    if not raw_value.strip():
        return []

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    profiles: list[StoredLLMProfile] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        try:
            profiles.append(_normalize_profile_payload(item, index))
        except Exception:
            continue
    return profiles


async def get_active_llm_profile_id() -> str:
    return (await storage.get_setting(_ACTIVE_LLM_PROFILE_ID_KEY, default="")).strip()


async def save_llm_profiles(profiles: list[StoredLLMProfile], active_profile_id: str = "") -> None:
    normalized_active_profile_id = active_profile_id.strip()
    await storage.set_setting(
        _LLM_PROFILES_KEY,
        json.dumps([profile.model_dump(mode="json") for profile in profiles], ensure_ascii=False),
    )
    await storage.set_setting(_ACTIVE_LLM_PROFILE_ID_KEY, normalized_active_profile_id)


async def resolve_llm_profile(profile_id: str | None = None) -> StoredLLMProfile | None:
    profiles = await list_llm_profiles()
    if not profiles:
        return None

    normalized_profile_id = (profile_id or "").strip()
    if normalized_profile_id:
        for profile in profiles:
            if profile.id == normalized_profile_id:
                return profile

    active_profile_id = await get_active_llm_profile_id()
    if active_profile_id:
        for profile in profiles:
            if profile.id == active_profile_id:
                return profile

    return profiles[0]


async def get_runtime_llm_config(
    *,
    profile_id: str | None = None,
    api_url: str = "",
    api_key: str = "",
    model: str = "",
) -> dict[str, Any]:
    resolved_profile = await resolve_llm_profile(profile_id)
    request_api_url = api_url.strip()
    request_api_key = api_key.strip()
    request_model = model.strip()

    effective_api_url = request_api_url
    effective_api_key = request_api_key
    effective_model = request_model or "gpt-4o"
    effective_profile_id = (profile_id or "").strip() or None

    if resolved_profile and (effective_profile_id or not request_api_key):
        effective_api_url = resolved_profile.api_url.strip()
        effective_api_key = resolved_profile.api_key.strip()
        effective_model = request_model or resolved_profile.model.strip() or "gpt-4o"
        effective_profile_id = resolved_profile.id

    return {
        "profile_id": effective_profile_id,
        "api_url": effective_api_url,
        "api_key": effective_api_key,
        "model": effective_model,
        "profile": resolved_profile,
    }


def serialize_llm_profile(profile: StoredLLMProfile, *, include_secret: bool = False) -> dict[str, Any]:
    payload = {
        "id": profile.id,
        "name": profile.name,
        "api_url": profile.api_url,
        "api_key": profile.api_key if include_secret else "",
        "has_api_key": bool(profile.api_key),
        "model": profile.model,
        "temperature": profile.temperature,
        "max_tokens": profile.max_tokens,
        "stream": profile.stream,
        "available_models": list(profile.available_models),
    }
    return payload
