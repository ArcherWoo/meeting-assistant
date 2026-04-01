"""
Know-how 规则服务 - 业务经验规则管理与匹配
遵循 PRD §5⅔：让系统"越用越好用"，通过用户反馈沉淀业务知识

功能：
  - 规则 CRUD（增删改查）
  - 规则匹配检查（逐项检查 PPT 内容是否覆盖关注点）
  - 命中统计 + 置信度自动衰减
  - 内置默认采购预审关注点清单
"""
import logging
from datetime import datetime, timezone
from typing import Any, Literal, List, Optional

from services.storage import gen_id, storage

logger = logging.getLogger(__name__)

# 内置默认采购预审关注点（PRD §5½.4）
DEFAULT_PROCUREMENT_RULES: List[dict] = [
    {"category": "采购预审", "rule_text": "供应商必须提供 ISO 9001 质量管理体系认证或相关行业资质", "weight": 3, "source": "builtin"},
    {"category": "采购预审", "rule_text": "价格与历史同品类均价对比，偏差应在合理范围（±15%）内", "weight": 3, "source": "builtin"},
    {"category": "采购预审", "rule_text": "是否有与该供应商的历史合作记录及合作评价", "weight": 2, "source": "builtin"},
    {"category": "采购预审", "rule_text": "交付时间节点是否明确，有无里程碑和交付计划", "weight": 3, "source": "builtin"},
    {"category": "采购预审", "rule_text": "付款方式与条件是否合理（预付比例、验收付款、质保金等）", "weight": 2, "source": "builtin"},
    {"category": "采购预审", "rule_text": "是否包含违约条款（延迟交付、质量不合格的处罚）", "weight": 2, "source": "builtin"},
    {"category": "采购预审", "rule_text": "技术参数是否完整详细，能否满足实际需求", "weight": 2, "source": "builtin"},
    {"category": "采购预审", "rule_text": "是否有售后服务承诺（保修期、响应时间、备件供应）", "weight": 1, "source": "builtin"},
    {"category": "采购预审", "rule_text": "是否提供了竞品对比或多家供应商的对比分析", "weight": 1, "source": "builtin"},
    {"category": "采购预审", "rule_text": "是否进行了供应链风险评估和单一来源风险分析", "weight": 2, "source": "builtin"},
    {"category": "采购预审", "rule_text": "采购策略是否合理：Single Source 需有充分理由，是否考虑 Multi-Source", "weight": 3, "source": "builtin"},
    {"category": "采购预审", "rule_text": "采购流程是否合规：金额是否达招标门槛、审批流程是否完整、比价记录是否齐全", "weight": 3, "source": "builtin"},
]


