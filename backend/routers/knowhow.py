"""
Know-how 规则路由 - PRD §5⅔.6
GET    /api/knowhow           - 获取规则列表
POST   /api/knowhow           - 添加新规则
PUT    /api/knowhow/{rule_id} - 更新规则
DELETE /api/knowhow/{rule_id} - 删除规则
GET    /api/knowhow/stats     - 规则统计
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.knowhow_service import knowhow_service

router = APIRouter()


class KnowhowRuleCreate(BaseModel):
    """创建规则请求"""
    category: str = "采购预审"
    rule_text: str
    weight: int = 2  # 1-3（⭐数）
    source: str = "user"


class KnowhowRuleUpdate(BaseModel):
    """更新规则请求"""
    category: Optional[str] = None
    rule_text: Optional[str] = None
    weight: Optional[int] = None
    is_active: Optional[int] = None


@router.get("/knowhow")
async def list_rules(
    category: Optional[str] = None,
    active_only: bool = False,
) -> dict:
    """获取所有 Know-how 规则，可按分类筛选"""
    rules = await knowhow_service.list_rules(
        category=category, active_only=active_only,
    )
    return {"rules": rules, "total": len(rules)}


@router.post("/knowhow")
async def add_rule(rule: KnowhowRuleCreate) -> dict:
    """添加新的 Know-how 规则"""
    if not rule.rule_text.strip():
        raise HTTPException(status_code=400, detail="规则内容不能为空")
    rule_id = await knowhow_service.add_rule(
        category=rule.category,
        rule_text=rule.rule_text,
        weight=rule.weight,
        source=rule.source,
    )
    return {"id": rule_id, "message": "规则已添加"}


@router.put("/knowhow/{rule_id}")
async def update_rule(rule_id: str, rule: KnowhowRuleUpdate) -> dict:
    """更新 Know-how 规则，返回更新后的完整规则对象"""
    updates = {k: v for k, v in rule.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    success = await knowhow_service.update_rule(rule_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="规则未找到或无有效更新")
    # 返回更新后的完整规则，方便前端直接刷新状态
    rules = await knowhow_service.list_rules(active_only=False)
    updated = next((r for r in rules if r["id"] == rule_id), None)
    if not updated:
        raise HTTPException(status_code=404, detail="规则更新后未找到")
    return updated


@router.delete("/knowhow/{rule_id}")
async def delete_rule(rule_id: str) -> dict:
    """删除 Know-how 规则"""
    await knowhow_service.delete_rule(rule_id)
    return {"message": "规则已删除"}


@router.get("/knowhow/stats")
async def get_stats() -> dict:
    """获取 Know-how 统计信息"""
    return await knowhow_service.get_stats()

