"""
Skill 管理路由 - PRD §10.1
GET    /api/skills              - 加载所有可用 Skill
GET    /api/skills/{id}         - 获取单个 Skill 详情
GET    /api/skills/{id}/content - 获取 Skill 原始 Markdown 内容
POST   /api/skills              - 保存新 Skill
PUT    /api/skills/{id}         - 更新已有 Skill 内容（内置 Skill 保存为用户版本）
DELETE /api/skills/{id}         - 物理删除 Skill（内置或用户自建均支持）
POST   /api/skills/match        - 匹配用户意图到 Skill
"""
import re
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.skill_manager import skill_manager, _USER_SKILLS_DIR, _BACKEND_SKILLS_DIR
from services.skill_matcher import skill_matcher

router = APIRouter()


class MatchRequest(BaseModel):
    """Skill 匹配请求"""
    query: str
    top_k: int = 3


class SaveSkillRequest(BaseModel):
    """保存 Skill 请求"""
    content: str  # Skill Markdown 原始内容
    filename: Optional[str] = None  # 可选文件名（不含扩展名），为空则从内容中提取


@router.get("/skills")
async def list_skills(builtin_only: bool = False) -> dict:
    """获取所有已加载的 Skill 列表"""
    skills = skill_manager.list_skills(builtin_only=builtin_only)
    return {
        "skills": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "keywords": s.keywords,
                "input_types": s.input_types,
                "is_builtin": s.is_builtin,
                "parameters": s.parameters,
            }
            for s in skills
        ],
        "total": len(skills),
    }


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str) -> dict:
    """获取单个 Skill 详情"""
    skill = skill_manager.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' 未找到")
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
        "is_builtin": skill.is_builtin,
        "source_path": skill.source_path,
    }


@router.get("/skills/{skill_id}/content")
async def get_skill_content(skill_id: str) -> dict:
    """获取 Skill 原始 Markdown 内容"""
    skill = skill_manager.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' 未找到")
    if not skill.source_path:
        raise HTTPException(status_code=404, detail="Skill 源文件路径未知")
    source = Path(skill.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Skill 源文件不存在")
    content = source.read_text(encoding="utf-8")
    return {"id": skill.id, "content": content, "source_path": skill.source_path, "is_builtin": skill.is_builtin}


def _slugify(name: str) -> str:
    """将 Skill 名称转换为文件名安全的 slug"""
    # 保留中文、字母、数字、连字符
    slug = re.sub(r'[^\w\u4e00-\u9fff-]', '-', name)
    slug = re.sub(r'-+', '-', slug).strip('-').lower()
    return slug or 'unnamed-skill'


@router.post("/skills")
async def save_skill(request: SaveSkillRequest) -> dict:
    """保存新的 Skill 文件到用户自建目录"""
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Skill 内容不能为空")

    # 从内容中提取 Skill 名称
    title_match = re.search(r"^#\s+Skill:\s*(.+)$", content, re.MULTILINE)
    skill_name = title_match.group(1).strip() if title_match else "未命名技能"

    # 确定文件名
    if request.filename:
        slug = request.filename.replace(".skill.md", "").replace(".skill", "")
    else:
        slug = _slugify(skill_name)

    # 确保用户目录存在
    _USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = _USER_SKILLS_DIR / f"{slug}.skill.md"

    # 写入文件
    file_path.write_text(content, encoding="utf-8")

    # 重新加载 Skill 列表
    await skill_manager.reload()

    # 获取新解析的 Skill 信息
    skill = skill_manager.get_skill(slug)
    return {
        "id": slug,
        "name": skill.name if skill else skill_name,
        "message": f"Skill '{skill_name}' 已保存",
        "source_path": str(file_path),
    }


@router.put("/skills/{skill_id}")
async def update_skill(skill_id: str, request: SaveSkillRequest) -> dict:
    """更新已有的 Skill 文件；内置 Skill 将在用户目录创建覆盖版本（Copy-on-Write）"""
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Skill 内容不能为空")

    skill = skill_manager.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' 未找到")

    if skill.is_builtin:
        # 内置 Skill：将修改后的版本保存到用户目录，不修改内置文件
        _USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        original_name = Path(skill.source_path).name if skill.source_path else f"{skill_id}.skill.md"
        target = _USER_SKILLS_DIR / original_name
        target.write_text(content, encoding="utf-8")
        await skill_manager.reload()
        updated = skill_manager.get_skill(skill_id)
        return {
            "id": skill_id,
            "name": updated.name if updated else skill_id,
            "message": f"Skill '{skill_id}' 已保存为用户版本（覆盖内置）",
        }

    if not skill.source_path:
        raise HTTPException(status_code=404, detail="Skill 源文件路径未知")

    source = Path(skill.source_path)
    source.write_text(content, encoding="utf-8")

    # 重新加载
    await skill_manager.reload()

    updated = skill_manager.get_skill(skill_id)
    return {
        "id": skill_id,
        "name": updated.name if updated else skill_id,
        "message": f"Skill '{skill_id}' 已更新",
    }


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str) -> dict:
    """
    删除 Skill（物理删除，支持内置 Skill 和用户自建/覆盖 Skill）。

    逻辑：
    - 用户自建 Skill：删除用户目录下的文件。
    - 用户覆盖的内置 Skill：删除用户目录下的覆盖文件。
    - 纯内置 Skill：直接物理删除 backend/skills/builtin/ 下的原始文件。
    """
    skill = skill_manager.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' 未找到")
    if not skill.source_path:
        raise HTTPException(status_code=404, detail="Skill 源文件路径未知")

    source = Path(skill.source_path)

    # 安全校验：文件必须在用户目录或内置目录下，防止路径穿越
    source_resolved = source.resolve()
    in_user_dir = False
    in_builtin_dir = False
    try:
        source_resolved.relative_to(_USER_SKILLS_DIR.resolve())
        in_user_dir = True
    except ValueError:
        pass
    try:
        source_resolved.relative_to((_BACKEND_SKILLS_DIR / "builtin").resolve())
        in_builtin_dir = True
    except ValueError:
        pass

    if not in_user_dir and not in_builtin_dir:
        raise HTTPException(status_code=403, detail="Skill 文件不在允许的目录范围内，拒绝删除")

    if source.exists():
        source.unlink()

    await skill_manager.reload()
    return {"id": skill_id, "message": f"Skill '{skill_id}' 已删除"}


@router.post("/skills/match")
async def match_skill(request: MatchRequest) -> dict:
    """根据用户输入匹配最佳 Skill"""
    skills = skill_manager.list_skills()
    if not skills:
        return {"matches": [], "total": 0}

    results = skill_matcher.match(request.query, skills, top_k=request.top_k)
    return {
        "matches": [
            {
                "skill_id": r.skill.id,
                "skill_name": r.skill.name,
                "score": round(r.score, 3),
                "confidence": r.confidence,
                "match_type": r.match_type,
                "matched_keywords": r.matched_keywords,
            }
            for r in results
        ],
        "total": len(results),
    }

