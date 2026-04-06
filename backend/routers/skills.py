"""
Skill 管理路由。

GET    /api/skills              - 加载所有可用 Skill
GET    /api/skills/{id}         - 获取单个 Skill 详情
GET    /api/skills/{id}/content - 获取 Skill 原始 Markdown 内容
POST   /api/skills              - 保存新 Skill
PUT    /api/skills/{id}         - 更新已有 Skill 内容
DELETE /api/skills/{id}         - 删除 Skill
POST   /api/skills/match        - 匹配用户意图到 Skill
"""

import re
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.access_control import filter_accessible_skills, get_accessible_skill
from services.skill_manager import _BACKEND_SKILLS_DIR, _USER_SKILLS_DIR, skill_manager
from services.skill_matcher import skill_matcher
from services.storage import storage
from routers.auth import get_current_user
from utils.text_utils import slugify_preserving_han

router = APIRouter()


class MatchRequest(BaseModel):
    query: str
    top_k: int = 3


class SaveSkillRequest(BaseModel):
    content: str
    filename: Optional[str] = None


def _serialize_skill_summary(skill) -> dict:
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "keywords": skill.keywords,
        "input_types": skill.input_types,
        "is_builtin": skill.is_builtin,
        "parameters": skill.parameters,
        "execution_profile": asdict(skill.execution_profile),
    }


def _serialize_skill_detail(skill) -> dict:
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "keywords": skill.keywords,
        "input_types": skill.input_types,
        "parameters": skill.parameters,
        "steps": skill.steps,
        "dependencies": skill.dependencies,
        "output_template": skill.output_template,
        "execution_profile": asdict(skill.execution_profile),
        "is_builtin": skill.is_builtin,
        "source_path": skill.source_path,
    }


async def _resolve_skill_for_user(skill_id: str, user: object):
    if isinstance(user, dict):
        return await get_accessible_skill(skill_id, user)
    return skill_manager.get_skill(skill_id)


@router.get("/skills")
async def list_skills(builtin_only: bool = False, user: dict = Depends(get_current_user)) -> dict:
    skills = skill_manager.list_skills(builtin_only=builtin_only)
    if isinstance(user, dict):
        skills = await filter_accessible_skills(skills, user)
    return {
        "skills": [_serialize_skill_summary(skill) for skill in skills],
        "total": len(skills),
    }


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, user: dict = Depends(get_current_user)) -> dict:
    skill = await _resolve_skill_for_user(skill_id, user)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill “{skill_id}”未找到")
    return _serialize_skill_detail(skill)


