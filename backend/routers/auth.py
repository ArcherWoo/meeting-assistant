"""
认证与用户管理路由
POST /api/auth/login       - 用户登录
POST /api/auth/register    - 注册新用户（仅管理员）
GET  /api/auth/me          - 获取当前用户信息
GET  /api/auth/users       - 用户列表（仅管理员）
PUT  /api/auth/users/{id}  - 更新用户（仅管理员）
DELETE /api/auth/users/{id} - 删除用户（仅管理员）
GET  /api/auth/groups      - 用户组列表
POST /api/auth/groups      - 创建用户组（仅管理员）
DELETE /api/auth/groups/{id} - 删除用户组（仅管理员）
GET  /api/auth/grants      - 访问授权列表
POST /api/auth/grants      - 设置访问授权（仅管理员）
DELETE /api/auth/grants/{id} - 删除访问授权（仅管理员）
"""
import logging
from typing import Optional

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

logger = logging.getLogger(__name__)
router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


# ===== 依赖项 =====

async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """从 JWT token 中解析当前用户，返回用户 dict"""
    if not creds:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证令牌")
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    user = await storage.get_user_by_id(payload["sub"])
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("system_role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


# ===== 请求模型 =====

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    display_name: str
    password: str
    system_role: str = "user"
    group_id: Optional[str] = None

class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    system_role: Optional[str] = None
    group_id: Optional[str] = None
    is_active: Optional[int] = None
    password: Optional[str] = None

class CreateGroupRequest(BaseModel):
    name: str
    description: str = ""

class SetGrantRequest(BaseModel):
    resource_type: str
    resource_id: str
    grant_type: str
    grantee_id: Optional[str] = None


# ===== 端点 =====

@router.post("/auth/login")
async def login(req: LoginRequest):
    user = await storage.get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.get("is_active"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已禁用")
    token = create_access_token(user["id"], user["username"], user["system_role"])
    return {
        "token": token,
        "user": {k: user[k] for k in ("id", "username", "display_name", "system_role", "group_id")},
    }


@router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return {k: user[k] for k in ("id", "username", "display_name", "system_role", "group_id")}


@router.post("/auth/register", status_code=201)
async def register(req: RegisterRequest, _admin: dict = Depends(require_admin)):
    existing = await storage.get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = await storage.create_user(
        req.username, req.display_name, hash_password(req.password),
        system_role=req.system_role, group_id=req.group_id,
    )
    return {k: user[k] for k in ("id", "username", "display_name", "system_role", "group_id")}


@router.get("/auth/users")
async def list_users(_admin: dict = Depends(require_admin)):
    return await storage.list_users()


@router.put("/auth/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, _admin: dict = Depends(require_admin)):
    updates = req.model_dump(exclude_none=True)
    if "password" in updates:
        updates["password_hash"] = hash_password(updates.pop("password"))
    user = await storage.update_user(user_id, **updates)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {k: user[k] for k in ("id", "username", "display_name", "system_role", "group_id", "is_active")}


@router.delete("/auth/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    if not await storage.delete_user(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True}


# ===== 用户组 =====

@router.get("/auth/groups")
async def list_groups(_user: dict = Depends(get_current_user)):
    return await storage.list_groups()

@router.post("/auth/groups", status_code=201)
async def create_group(req: CreateGroupRequest, _admin: dict = Depends(require_admin)):
    return await storage.create_group(req.name, req.description)

@router.delete("/auth/groups/{group_id}")
async def delete_group(group_id: str, _admin: dict = Depends(require_admin)):
    if not await storage.delete_group(group_id):
        raise HTTPException(status_code=404, detail="用户组不存在")
    return {"ok": True}


# ===== 访问授权 =====

@router.get("/auth/grants")
async def list_grants(resource_type: Optional[str] = None, resource_id: Optional[str] = None, _admin: dict = Depends(require_admin)):
    return await storage.list_access_grants(resource_type, resource_id)

@router.post("/auth/grants", status_code=201)
async def set_grant(req: SetGrantRequest, _admin: dict = Depends(require_admin)):
    return await storage.set_access_grant(req.resource_type, req.resource_id, req.grant_type, req.grantee_id)

@router.delete("/auth/grants/{grant_id}")
async def remove_grant(grant_id: str, _admin: dict = Depends(require_admin)):
    if not await storage.remove_access_grant(grant_id):
        raise HTTPException(status_code=404, detail="授权记录不存在")
    return {"ok": True}

