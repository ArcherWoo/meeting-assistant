from typing import Optional

from services.skill_manager import skill_manager
from services.storage import storage


def is_admin(user: Optional[dict]) -> bool:
    return isinstance(user, dict) and user.get("system_role") == "admin"


def _user_id(user: Optional[dict]) -> str:
    if not isinstance(user, dict):
        return ""
    return str(user.get("id") or "").strip()


def _group_id(user: Optional[dict]) -> str:
    if not isinstance(user, dict):
        return ""
    return str(user.get("group_id") or "").strip()


async def has_access_grant(resource_type: str, resource_id: str, user: Optional[dict]) -> bool:
    if not resource_id:
        return False

    grants = await storage.list_access_grants(resource_type=resource_type, resource_id=resource_id)
    if not grants:
        return False

    user_id = _user_id(user)
    group_id = _group_id(user)
    for grant in grants:
        grant_type = str(grant.get("grant_type") or "").strip()
        grantee_id = str(grant.get("grantee_id") or "").strip()
        if grant_type == "public":
            return True
        if grant_type == "user" and user_id and grantee_id == user_id:
            return True
        if grant_type == "group" and group_id and grantee_id == group_id:
            return True

    return False


async def can_access_role(role: Optional[dict], user: Optional[dict]) -> bool:
    if not role:
        return False

    if role.get("is_builtin") or is_admin(user):
        return True

    if not isinstance(user, dict):
        return False

    user_id = _user_id(user)
    if user_id and str(role.get("owner_id") or "").strip() == user_id:
        return True

    return await has_access_grant("role", str(role.get("id") or ""), user)


async def get_accessible_role(role_id: str, user: Optional[dict]) -> Optional[dict]:
    role = await storage.get_role(role_id)
    if not role:
        return None
    if await can_access_role(role, user):
        return role
    return None


def _skill_id(skill) -> str:
    if isinstance(skill, dict):
        return str(skill.get("id") or skill.get("skill_id") or "").strip()
    return str(getattr(skill, "id", "") or "").strip()


def _skill_is_builtin(skill) -> bool:
    if isinstance(skill, dict):
        return bool(skill.get("is_builtin"))
    return bool(getattr(skill, "is_builtin", False))


async def can_access_skill(skill, user: Optional[dict]) -> bool:
    if not skill:
        return False

    skill_id = _skill_id(skill)
    if not skill_id:
        return False

    if not skill_manager._loaded:
        await skill_manager.initialize()

    if _skill_is_builtin(skill) or skill_manager.has_builtin_skill(skill_id) or is_admin(user):
        return True

    try:
        metadata = await storage.get_skill_metadata(skill_id)
    except RuntimeError:
        metadata = None
    if not metadata:
        # 兼容历史自定义 Skill：未写入元数据时继续保持公开可见。
        return True

    owner_id = str(metadata.get("owner_id") or "").strip()
    if not owner_id:
        return True

    user_id = _user_id(user)
    if user_id and owner_id == user_id:
        return True

    return await has_access_grant("skill", skill_id, user)


async def get_accessible_skill(skill_id: str, user: Optional[dict]):
    if not skill_manager._loaded:
        await skill_manager.initialize()
    skill = skill_manager.get_skill(skill_id)
    if not skill:
        return None
    if await can_access_skill(skill, user):
        return skill
    return None


async def filter_accessible_skills(skills: list, user: Optional[dict]) -> list:
    visible: list = []
    for skill in skills:
        if await can_access_skill(skill, user):
            visible.append(skill)
    return visible