@router.get("/skills/{skill_id}/content")
async def get_skill_content(skill_id: str, user: dict = Depends(get_current_user)) -> dict:
    skill = await _resolve_skill_for_user(skill_id, user)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill “{skill_id}”未找到")
    if not skill.source_path:
        raise HTTPException(status_code=404, detail="Skill 源文件路径未知")

    source = Path(skill.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Skill 源文件不存在")

    content = source.read_text(encoding="utf-8")
    return {
        "id": skill.id,
        "content": content,
        "source_path": skill.source_path,
        "is_builtin": skill.is_builtin,
    }


def _slugify(name: str) -> str:
    return slugify_preserving_han(name)


@router.post("/skills")
async def save_skill(request: SaveSkillRequest, user: dict = Depends(get_current_user)) -> dict:
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Skill 内容不能为空")

    title_match = re.search(r"^#\s+Skill:\s*(.+)$", content, re.MULTILINE)
    skill_name = title_match.group(1).strip() if title_match else "未命名技能"

    if request.filename:
        slug = request.filename.replace(".skill.md", "").replace(".skill", "")
    else:
        slug = _slugify(skill_name)

    _USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = _USER_SKILLS_DIR / f"{slug}.skill.md"
    file_path.write_text(content, encoding="utf-8")

    await skill_manager.reload()
    skill = skill_manager.get_skill(slug)
    if isinstance(user, dict) and skill and not skill.is_builtin:
        await storage.upsert_skill_metadata(skill.id, user["id"])
    return {
        "id": slug,
        "name": skill.name if skill else skill_name,
        "message": f"Skill “{skill_name}”已保存",
        "source_path": str(file_path),
    }


@router.put("/skills/{skill_id}")
async def update_skill(skill_id: str, request: SaveSkillRequest, user: dict = Depends(get_current_user)) -> dict:
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Skill 内容不能为空")

    skill = await _resolve_skill_for_user(skill_id, user)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill “{skill_id}”未找到")

    if skill.is_builtin:
        _USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        original_name = Path(skill.source_path).name if skill.source_path else f"{skill_id}.skill.md"
        target = _USER_SKILLS_DIR / original_name
        target.write_text(content, encoding="utf-8")
        await skill_manager.clear_builtin_deleted(skill_id)
        await skill_manager.reload()
        updated = skill_manager.get_skill(skill_id)
        if isinstance(user, dict) and updated and not updated.is_builtin:
            await storage.upsert_skill_metadata(updated.id, user["id"])
        return {
            "id": skill_id,
            "name": updated.name if updated else skill_id,
            "message": f"Skill “{skill_id}”已保存为用户版本（覆盖内置）",
        }

    if not skill.source_path:
        raise HTTPException(status_code=404, detail="Skill 源文件路径未知")

    source = Path(skill.source_path)
    source.write_text(content, encoding="utf-8")
    await skill_manager.reload()

    updated = skill_manager.get_skill(skill_id)
    if isinstance(user, dict) and updated and not updated.is_builtin:
        await storage.upsert_skill_metadata(updated.id, user["id"])
    return {
        "id": skill_id,
        "name": updated.name if updated else skill_id,
        "message": f"Skill “{skill_id}”已更新",
    }


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, user: dict = Depends(get_current_user)) -> dict:
    """
    删除 Skill。

    逻辑：
    - 用户自建 Skill：物理删除用户目录下的文件。
    - 用户覆盖的内置 Skill：删除用户目录下的覆盖文件，并写入墓碑隐藏内置版。
    - 纯内置 Skill：仅写入墓碑隐藏，不修改内置源文件。
    """
    skill = await _resolve_skill_for_user(skill_id, user)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill “{skill_id}”未找到")
    if not skill.source_path:
        raise HTTPException(status_code=404, detail="Skill 源文件路径未知")

    source = Path(skill.source_path)
    source_resolved = source.resolve()
    user_dir = _USER_SKILLS_DIR.resolve()
    builtin_dir = (_BACKEND_SKILLS_DIR / "builtin").resolve()

    in_user_dir = False
    in_builtin_dir = False
    try:
        source_resolved.relative_to(user_dir)
        in_user_dir = True
    except ValueError:
        pass
    try:
        source_resolved.relative_to(builtin_dir)
        in_builtin_dir = True
    except ValueError:
        pass

    if not in_user_dir and not in_builtin_dir:
        raise HTTPException(status_code=403, detail="Skill 文件不在允许的目录范围内，拒绝删除")

    builtin_shadow_exists = skill_manager.has_builtin_skill(skill_id)

    if in_builtin_dir:
        await skill_manager.mark_builtin_deleted(skill_id)
        await skill_manager.reload()
        if isinstance(user, dict):
            await storage.delete_skill_metadata(skill_id)
        return {
            "id": skill_id,
            "message": f"Skill “{skill_id}”已从列表隐藏（未修改内置源文件）",
            "deletion_mode": "builtin_tombstone",
        }

    if source.exists():
        source.unlink()

    if builtin_shadow_exists:
        await skill_manager.mark_builtin_deleted(skill_id)
        message = f"Skill “{skill_id}”已删除用户版本，并隐藏内置版本"
        deletion_mode = "user_delete_and_builtin_tombstone"
    else:
        await skill_manager.clear_builtin_deleted(skill_id)
        message = f"Skill “{skill_id}”已删除"
        deletion_mode = "user_delete"

    await skill_manager.reload()
    if isinstance(user, dict):
        await storage.delete_skill_metadata(skill_id)
    return {"id": skill_id, "message": message, "deletion_mode": deletion_mode}


@router.post("/skills/match")
async def match_skill(request: MatchRequest, user: dict = Depends(get_current_user)) -> dict:
    skills = skill_manager.list_skills()
    if isinstance(user, dict):
        skills = await filter_accessible_skills(skills, user)
    if not skills:
        return {"matches": [], "total": 0}

    results = skill_matcher.match(request.query, skills, top_k=request.top_k)
    return {
        "matches": [
            {
                "skill_id": result.skill.id,
                "skill_name": result.skill.name,
                "score": round(result.score, 3),
                "confidence": result.confidence,
                "match_type": result.match_type,
                "matched_keywords": result.matched_keywords,
            }
            for result in results
        ],
        "total": len(results),
    }
