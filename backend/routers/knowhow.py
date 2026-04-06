"""
Know-how routes.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from routers.auth import get_current_user
from services.knowhow_service import knowhow_service

router = APIRouter()


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
    is_admin = user.get("system_role") == "admin"
    rules = await knowhow_service.list_rules(
        category=category,
        active_only=active_only,
        user_id=user["id"],
        group_id=user.get("group_id"),
        is_admin=is_admin,
    )
    return {"rules": rules, "total": len(rules)}


@router.post("/knowhow")
async def add_rule(rule: KnowhowRuleCreate, user: dict = Depends(get_current_user)) -> dict:
    if not rule.rule_text.strip():
        raise HTTPException(status_code=400, detail="规则内容不能为空")
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
    )
    return {"id": rule_id, "message": "规则已添加"}


@router.put("/knowhow/{rule_id}")
async def update_rule(rule_id: str, rule: KnowhowRuleUpdate, user: dict = Depends(get_current_user)) -> dict:
    updates = {key: value for key, value in rule.model_dump().items() if value is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    success = await knowhow_service.update_rule(rule_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="规则未找到或没有有效更新")
    rules = await knowhow_service.list_rules(active_only=False)
    updated = next((item for item in rules if item["id"] == rule_id), None)
    if not updated:
        raise HTTPException(status_code=404, detail="规则更新后未找到")
    return updated


@router.delete("/knowhow/{rule_id}")
async def delete_rule(rule_id: str, user: dict = Depends(get_current_user)) -> dict:
    await knowhow_service.delete_rule(rule_id)
    return {"message": "规则已删除"}


@router.get("/knowhow/stats")
async def get_stats(user: dict = Depends(get_current_user)) -> dict:
    return await knowhow_service.get_stats()


@router.get("/knowhow/export")
async def export_rules(user: dict = Depends(get_current_user)) -> JSONResponse:
    payload = await knowhow_service.export_rules()
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
    try:
        return await knowhow_service.import_rules(payload, strategy=strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/knowhow/categories")
async def list_categories(user: dict = Depends(get_current_user)) -> dict:
    categories = await knowhow_service.list_categories()
    return {"categories": categories, "total": len(categories)}


@router.post("/knowhow/categories")
async def create_category(body: CategoryCreateRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        category = await knowhow_service.create_category(
            name=body.name,
            description=body.description,
            aliases=body.aliases,
            example_queries=body.example_queries,
            applies_to=body.applies_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": f"分类“{category['name']}”已创建", "category": category}


@router.put("/knowhow/categories/{name}")
async def rename_category(name: str, body: CategoryRenameRequest, user: dict = Depends(get_current_user)) -> dict:
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="新分类名不能为空")
    if new_name == name:
        raise HTTPException(status_code=400, detail="新旧分类名相同，无需更改")
    affected = await knowhow_service.rename_category(name, new_name)
    return {"message": f"分类“{name}”已重命名为“{new_name}”", "affected_rules": affected}


@router.put("/knowhow/categories/{name}/profile")
async def update_category_profile(
    name: str,
    body: CategoryUpdateRequest,
    user: dict = Depends(get_current_user),
) -> dict:
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
    affected = await knowhow_service.delete_category(name, delete_rules=delete_rules)
    action = "已删除" if delete_rules else "已清空分类名"
    return {"message": f"分类“{name}”{action}，影响 {affected} 条规则", "affected_rules": affected}
