"""
Know-how routes.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from routers.auth import get_current_user
from services.access_control import (
    get_manageable_knowhow_rule,
    is_admin,
    is_group_knowhow_manager,
)
from services.knowhow_service import knowhow_service

router = APIRouter()


def _require_admin(user: dict) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可以执行此操作")


def _require_library_manager(user: dict) -> None:
    if is_admin(user) or is_group_knowhow_manager(user):
        return
    raise HTTPException(status_code=403, detail="没有规则库管理权限")


def _resolve_group_share(user: dict, share_to_group: Optional[bool]) -> Optional[str]:
    if not share_to_group:
        return None
    if not is_group_knowhow_manager(user):
        raise HTTPException(status_code=403, detail="当前用户不能将规则共享给所属用户组")
    group_id = str(user.get("group_id") or "").strip()
    if not group_id:
        raise HTTPException(status_code=400, detail="共享到用户组前需要先绑定用户组")
    return group_id


class KnowhowRuleCreate(BaseModel):
    category: str = "采购预审"
    title: str = ""
    rule_text: str
    trigger_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    applies_when: str = ""
    not_applies_when: str = ""
    examples: list[str] = Field(default_factory=list)
    weight: int = 2
    source: str = "user"
    share_to_group: bool = False


class KnowhowRuleUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    rule_text: Optional[str] = None
    trigger_terms: Optional[list[str]] = None
    exclude_terms: Optional[list[str]] = None
    applies_when: Optional[str] = None
    not_applies_when: Optional[str] = None
    examples: Optional[list[str]] = None
    weight: Optional[int] = None
    is_active: Optional[int] = None
    share_to_group: Optional[bool] = None


class CategoryCreateRequest(BaseModel):
    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    example_queries: list[str] = Field(default_factory=list)
    applies_to: str = ""


class CategoryUpdateRequest(BaseModel):
    description: Optional[str] = None
    aliases: Optional[list[str]] = None
    example_queries: Optional[list[str]] = None
    applies_to: Optional[str] = None


class CategoryRenameRequest(BaseModel):
    new_name: str


@router.get("/knowhow")
async def list_rules(
    category: Optional[str] = None,
    active_only: bool = False,
    user: dict = Depends(get_current_user),
) -> dict:
    admin = is_admin(user)
    rules = await knowhow_service.list_rules(
        category=category,
        active_only=active_only,
        user_id=user["id"],
        group_id=user.get("group_id"),
        is_admin=admin,
    )
    return {"rules": rules, "total": len(rules)}


@router.post("/knowhow")
async def add_rule(rule: KnowhowRuleCreate, user: dict = Depends(get_current_user)) -> dict:
    if not rule.rule_text.strip():
        raise HTTPException(status_code=400, detail="规则内容不能为空")

    owner_group_id = _resolve_group_share(user, rule.share_to_group)
    rule_id = await knowhow_service.add_rule(
        category=rule.category,
        title=rule.title,
        rule_text=rule.rule_text,
        trigger_terms=rule.trigger_terms,
        exclude_terms=rule.exclude_terms,
        applies_when=rule.applies_when,
        not_applies_when=rule.not_applies_when,
        examples=rule.examples,
        weight=rule.weight,
        source=rule.source,
        owner_id=user["id"],
        owner_group_id=owner_group_id,
    )
    return {"id": rule_id, "message": "规则已创建"}


@router.put("/knowhow/{rule_id}")
async def update_rule(rule_id: str, rule: KnowhowRuleUpdate, user: dict = Depends(get_current_user)) -> dict:
    updates = {key: value for key, value in rule.model_dump().items() if value is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    existing_rule = await knowhow_service.get_rule(rule_id)
    if not existing_rule:
        raise HTTPException(status_code=404, detail="规则未找到")
    existing = await get_manageable_knowhow_rule(rule_id, user)
    if not existing:
        raise HTTPException(status_code=403, detail="没有权限修改该规则")

    if "share_to_group" in updates:
        updates["owner_group_id"] = _resolve_group_share(user, updates.pop("share_to_group"))

    success = await knowhow_service.update_rule(rule_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="规则未找到或没有有效更新")

    updated = await knowhow_service.get_rule(rule_id)
    if not updated:
        raise HTTPException(status_code=404, detail="规则更新后未找到")
    return updated


@router.delete("/knowhow/{rule_id}")
async def delete_rule(rule_id: str, user: dict = Depends(get_current_user)) -> dict:
    existing_rule = await knowhow_service.get_rule(rule_id)
    if not existing_rule:
        raise HTTPException(status_code=404, detail="规则未找到")
    existing = await get_manageable_knowhow_rule(rule_id, user)
    if not existing:
        raise HTTPException(status_code=403, detail="没有权限删除该规则")
    await knowhow_service.delete_rule(rule_id)
    return {"message": "规则已删除"}


@router.get("/knowhow/stats")
async def get_stats(user: dict = Depends(get_current_user)) -> dict:
    return await knowhow_service.get_stats(
        user_id=user.get("id"),
        group_id=user.get("group_id"),
        is_admin=is_admin(user),
    )


@router.get("/knowhow/export")
async def export_rules(user: dict = Depends(get_current_user)) -> JSONResponse:
    if is_admin(user):
        payload = await knowhow_service.export_rules(is_admin=True)
    else:
        _require_library_manager(user)
        payload = await knowhow_service.export_rules(
            user_id=user.get("id"),
            group_id=user.get("group_id"),
            is_admin=False,
            group_manager_scope=True,
        )
    export_date = str(payload["exported_at"]).split("T", 1)[0]
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="knowhow-rules-{export_date}.json"'},
    )


@router.post("/knowhow/import")
async def import_rules(
    payload: Any = Body(...),
    strategy: Literal["append", "replace"] = "append",
    user: dict = Depends(get_current_user),
) -> dict:
    if is_admin(user):
        try:
            return await knowhow_service.import_rules(payload, strategy=strategy)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    _require_library_manager(user)
    if strategy != "append":
        raise HTTPException(status_code=403, detail="组内 Know-how 管理员只允许追加导入本组规则")
    try:
        return await knowhow_service.import_rules(
            payload,
            strategy="append",
            owner_id=user.get("id"),
            owner_group_id=user.get("group_id"),
            force_owner_scope=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/knowhow/categories")
async def list_categories(user: dict = Depends(get_current_user)) -> dict:
    categories = await knowhow_service.list_categories(
        user_id=user.get("id"),
        group_id=user.get("group_id"),
        is_admin=is_admin(user),
        manageable_group_id=user.get("group_id") if is_group_knowhow_manager(user) else None,
    )
    return {"categories": categories, "total": len(categories)}


@router.post("/knowhow/categories")
async def create_category(body: CategoryCreateRequest, user: dict = Depends(get_current_user)) -> dict:
    if not (is_admin(user) or is_group_knowhow_manager(user)):
        raise HTTPException(status_code=403, detail="没有分类管理权限")
    try:
        if is_admin(user):
            category = await knowhow_service.create_category(
                name=body.name,
                description=body.description,
                aliases=body.aliases,
                example_queries=body.example_queries,
                applies_to=body.applies_to,
            )
        else:
            category = await knowhow_service.create_category(name=body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": f"分类“{category['name']}”已创建", "category": category}


@router.put("/knowhow/categories/{name}")
async def rename_category(name: str, body: CategoryRenameRequest, user: dict = Depends(get_current_user)) -> dict:
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="新分类名称不能为空")
    if new_name == name:
        raise HTTPException(status_code=400, detail="新旧分类名相同，无需修改")
    try:
        if is_admin(user):
            affected = await knowhow_service.rename_category(name, new_name)
        elif is_group_knowhow_manager(user):
            affected = await knowhow_service.rename_category_for_group(
                name,
                new_name,
                owner_group_id=str(user.get("group_id") or ""),
            )
        else:
            raise HTTPException(status_code=403, detail="没有分类管理权限")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"message": f"分类“{name}”已重命名为“{new_name}”", "affected_rules": affected}


@router.put("/knowhow/categories/{name}/profile")
async def update_category_profile(
    name: str,
    body: CategoryUpdateRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    _require_admin(user)
    updates = {key: value for key, value in body.model_dump().items() if value is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    try:
        category = await knowhow_service.update_category(name, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": f"分类画像“{name}”已更新", "category": category}


@router.delete("/knowhow/categories/{name}")
async def delete_category(name: str, delete_rules: bool = True, user: dict = Depends(get_current_user)) -> dict:
    try:
        if is_admin(user):
            affected = await knowhow_service.delete_category(name, delete_rules=delete_rules)
        elif is_group_knowhow_manager(user):
            affected = await knowhow_service.delete_category_for_group(
                name,
                owner_group_id=str(user.get("group_id") or ""),
                delete_rules=delete_rules,
            )
        else:
            raise HTTPException(status_code=403, detail="没有分类管理权限")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    action = "已删除" if delete_rules else "已清空分类名"
    return {"message": f"分类“{name}”{action}，影响 {affected} 条规则", "affected_rules": affected}