class KnowhowService:
    """Know-how 规则管理与匹配服务"""

    async def ensure_defaults(self) -> int:
        """确保内置默认规则已初始化，返回新增数量"""
        existing = await storage.list_knowhow_rules(active_only=False)
        if existing:
            return 0
        count = 0
        for rule in DEFAULT_PROCUREMENT_RULES:
            await storage.add_knowhow_rule(
                category=rule["category"],
                rule_text=rule["rule_text"],
                weight=rule["weight"],
                source=rule["source"],
            )
            count += 1
        logger.info(f"已初始化 {count} 条默认 Know-how 规则")
        return count

    async def list_rules(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> List[dict]:
        """获取规则列表，支持 RBAC 过滤"""
        return await storage.list_knowhow_rules(
            category=category,
            active_only=active_only,
            user_id=user_id,
            group_id=group_id,
            is_admin=is_admin,
        )

    async def add_rule(
        self,
        category: str,
        rule_text: str,
        weight: int = 2,
        source: str = "user",
        owner_id: Optional[str] = None,
    ) -> str:
        """添加新规则"""
        return await storage.add_knowhow_rule(
            category,
            rule_text,
            weight,
            source,
            owner_id=owner_id,
        )

    async def update_rule(self, rule_id: str, updates: dict) -> bool:
        """更新规则字段"""
        allowed = {"category", "rule_text", "weight", "is_active"}
        sets = []
        params: list = []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return False
        sets.append("updated_at=?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(rule_id)
        await storage.db.execute(
            f"UPDATE knowhow_rules SET {', '.join(sets)} WHERE id=?", params,
        )
        await storage.db.commit()
        return True

    async def delete_rule(self, rule_id: str) -> bool:
        """删除规则"""
        await storage.db.execute("DELETE FROM knowhow_rules WHERE id=?", (rule_id,))
        await storage.db.commit()
        return True

    def _extract_import_rules(self, payload: Any) -> List[dict]:
        """从导入载荷中提取规则列表。"""
        if isinstance(payload, list):
            raw_rules = payload
        elif isinstance(payload, dict):
            raw_rules = payload.get("rules")
        else:
            raise ValueError("导入文件格式不正确")

        if not isinstance(raw_rules, list):
            raise ValueError("导入文件中缺少 rules 数组")

        rules = [self._normalize_import_rule(rule, index + 1) for index, rule in enumerate(raw_rules)]
        if not rules:
            raise ValueError("导入文件中没有可导入的规则")
        return rules

    @staticmethod
    def _normalize_import_rule(raw_rule: Any, index: int) -> dict:
        """标准化导入规则，兼容导出备份和手工维护的 JSON。"""
        if not isinstance(raw_rule, dict):
            raise ValueError(f"第 {index} 条规则格式不正确")

        category = str(raw_rule.get("category") or "").strip() or "未分类"
        rule_text = str(raw_rule.get("rule_text") or "").strip()
        if not rule_text:
            raise ValueError(f"第 {index} 条规则缺少内容")

        try:
            weight = round(float(raw_rule.get("weight", 2)), 1)
        except (TypeError, ValueError):
            weight = 2.0
        weight = max(0.0, min(5.0, weight))

        try:
            hit_count = max(0, int(raw_rule.get("hit_count", 0)))
        except (TypeError, ValueError):
            hit_count = 0

        try:
            confidence = float(raw_rule.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        source = str(raw_rule.get("source") or "imported").strip() or "imported"
        is_active_raw = raw_rule.get("is_active", 1)
        if isinstance(is_active_raw, str):
            is_active = 0 if is_active_raw.strip().lower() in {"0", "false", "no", "off"} else 1
        else:
            is_active = 1 if bool(is_active_raw) else 0

        now = datetime.now(timezone.utc).isoformat()
        created_at = str(raw_rule.get("created_at") or now)
        updated_at = str(raw_rule.get("updated_at") or created_at)

        return {
            "category": category,
            "rule_text": rule_text,
            "weight": weight,
            "hit_count": hit_count,
            "confidence": confidence,
            "source": source,
            "is_active": is_active,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    async def export_rules(self) -> dict:
        """导出当前 Know-how 规则库。"""
        rules = await storage.list_knowhow_rules(active_only=False)
        return {
            "kind": "knowhow_rules_export",
            "schema_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_rules": len(rules),
            "rules": rules,
        }

    async def import_rules(
        self,
        payload: Any,
        strategy: Literal["append", "replace"] = "append",
    ) -> dict:
        """导入 Know-how 规则库，支持追加或覆盖。"""
        if strategy not in {"append", "replace"}:
            raise ValueError("导入策略不支持")

        rules = self._extract_import_rules(payload)
        existing_rules = await storage.list_knowhow_rules(active_only=False)
        existing_keys = {
            (str(rule.get("category") or "").strip(), str(rule.get("rule_text") or "").strip())
            for rule in existing_rules
        }

        deleted_count = 0
        if strategy == "replace":
            cursor = await storage.db.execute("DELETE FROM knowhow_rules")
            deleted_count = max(cursor.rowcount, 0)
            existing_keys.clear()

        rows = []
        skipped_count = 0
        for rule in rules:
            key = (rule["category"], rule["rule_text"])
            if key in existing_keys:
                skipped_count += 1
                continue

            existing_keys.add(key)
            rows.append((
                gen_id(),
                rule["category"],
                rule["rule_text"],
                rule["weight"],
                rule["hit_count"],
                rule["confidence"],
                rule["source"],
                rule["is_active"],
                rule["created_at"],
                rule["updated_at"],
            ))

        if rows:
            await storage.db.executemany(
                "INSERT INTO knowhow_rules ("
                "id, category, rule_text, weight, hit_count, confidence, source, is_active, created_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        await storage.db.commit()

        total_after_import = len(await storage.list_knowhow_rules(active_only=False))
        return {
            "strategy": strategy,
            "total_in_file": len(rules),
            "imported_count": len(rows),
            "skipped_count": skipped_count,
            "deleted_count": deleted_count,
            "total_after_import": total_after_import,
        }

    async def check_against_content(
        self, content: str, category: str = "采购预审",
    ) -> List[dict]:
        """
        将 Know-how 规则逐项与内容匹配检查
        返回每条规则的覆盖情况: [{rule_id, rule_text, weight, covered: bool, detail: str}]
        注意：精准匹配需要 LLM，这里做基础关键词预匹配；Agent 执行时由 LLM 做最终判定
        """
        rules = await storage.list_knowhow_rules(category=category, active_only=True)
        content_lower = content.lower()
        results: List[dict] = []

        for rule in rules:
            rule_text = rule["rule_text"]
            # 基础关键词匹配（从规则中提取关键词）
            keywords = self._extract_keywords(rule_text)
            matched = sum(1 for kw in keywords if kw in content_lower)
            covered = matched >= max(1, len(keywords) // 3)

            results.append({
                "rule_id": rule["id"],
                "rule_text": rule_text,
                "weight": rule["weight"],
                "covered": covered,
                "match_score": matched / max(len(keywords), 1),
                "detail": f"匹配 {matched}/{len(keywords)} 个关键词" if keywords else "无法自动判定",
            })

            # 更新命中统计
            if covered:
                await storage.increment_knowhow_hit(rule["id"])

        return results

    def _extract_keywords(self, rule_text: str) -> List[str]:
        """从规则文本中提取关键词（简单分词）"""
        keywords: List[str] = []
        term_map = {
            "ISO": "iso", "认证": "认证", "资质": "资质", "供应商": "供应商",
            "价格": "价格", "均价": "均价", "偏差": "偏差",
            "合作": "合作", "历史": "历史",
            "交付": "交付", "里程碑": "里程碑", "时间": "时间",
            "付款": "付款", "预付": "预付", "质保": "质保",
            "违约": "违约", "处罚": "处罚",
            "技术参数": "技术参数", "规格": "规格",
            "售后": "售后", "保修": "保修",
            "竞品": "竞品", "对比": "对比", "比价": "比价",
            "风险": "风险", "评估": "评估",
            "招标": "招标", "审批": "审批", "合规": "合规",
            "单一来源": "单一来源", "multi-source": "multi-source",
        }
        rule_lower = rule_text.lower()
        for term, kw in term_map.items():
            if term.lower() in rule_lower:
                keywords.append(kw.lower())
        return keywords

    async def get_stats(self) -> dict:
        """获取 Know-how 统计"""
        all_rules = await storage.list_knowhow_rules(active_only=False)
        active = [r for r in all_rules if r.get("is_active")]
        categories = set(r["category"] for r in all_rules)
        total_hits = sum(r.get("hit_count", 0) for r in all_rules)
        return {
            "total_rules": len(all_rules),
            "active_rules": len(active),
            "categories": list(categories),
            "total_hits": total_hits,
        }

    async def list_categories(self) -> list[dict]:
        """获取所有分类及其规则数量"""
        all_rules = await storage.list_knowhow_rules(active_only=False)
        counts: dict[str, int] = {}
        for rule in all_rules:
            cat = rule["category"]
            counts[cat] = counts.get(cat, 0) + 1
        return [{"name": name, "rule_count": count} for name, count in sorted(counts.items())]

    async def rename_category(self, old_name: str, new_name: str) -> int:
        """批量将所有属于 old_name 分类的规则改为 new_name，返回受影响行数"""
        cursor = await storage.db.execute(
            "UPDATE knowhow_rules SET category=?, updated_at=? WHERE category=?",
            (new_name, datetime.now(timezone.utc).isoformat(), old_name),
        )
        await storage.db.commit()
        return cursor.rowcount

    async def delete_category(self, name: str, delete_rules: bool = True) -> int:
        """
        删除分类。
        delete_rules=True：连同该分类下所有规则一起删除（默认）。
        delete_rules=False：仅将规则的 category 清空（置为空字符串），保留规则本身。
        返回受影响行数。
        """
        if delete_rules:
            cursor = await storage.db.execute(
                "DELETE FROM knowhow_rules WHERE category=?", (name,)
            )
        else:
            cursor = await storage.db.execute(
                "UPDATE knowhow_rules SET category='', updated_at=? WHERE category=?",
                (datetime.now(timezone.utc).isoformat(), name),
            )
        await storage.db.commit()
        return cursor.rowcount


# 全局单例
knowhow_service = KnowhowService()
