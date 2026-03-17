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
from typing import List, Optional

from services.storage import storage

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
        self, category: Optional[str] = None, active_only: bool = True,
    ) -> List[dict]:
        """获取规则列表"""
        return await storage.list_knowhow_rules(category=category, active_only=active_only)

    async def add_rule(
        self, category: str, rule_text: str, weight: int = 2, source: str = "user",
    ) -> str:
        """添加新规则"""
        return await storage.add_knowhow_rule(category, rule_text, weight, source)

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
        # 提取中文关键短语（2-4字）
        keywords: List[str] = []
        # 常见采购相关关键词
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


# 全局单例
knowhow_service = KnowhowService()

