"""
认证与用户管理路由。

接口：
- POST /api/auth/login
- POST /api/auth/register
- GET  /api/auth/me
- GET  /api/auth/users
- PUT  /api/auth/users/{id}
- DELETE /api/auth/users/{id}
- GET  /api/auth/groups
- POST /api/auth/groups
- PUT  /api/auth/groups/{id}
- DELETE /api/auth/groups/{id}
- GET  /api/auth/grants
- POST /api/auth/grants
- DELETE /api/auth/grants/{id}
"""

from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from services.auth_service import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from services.storage import storage

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """从 JWT token 中解析当前用户。"""
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证令牌")

    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")

    user = await storage.get_user_by_id(payload["sub"])
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("system_role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def _is_default_admin(user: Optional[dict]) -> bool:
    return bool(user) and user.get("username") == "admin"


def _normalize_system_role(system_role: str) -> str:
    normalized = str(system_role or "").strip().lower()
    if normalized not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="system_role 仅支持 admin 或 user")
    return normalized


async def _normalize_group_id(group_id: Optional[str]) -> Optional[str]:
    normalized = str(group_id or "").strip() or None
    if normalized and not await storage.get_group_by_id(normalized):
        raise HTTPException(status_code=400, detail="指定的用户组不存在")
    return normalized


def _normalize_group_knowhow_manager(value: Optional[bool | int]) -> int:
    return 1 if bool(value) else 0


def _serialize_user(user: dict, *, include_is_active: bool = False) -> dict:
    payload = {
        "id": user.get("id"),
        "username": user.get("username"),
        "display_name": user.get("display_name"),
        "system_role": user.get("system_role"),
        "group_id": user.get("group_id"),
        "can_manage_group_knowhow": bool(user.get("can_manage_group_knowhow")),
        "login_count": int(user.get("login_count") or 0),
        "last_login_at": user.get("last_login_at"),
        "token_input_total": int(user.get("token_input_total") or 0),
        "token_output_total": int(user.get("token_output_total") or 0),
        "token_total": int(
            user.get("token_total")
            or (int(user.get("token_input_total") or 0) + int(user.get("token_output_total") or 0))
        ),
    }
    if include_is_active:
        payload["is_active"] = user.get("is_active")
    return payload


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    display_name: str
    password: str
    system_role: str = "user"
    group_id: Optional[str] = None
    can_manage_group_knowhow: bool = False


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    system_role: Optional[str] = None
    group_id: Optional[str] = None
    can_manage_group_knowhow: Optional[bool] = None
    is_active: Optional[int] = None
    password: Optional[str] = None


class CreateGroupRequest(BaseModel):
    name: str
    description: str = ""


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class SetGrantRequest(BaseModel):
    resource_type: str
    resource_id: str
    grant_type: str
    grantee_id: Optional[str] = None


@router.post("/auth/login")
async def login(req: LoginRequest):
    user = await storage.get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.get("is_active"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

    user = await storage.record_user_login(user["id"]) or user
    token = create_access_token(user["id"], user["username"], user["system_role"])
    return {
        "token": token,
        "user": _serialize_user(user),
    }


@router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    fresh_user = await storage.get_user_by_id_with_stats(user["id"])
    return _serialize_user(fresh_user or user)


@router.post("/auth/register", status_code=201)
async def register(req: RegisterRequest, _admin: dict = Depends(require_admin)):
    existing = await storage.get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")

    group_id = await _normalize_group_id(req.group_id)
    can_manage_group_knowhow = _normalize_group_knowhow_manager(req.can_manage_group_knowhow)
    if can_manage_group_knowhow and not group_id:
        raise HTTPException(status_code=400, detail="组内 Know-how 管理员必须先绑定用户组")

    user = await storage.create_user(
        req.username,
        req.display_name,
        hash_password(req.password),
        system_role=_normalize_system_role(req.system_role),
        group_id=group_id,
        can_manage_group_knowhow=bool(can_manage_group_knowhow),
    )
    return _serialize_user(user)


@router.get("/auth/users")
async def list_users(_admin: dict = Depends(require_admin)):
    return [_serialize_user(user, include_is_active=True) for user in await storage.list_users()]


@router.put("/auth/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, _admin: dict = Depends(require_admin)):
    existing_user = await storage.get_user_by_id(user_id)
    if not existing_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    updates = req.model_dump(exclude_none=True)
    if "password" in updates:
        updates["password_hash"] = hash_password(updates.pop("password"))
    if "system_role" in updates:
        updates["system_role"] = _normalize_system_role(str(updates["system_role"]))
        if _is_default_admin(existing_user) and updates["system_role"] != "admin":
            raise HTTPException(status_code=400, detail="默认 admin 账号不能降级")
    if "group_id" in updates:
        updates["group_id"] = await _normalize_group_id(updates.get("group_id"))
    if "can_manage_group_knowhow" in updates:
        updates["can_manage_group_knowhow"] = _normalize_group_knowhow_manager(
            updates.get("can_manage_group_knowhow")
        )

    effective_group_id = updates.get("group_id", existing_user.get("group_id"))
    effective_group_manager = updates.get(
        "can_manage_group_knowhow",
        existing_user.get("can_manage_group_knowhow"),
    )
    if effective_group_manager and not effective_group_id:
        raise HTTPException(status_code=400, detail="组内 Know-how 管理员必须绑定用户组")
    if not effective_group_id:
        updates["can_manage_group_knowhow"] = 0

    user = await storage.update_user(user_id, **updates)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _serialize_user(user, include_is_active=True)


@router.delete("/auth/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    target_user = await storage.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if _is_default_admin(target_user):
        raise HTTPException(status_code=400, detail="默认 admin 账号不能删除")
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    if not await storage.delete_user(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True}


@router.get("/auth/groups")
async def list_groups(_user: dict = Depends(get_current_user)):
    return await storage.list_groups()


@router.post("/auth/groups", status_code=201)
async def create_group(req: CreateGroupRequest, _admin: dict = Depends(require_admin)):
    name = str(req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="用户组名称不能为空")
    try:
        return await storage.create_group(name, str(req.description or "").strip())
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户组名称已存在") from exc


@router.put("/auth/groups/{group_id}")
async def update_group(group_id: str, req: UpdateGroupRequest, _admin: dict = Depends(require_admin)):
    updates = req.model_dump(exclude_none=True)
    if "name" in updates:
        updates["name"] = str(updates["name"] or "").strip()
        if not updates["name"]:
            raise HTTPException(status_code=400, detail="用户组名称不能为空")
    if "description" in updates:
        updates["description"] = str(updates["description"] or "").strip()
    try:
        group = await storage.update_group(group_id, **updates)
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="用户组名称已存在") from exc
    if not group:
        raise HTTPException(status_code=404, detail="用户组不存在")
    return group


@router.delete("/auth/groups/{group_id}")
async def delete_group(group_id: str, _admin: dict = Depends(require_admin)):
    if not await storage.delete_group(group_id):
        raise HTTPException(status_code=404, detail="用户组不存在")
    return {"ok": True}


@router.get("/auth/grants")
async def list_grants(
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    _admin: dict = Depends(require_admin),
):
    return await storage.list_access_grants(resource_type, resource_id)


@router.post("/auth/grants", status_code=201)
async def set_grant(req: SetGrantRequest, _admin: dict = Depends(require_admin)):
    try:
        return await storage.set_access_grant(
            req.resource_type,
            req.resource_id,
            req.grant_type,
            req.grantee_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/auth/grants/{grant_id}")
async def remove_grant(grant_id: str, _admin: dict = Depends(require_admin)):
    if not await storage.remove_access_grant(grant_id):
        raise HTTPException(status_code=404, detail="授权记录不存在")
    return {"ok": True}
