"""
Know-how 规则服务。

负责：
- 规则的增删改查
- 分类画像的增删改查
- 规则导入导出
- 基于内容的轻量匹配检查
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from services.storage import gen_id, storage
from utils.text_utils import contains_han_text, extract_han_segments

logger = logging.getLogger(__name__)

UNCATEGORIZED = "未分类"

DEFAULT_CATEGORY_PROFILES: dict[str, dict[str, Any]] = {
    "采购预审": {
        "description": "用于采购预审、供应商资质、报价合理性、付款条款、交付风险、单一来源与审批合规判断。",
        "aliases": ["采购审核", "采购评审", "供应商预审", "采购合规"],
        "example_queries": [
            "这个供应商资质是否齐全",
            "付款方式是否合理",
            "单一来源风险说明够不够",
            "采购流程是否合规",
        ],
        "applies_to": "采购、招投标、供应商准入、单一来源论证、合同前置审查",
    }
}

DEFAULT_PROCUREMENT_RULES: list[dict[str, Any]] = [
    {
        "category": "采购预审",
        "title": "供应商资质要求",
        "rule_text": "供应商必须提供 ISO 9001 质量管理体系认证或相关行业资质。",
        "trigger_terms": ["供应商资质", "ISO", "认证", "资格"],
        "examples": ["这个供应商缺少 ISO 认证还能继续吗"],
        "weight": 3,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "价格偏差判断",
        "rule_text": "价格与历史同品类均价对比，偏差应在合理范围内，异常偏差需要补充解释。",
        "trigger_terms": ["价格偏差", "均价", "报价", "偏差说明"],
        "examples": ["这次报价比历史均价高很多是否合理"],
        "weight": 3,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "历史合作记录",
        "rule_text": "需要核查与该供应商的历史合作记录及合作评价。",
        "trigger_terms": ["合作记录", "历史合作", "供应商评价"],
        "weight": 2,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "交付计划完整性",
        "rule_text": "交付时间节点应明确，并包含里程碑和交付计划。",
        "trigger_terms": ["交付", "里程碑", "交期"],
        "weight": 3,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "付款条款合理性",
        "rule_text": "付款方式与条件是否合理，需要关注预付比例、验收付款、质保金等安排。",
        "trigger_terms": ["付款方式", "预付款", "验收付款", "质保金"],
        "examples": ["30%预付款、70%验收后支付是否合理"],
        "weight": 2,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "违约条款完整性",
        "rule_text": "需要明确违约责任，包括延迟交付和质量不合格的处理方式。",
        "trigger_terms": ["违约", "延迟交付", "质量不合格"],
        "weight": 2,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "技术参数完整性",
        "rule_text": "技术参数应完整详细，并能够支撑实际需求。",
        "trigger_terms": ["技术参数", "规格", "参数完整"],
        "weight": 2,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "售后服务承诺",
        "rule_text": "需要明确售后服务承诺，包括保修期、响应时间和备件供应。",
        "trigger_terms": ["售后", "保修", "响应时间"],
        "weight": 1,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "竞品比价要求",
        "rule_text": "应提供竞品对比或多家供应商的比价分析。",
        "trigger_terms": ["比价", "竞品", "多家供应商"],
        "weight": 1,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "供应链与单一来源风险",
        "rule_text": "需要进行供应链风险评估和单一来源风险分析。",
        "trigger_terms": ["风险评估", "单一来源", "供应链风险"],
        "examples": ["单一来源风险是否已经说明充分"],
        "weight": 2,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "采购策略合理性",
        "rule_text": "采购策略是否合理，Single Source 需要有充分理由，并评估是否应考虑 Multi-Source。",
        "trigger_terms": ["single source", "multi-source", "采购策略"],
        "applies_when": "适用于单一来源、唯一供应商、采购策略合理性判断。",
        "examples": ["唯一供应商方案是否需要补充理由"],
        "weight": 3,
        "source": "builtin",
    },
    {
        "category": "采购预审",
        "title": "采购流程合规性",
        "rule_text": "采购流程应合规，需要核查招标门槛、审批流程和比价记录是否齐全。",
        "trigger_terms": ["审批流程", "招标门槛", "比价记录", "合规"],
        "examples": ["这个采购流程是否需要补审批材料"],
        "weight": 3,
        "source": "builtin",
    },
]


class KnowhowService:
    """Know-how 规则管理与检索支持服务。"""

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _normalize_list(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    raw_items = parsed if isinstance(parsed, list) else [parsed]
                except json.JSONDecodeError:
                    raw_items = [item.strip() for item in stripped.split(",")]
            else:
                raw_items = [item.strip() for item in stripped.split(",")]
        else:
            raw_items = []

        items: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = cls._normalize_text(item)
            if not text or text in seen:
                continue
            seen.add(text)
            items.append(text)
        return items

    @classmethod
    def _dump_list(cls, value: Any) -> str:
        return json.dumps(cls._normalize_list(value), ensure_ascii=False)

    @classmethod
    def _load_list(cls, value: Any) -> list[str]:
        return cls._normalize_list(value)

    @classmethod
    def _serialize_rule(cls, rule: dict) -> dict:
        serialized = dict(rule)
        serialized["category"] = cls._normalize_text(serialized.get("category")) or UNCATEGORIZED
        serialized["title"] = cls._normalize_text(serialized.get("title"))
        serialized["rule_text"] = cls._normalize_text(serialized.get("rule_text"))
        serialized["owner_group_id"] = cls._normalize_text(serialized.get("owner_group_id")) or None
        serialized["trigger_terms"] = cls._load_list(serialized.get("trigger_terms"))
        serialized["exclude_terms"] = cls._load_list(serialized.get("exclude_terms"))
        serialized["applies_when"] = cls._normalize_text(serialized.get("applies_when"))
        serialized["not_applies_when"] = cls._normalize_text(serialized.get("not_applies_when"))
        serialized["examples"] = cls._load_list(serialized.get("examples"))
        return serialized

    @classmethod
    def _serialize_category(
        cls,
        category: dict,
        rule_count: int = 0,
        manageable_rule_count: int = 0,
        can_manage: bool = False,
    ) -> dict:
        serialized = dict(category)
        serialized["name"] = cls._normalize_text(serialized.get("name"))
        serialized["description"] = cls._normalize_text(serialized.get("description"))
        serialized["aliases"] = cls._load_list(serialized.get("aliases"))
        serialized["example_queries"] = cls._load_list(serialized.get("example_queries"))
        serialized["applies_to"] = cls._normalize_text(serialized.get("applies_to"))
        serialized["rule_count"] = int(rule_count)
        serialized["manageable_rule_count"] = int(manageable_rule_count)
        serialized["can_manage"] = bool(can_manage)
        return serialized

    async def _sync_categories_from_rules(self) -> None:
        rules = await storage.list_knowhow_rules(active_only=False)
        category_names = {
            self._normalize_text(rule.get("category")) or UNCATEGORIZED
            for rule in rules
        }
        for name in category_names:
            defaults = DEFAULT_CATEGORY_PROFILES.get(name, {})
            await storage.ensure_knowhow_category(
                name,
                description=self._normalize_text(defaults.get("description")),
                aliases=self._dump_list(defaults.get("aliases")),
                example_queries=self._dump_list(defaults.get("example_queries")),
                applies_to=self._normalize_text(defaults.get("applies_to")),
            )

    async def ensure_defaults(self) -> int:
        existing = await storage.list_knowhow_rules(active_only=False)
        if existing:
            await self._sync_categories_from_rules()
            return 0

        count = 0
        for profile_name, profile in DEFAULT_CATEGORY_PROFILES.items():
            await storage.ensure_knowhow_category(
                profile_name,
                description=self._normalize_text(profile.get("description")),
                aliases=self._dump_list(profile.get("aliases")),
                example_queries=self._dump_list(profile.get("example_queries")),
                applies_to=self._normalize_text(profile.get("applies_to")),
            )

        for rule in DEFAULT_PROCUREMENT_RULES:
            await self.add_rule(
                category=rule["category"],
                title=rule.get("title", ""),
                rule_text=rule["rule_text"],
                trigger_terms=rule.get("trigger_terms"),
                exclude_terms=rule.get("exclude_terms"),
                applies_when=rule.get("applies_when", ""),
                not_applies_when=rule.get("not_applies_when", ""),
                examples=rule.get("examples"),
                weight=rule["weight"],
                source=rule["source"],
            )
            count += 1
        logger.info("Initialized %s default knowhow rules", count)
        return count
    @staticmethod
    def _contains_chinese(text: str) -> bool:
        return contains_han_text(text)

    @classmethod
    def _merge_unique_items(cls, *groups: Any, limit: int = 6) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for item in cls._normalize_list(group):
                key = item.casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= limit:
                    return merged
        return merged

    @classmethod
    def _normalize_weight(cls, value: Any, default: float = 2) -> float:
        try:
            normalized = round(float(value), 1)
        except (TypeError, ValueError):
            normalized = float(default)
        return max(0.0, min(5.0, normalized))

    @classmethod
    def _infer_title(cls, category: str, rule_text: str) -> str:
        text = cls._normalize_text(rule_text)
        lowered = text.lower()
        is_chinese = cls._contains_chinese(f"{category} {rule_text}")
        title_hints = [
            (("single source", "sole source", "单一来源", "唯一供应商"), "单一来源合规判断", "Single-source compliance check"),
            (("iso", "supplier", "qualification", "certification", "资质", "认证", "供应商"), "供应商资质要求", "Supplier qualification requirement"),
            (("payment", "advance", "milestone", "付款", "预付"), "付款条款检查", "Payment term check"),
            (("price", "quote", "quotation", "价格", "报价"), "价格合理性判断", "Price reasonableness check"),
            (("delivery", "milestone", "schedule", "交付", "里程碑"), "交付计划检查", "Delivery plan check"),
            (("contract", "penalty", "liability", "合同", "违约"), "合同条款检查", "Contract clause check"),
            (("support", "warranty", "service", "售后", "保修"), "售后服务要求", "After-sales support requirement"),
            (("specification", "technical", "parameter", "参数", "规格"), "技术参数检查", "Technical specification check"),
            (("compliance", "approval", "process", "合规", "审批"), "合规流程检查", "Compliance workflow check"),
        ]
        for terms, zh_title, en_title in title_hints:
            if any(term in lowered for term in terms):
                return zh_title if is_chinese else en_title

        first_sentence = re.split(r"[。！？?!\n;；]", text, maxsplit=1)[0].strip()
        if not first_sentence:
            return category.strip() or ("规则摘要" if is_chinese else "Rule summary")
        return first_sentence[:18] if is_chinese else " ".join(first_sentence.split()[:6]).strip()

    @classmethod
    def _extract_keywords(cls, rule_text: str) -> list[str]:
        text = cls._normalize_text(rule_text).lower()
        keywords: list[str] = []
        english_terms = [
            "iso",
            "supplier",
            "qualification",
            "certification",
            "price",
            "payment",
            "delivery",
            "milestone",
            "contract",
            "penalty",
            "support",
            "warranty",
            "specification",
            "compliance",
            "approval",
            "risk",
            "single source",
            "multi-source",
        ]
        for term in english_terms:
            if term in text:
                keywords.append(term)
        keywords.extend(extract_han_segments(cls._normalize_text(rule_text), min_length=2, max_length=8))
        return cls._merge_unique_items(keywords, limit=8)

    @classmethod
    def _infer_trigger_terms(cls, category: str, rule_text: str, title: str, current_terms: Any = None) -> list[str]:
        existing = cls._normalize_list(current_terms)
        if existing:
            return existing

        normalized_text = cls._normalize_text(f"{category} {title} {rule_text}")
        lowered_text = normalized_text.lower()
        hint_terms = [
            "single source", "multi-source", "iso", "supplier", "qualification", "certification",
            "price", "payment", "delivery", "milestone", "contract", "penalty", "risk", "compliance",
            "供应商", "资质", "资格", "认证", "价格", "报价", "付款", "预付",
            "交付", "里程碑", "合同", "违约", "风险", "合规", "审批",
            "售后", "保修", "参数", "规格", "单一来源",
        ]
        inferred = [term for term in hint_terms if term.lower() in lowered_text]
        inferred.extend(cls._extract_keywords(normalized_text))
        inferred.extend(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", lowered_text))
        inferred.extend(extract_han_segments(normalized_text, min_length=2, max_length=8))
        return cls._merge_unique_items(inferred, limit=6)

    @classmethod
    def _infer_applies_when(cls, category: str, trigger_terms: list[str], rule_text: str, current_value: str = "") -> str:
        existing = cls._normalize_text(current_value)
        if existing:
            return existing

        is_chinese = cls._contains_chinese(f"{category} {rule_text}")
        focus = ("、" if is_chinese else ", ").join(trigger_terms[:3])
        if not focus:
            focus = category or ("相关事项" if is_chinese else "related cases")
        if is_chinese:
            return f"当用户询问{focus}是否合理、合规或需要补充说明时适用。"
        return f"Use when the user asks whether {focus} is sufficient, compliant, or needs more support."

    @classmethod
    def _infer_examples(cls, category: str, trigger_terms: list[str], current_examples: Any = None) -> list[str]:
        existing = cls._normalize_list(current_examples)
        if existing:
            return existing

        seed = trigger_terms[0] if trigger_terms else (category or "rule")
        if cls._contains_chinese(f"{category} {' '.join(trigger_terms)}"):
            return [f"这个{seed}是否满足要求？"]
        return [f"Does this satisfy the {seed} requirement?"]

    @classmethod
    def _prepare_rule_fields(
        cls,
        *,
        category: str,
        rule_text: str,
        title: str = "",
        trigger_terms: Any = None,
        exclude_terms: Any = None,
        applies_when: str = "",
        not_applies_when: str = "",
        examples: Any = None,
    ) -> dict[str, Any]:
        normalized_category = cls._normalize_text(category) or UNCATEGORIZED
        normalized_rule_text = cls._normalize_text(rule_text)
        normalized_title = cls._normalize_text(title) or cls._infer_title(normalized_category, normalized_rule_text)
        normalized_trigger_terms = cls._infer_trigger_terms(
            normalized_category,
            normalized_rule_text,
            normalized_title,
            trigger_terms,
        )
        normalized_examples = cls._infer_examples(
            normalized_category,
            normalized_trigger_terms,
            examples,
        )
        return {
            "category": normalized_category,
            "title": normalized_title,
            "rule_text": normalized_rule_text,
            "trigger_terms": normalized_trigger_terms,
            "exclude_terms": cls._normalize_list(exclude_terms),
            "applies_when": cls._infer_applies_when(
                normalized_category,
                normalized_trigger_terms,
                normalized_rule_text,
                applies_when,
            ),
            "not_applies_when": cls._normalize_text(not_applies_when),
            "examples": normalized_examples,
        }

    async def _refresh_category_profile(self, category: str) -> None:
        normalized_category = self._normalize_text(category) or UNCATEGORIZED
        await storage.ensure_knowhow_category(normalized_category)
        categories = await storage.list_knowhow_categories()
        existing_row = next((item for item in categories if item.get("name") == normalized_category), {}) or {}
        existing = self._serialize_category(existing_row, 0)
        defaults = DEFAULT_CATEGORY_PROFILES.get(normalized_category, {})
        rules = await self.list_rules(category=normalized_category, active_only=False)

        inferred_terms: list[str] = []
        inferred_examples: list[str] = []
        for rule in rules:
            inferred_terms.extend(rule.get("trigger_terms") or [])
            inferred_terms.extend(self._extract_keywords(rule.get("rule_text", "")))
            inferred_examples.extend(rule.get("examples") or [])

        top_terms = self._merge_unique_items(inferred_terms, limit=4)
        merged_aliases = self._merge_unique_items(existing.get("aliases"), defaults.get("aliases"), top_terms, limit=6)
        merged_examples = self._merge_unique_items(
            existing.get("example_queries"),
            defaults.get("example_queries"),
            inferred_examples,
            limit=6,
        )

        if self._contains_chinese(normalized_category):
            zh_focus = "、".join(top_terms)
            zh_focus_short = "、".join(top_terms[:3])
            inferred_description = (
                f"适用于{normalized_category}相关判断，重点关注{zh_focus}。"
                if top_terms else f"适用于{normalized_category}相关判断。"
            )
            inferred_applies_to = (
                f"当用户询问{zh_focus_short}是否合理、合规或需要补充说明时。"
                if top_terms else f"当用户询问{normalized_category}相关问题时。"
            )
        else:
            inferred_description = (
                f"Used for {normalized_category} decisions, especially around {', '.join(top_terms)}."
                if top_terms else f"Used for {normalized_category} decisions."
            )
            inferred_applies_to = (
                f"When the user asks whether {', '.join(top_terms[:3])} is sufficient, compliant, or needs clarification."
                if top_terms else f"When the user asks about {normalized_category}."
            )

        await storage.update_knowhow_category_profile(
            normalized_category,
            description=self._normalize_text(existing.get("description")) or self._normalize_text(defaults.get("description")) or inferred_description,
            aliases=self._dump_list(merged_aliases),
            example_queries=self._dump_list(merged_examples),
            applies_to=self._normalize_text(existing.get("applies_to")) or self._normalize_text(defaults.get("applies_to")) or inferred_applies_to,
        )
    async def list_rules(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        is_admin: bool = False,
    ) -> list[dict]:
        rules = await storage.list_knowhow_rules(
            category=category,
            active_only=active_only,
            user_id=user_id,
            group_id=group_id,
            is_admin=is_admin,
        )
        return [self._serialize_rule(rule) for rule in rules]

    async def get_rule(self, rule_id: str) -> Optional[dict]:
        rule = await storage.get_knowhow_rule(rule_id)
        if not rule:
            return None
        return self._serialize_rule(rule)

    async def add_rule(
        self,
        category: str,
        rule_text: str,
        title: str = "",
        trigger_terms: Any = None,
        exclude_terms: Any = None,
        applies_when: str = "",
        not_applies_when: str = "",
        examples: Any = None,
        weight: int = 2,
        source: str = "user",
        owner_id: Optional[str] = None,
        owner_group_id: Optional[str] = None,
    ) -> str:
        prepared = self._prepare_rule_fields(
            category=category,
            rule_text=rule_text,
            title=title,
            trigger_terms=trigger_terms,
            exclude_terms=exclude_terms,
            applies_when=applies_when,
            not_applies_when=not_applies_when,
            examples=examples,
        )
        await storage.ensure_knowhow_category(prepared["category"])
        rule_id = await storage.add_knowhow_rule(
            category=prepared["category"],
            title=prepared["title"],
            rule_text=prepared["rule_text"],
            trigger_terms=self._dump_list(prepared["trigger_terms"]),
            exclude_terms=self._dump_list(prepared["exclude_terms"]),
            applies_when=prepared["applies_when"],
            not_applies_when=prepared["not_applies_when"],
            examples=self._dump_list(prepared["examples"]),
            weight=self._normalize_weight(weight),
            source=source,
            owner_id=owner_id,
            owner_group_id=self._normalize_text(owner_group_id) or None,
        )
        await self._refresh_category_profile(prepared["category"])
        return rule_id

    async def update_rule(self, rule_id: str, updates: dict) -> bool:
        existing_raw = await storage.get_knowhow_rule(rule_id)
        if not existing_raw:
            return False

        existing = self._serialize_rule(existing_raw)
        old_category = existing["category"]
        content_changed = any(key in updates for key in ("category", "rule_text"))
        prepared = self._prepare_rule_fields(
            category=updates.get("category", existing["category"]),
            rule_text=updates.get("rule_text", existing["rule_text"]),
            title=updates["title"] if "title" in updates else ("" if content_changed else existing["title"]),
            trigger_terms=updates["trigger_terms"] if "trigger_terms" in updates else ([] if content_changed else existing["trigger_terms"]),
            exclude_terms=updates.get("exclude_terms", existing["exclude_terms"]),
            applies_when=updates["applies_when"] if "applies_when" in updates else ("" if content_changed else existing["applies_when"]),
            not_applies_when=updates.get("not_applies_when", existing["not_applies_when"]),
            examples=updates["examples"] if "examples" in updates else ([] if content_changed else existing["examples"]),
        )
        await storage.ensure_knowhow_category(prepared["category"])

        persisted_updates = {
            "category": prepared["category"],
            "title": prepared["title"],
            "rule_text": prepared["rule_text"],
            "trigger_terms": self._dump_list(prepared["trigger_terms"]),
            "exclude_terms": self._dump_list(prepared["exclude_terms"]),
            "applies_when": prepared["applies_when"],
            "not_applies_when": prepared["not_applies_when"],
            "examples": self._dump_list(prepared["examples"]),
        }
        if "weight" in updates:
            persisted_updates["weight"] = self._normalize_weight(updates.get("weight"), existing_raw.get("weight", 2))
        if "is_active" in updates:
            persisted_updates["is_active"] = 1 if bool(updates.get("is_active")) else 0
        if "owner_group_id" in updates:
            persisted_updates["owner_group_id"] = self._normalize_text(updates.get("owner_group_id")) or None

        set_clause = ", ".join(f"{key}=?" for key in persisted_updates)
        params = [*persisted_updates.values(), datetime.now(timezone.utc).isoformat(), rule_id]
        await storage.db.execute(
            f"UPDATE knowhow_rules SET {set_clause}, updated_at=? WHERE id=?",
            params,
        )
        await storage.db.commit()
        await self._refresh_category_profile(prepared["category"])
        if prepared["category"] != old_category:
            await self._refresh_category_profile(old_category)
        return True

    async def delete_rule(self, rule_id: str) -> bool:
        existing = await storage.get_knowhow_rule(rule_id)
        if not existing:
            return False
        category = self._normalize_text(existing.get("category")) or UNCATEGORIZED
        await storage.db.execute("DELETE FROM knowhow_rules WHERE id=?", (rule_id,))
        await storage.db.commit()
        await self._refresh_category_profile(category)
        return True

    def _extract_import_rules(self, payload: Any) -> list[dict]:
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
        if not isinstance(raw_rule, dict):
            raise ValueError(f"第 {index} 条规则格式不正确")

        category = str(raw_rule.get("category") or "").strip() or UNCATEGORIZED
        title = str(raw_rule.get("title") or "").strip()
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
            "title": title,
            "rule_text": rule_text,
            "trigger_terms": KnowhowService._normalize_list(raw_rule.get("trigger_terms")),
            "exclude_terms": KnowhowService._normalize_list(raw_rule.get("exclude_terms")),
            "applies_when": str(raw_rule.get("applies_when") or "").strip(),
            "not_applies_when": str(raw_rule.get("not_applies_when") or "").strip(),
            "examples": KnowhowService._normalize_list(raw_rule.get("examples")),
            "weight": weight,
            "hit_count": hit_count,
            "confidence": confidence,
            "source": source,
            "is_active": is_active,
            "owner_id": str(raw_rule.get("owner_id") or "").strip() or None,
            "owner_group_id": str(raw_rule.get("owner_group_id") or "").strip() or None,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    async def export_rules(
        self,
        *,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        is_admin: bool = False,
        group_manager_scope: bool = False,
    ) -> dict:
        rules = await self.list_rules(
            active_only=False,
            user_id=user_id,
            group_id=group_id,
            is_admin=is_admin,
        )
        if group_manager_scope and group_id and not is_admin:
            normalized_group_id = self._normalize_text(group_id)
            rules = [
                rule for rule in rules
                if self._normalize_text(rule.get("owner_group_id")) == normalized_group_id
            ]
        return {
            "kind": "knowhow_rules_export",
            "schema_version": 2,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_rules": len(rules),
            "rules": rules,
        }

    async def import_rules(
        self,
        payload: Any,
        strategy: Literal["append", "replace"] = "append",
        *,
        owner_id: Optional[str] = None,
        owner_group_id: Optional[str] = None,
        force_owner_scope: bool = False,
    ) -> dict:
        if strategy not in {"append", "replace"}:
            raise ValueError("不支持的导入策略")

        rules = self._extract_import_rules(payload)
        if force_owner_scope:
            if owner_group_id:
                existing_rules = [
                    rule
                    for rule in await storage.list_knowhow_rules(active_only=False)
                    if self._normalize_text(rule.get("owner_group_id")) == self._normalize_text(owner_group_id)
                ]
            elif owner_id:
                existing_rules = [
                    rule
                    for rule in await storage.list_knowhow_rules(active_only=False)
                    if self._normalize_text(rule.get("owner_id")) == self._normalize_text(owner_id)
                    and not self._normalize_text(rule.get("owner_group_id"))
                ]
            else:
                existing_rules = []
        else:
            existing_rules = await storage.list_knowhow_rules(active_only=False)
        existing_keys = {
            (
                self._normalize_text(rule.get("category")),
                self._normalize_text(rule.get("rule_text")),
            )
            for rule in existing_rules
        }

        deleted_count = 0
        if strategy == "replace":
            cursor = await storage.db.execute("DELETE FROM knowhow_rules")
            deleted_count = max(cursor.rowcount, 0)
            existing_keys.clear()

        rows: list[tuple[Any, ...]] = []
        skipped_count = 0
        touched_categories: set[str] = set()
        for rule in rules:
            prepared = self._prepare_rule_fields(
                category=rule["category"],
                rule_text=rule["rule_text"],
                title=rule.get("title", ""),
                trigger_terms=rule.get("trigger_terms"),
                exclude_terms=rule.get("exclude_terms"),
                applies_when=rule.get("applies_when", ""),
                not_applies_when=rule.get("not_applies_when", ""),
                examples=rule.get("examples"),
            )
            key = (prepared["category"], prepared["rule_text"])
            if key in existing_keys:
                skipped_count += 1
                continue

            existing_keys.add(key)
            touched_categories.add(prepared["category"])
            await storage.ensure_knowhow_category(prepared["category"])
            rows.append(
                (
                    gen_id(),
                    prepared["category"],
                    prepared["title"],
                    prepared["rule_text"],
                    self._dump_list(prepared["trigger_terms"]),
                    self._dump_list(prepared["exclude_terms"]),
                    prepared["applies_when"],
                    prepared["not_applies_when"],
                    self._dump_list(prepared["examples"]),
                    self._normalize_weight(rule["weight"]),
                    rule["hit_count"],
                    rule["confidence"],
                    rule["source"],
                    rule["is_active"],
                    (
                        self._normalize_text(owner_id) or None
                        if force_owner_scope
                        else self._normalize_text(rule.get("owner_id")) or self._normalize_text(owner_id) or None
                    ),
                    (
                        self._normalize_text(owner_group_id) or None
                        if force_owner_scope
                        else self._normalize_text(rule.get("owner_group_id")) or self._normalize_text(owner_group_id) or None
                    ),
                    rule["created_at"],
                    rule["updated_at"],
                )
            )

        if rows:
            await storage.db.executemany(
                "INSERT INTO knowhow_rules ("
                "id, category, title, rule_text, trigger_terms, exclude_terms, applies_when, not_applies_when, "
                "examples, weight, hit_count, confidence, source, is_active, owner_id, owner_group_id, created_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        await storage.db.commit()
        await self._sync_categories_from_rules()
        for category in sorted(touched_categories):
            await self._refresh_category_profile(category)

        total_after_import = len(await storage.list_knowhow_rules(active_only=False))
        return {
            "strategy": strategy,
            "total_in_file": len(rules),
            "imported_count": len(rows),
            "skipped_count": skipped_count,
            "deleted_count": deleted_count,
            "total_after_import": total_after_import,
        }
    def _extract_rule_keywords(self, rule: dict) -> list[str]:
        bag: list[str] = []
        bag.extend(self._extract_keywords(rule.get("title", "")))
        bag.extend(self._extract_keywords(rule.get("rule_text", "")))
        bag.extend(self._normalize_list(rule.get("trigger_terms")))
        bag.extend(self._normalize_list(rule.get("examples")))
        if rule.get("category"):
            bag.extend(self._normalize_list([rule["category"]]))

        normalized: list[str] = []
        seen: set[str] = set()
        for item in bag:
            text = self._normalize_text(item).lower()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    async def check_against_content(self, content: str, category: str = "采购预审") -> list[dict]:
        rules = await self.list_rules(category=category, active_only=True)
        content_lower = content.lower()
        results: list[dict] = []

        for rule in rules:
            keywords = self._extract_rule_keywords(rule)
            matched = sum(1 for keyword in keywords if keyword in content_lower)
            covered = matched >= max(1, len(keywords) // 3)
            results.append(
                {
                    "rule_id": rule["id"],
                    "rule_text": rule["rule_text"],
                    "weight": rule["weight"],
                    "covered": covered,
                    "match_score": matched / max(len(keywords), 1),
                    "detail": f"匹配 {matched}/{len(keywords)} 个关键词" if keywords else "无法自动判定",
                }
            )
            if covered:
                await storage.increment_knowhow_hit(rule["id"])
        return results

    async def get_stats(
        self,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        is_admin: bool = False,
    ) -> dict:
        all_rules = await storage.list_knowhow_rules(
            active_only=False,
            user_id=user_id,
            group_id=group_id,
            is_admin=is_admin,
        )
        if all_rules:
            await self._sync_categories_from_rules()
        active = [rule for rule in all_rules if rule.get("is_active")]
        categories = [
            item["name"]
            for item in await self.list_categories(
                user_id=user_id,
                group_id=group_id,
                is_admin=is_admin,
            )
        ]
        total_hits = sum(rule.get("hit_count", 0) for rule in all_rules)
        return {
            "total_rules": len(all_rules),
            "active_rules": len(active),
            "categories": categories,
            "total_hits": total_hits,
        }

    async def record_rule_hits(self, rules_or_ids: list[dict | str]) -> None:
        seen: set[str] = set()
        for item in rules_or_ids:
            if isinstance(item, dict) and item.get("is_virtual"):
                continue
            rule_id = str(item.get("id") if isinstance(item, dict) else item or "").strip()
            if not rule_id or rule_id in seen:
                continue
            seen.add(rule_id)
            try:
                await storage.increment_knowhow_hit(rule_id)
            except Exception:
                logger.warning("记录 knowhow 命中次数失败: %s", rule_id, exc_info=True)

    async def list_categories(
        self,
        *,
        user_id: str | None = None,
        group_id: str | None = None,
        is_admin: bool = False,
        manageable_group_id: str | None = None,
    ) -> list[dict]:
        all_rules = await storage.list_knowhow_rules(
            active_only=False,
            user_id=user_id,
            group_id=group_id,
            is_admin=is_admin,
        )
        if all_rules:
            await self._sync_categories_from_rules()
        counts: dict[str, int] = {}
        for rule in all_rules:
            category = self._normalize_text(rule.get("category")) or UNCATEGORIZED
            counts[category] = counts.get(category, 0) + 1
        manageable_counts: dict[str, int] = {}
        if is_admin:
            manageable_counts = dict(counts)
        elif manageable_group_id:
            normalized_group_id = self._normalize_text(manageable_group_id)
            for rule in all_rules:
                if self._normalize_text(rule.get("owner_group_id")) != normalized_group_id:
                    continue
                category = self._normalize_text(rule.get("category")) or UNCATEGORIZED
                manageable_counts[category] = manageable_counts.get(category, 0) + 1
        categories = await storage.list_knowhow_categories()
        serialized = [
            self._serialize_category(
                item,
                counts.get(item["name"], 0),
                manageable_counts.get(item["name"], 0),
                is_admin or manageable_counts.get(item["name"], 0) > 0,
            )
            for item in categories
        ]
        if user_id and not is_admin:
            serialized = [item for item in serialized if item["rule_count"] > 0]
        return serialized

    async def build_library_summary_rule(
        self,
        *,
        focus: str = "overview",
        rationale: str = "",
        confidence: str = "medium",
        user_id: str | None = None,
        group_id: str | None = None,
        is_admin: bool = False,
    ) -> dict:
        visible_rules = await self.list_rules(
            active_only=False,
            user_id=user_id,
            group_id=group_id,
            is_admin=is_admin,
        )
        stats = await self.get_stats(
            user_id=user_id,
            group_id=group_id,
            is_admin=is_admin,
        )
        categories = await self.list_categories(
            user_id=user_id,
            group_id=group_id,
            is_admin=is_admin,
        )

        top_categories = sorted(
            categories,
            key=lambda item: (int(item.get("rule_count", 0)), str(item.get("name") or "")),
            reverse=True,
        )[:5]
        active_rules = [rule for rule in visible_rules if rule.get("is_active")]
        top_rules = sorted(
            active_rules,
            key=lambda item: (int(item.get("hit_count", 0)), float(item.get("weight", 0))),
            reverse=True,
        )[:3]

        summary_parts = [
            f"当前你可访问的 Know-how 规则共 {stats['total_rules']} 条，其中启用 {stats['active_rules']} 条，覆盖 {len(categories)} 个分类。"
        ]
        if top_categories:
            category_text = "；".join(
                f"{item['name']}（{item['rule_count']}条）"
                for item in top_categories
            )
            summary_parts.append(f"分类分布：{category_text}。")
        if top_rules:
            rule_text = "；".join(
                f"{str(rule.get('title') or '未命名规则').strip()}（{str(rule.get('category') or UNCATEGORIZED).strip()}）"
                for rule in top_rules
            )
            summary_parts.append(f"当前较常被命中的规则有：{rule_text}。")

        title_map = {
            "stats": "Know-how 规则库统计",
            "categories": "Know-how 分类概览",
            "overview": "Know-how 规则库概览",
        }
        return {
            "id": "virtual-knowhow-library-summary",
            "category": "规则库概览",
            "title": title_map.get(focus, "Know-how 规则库概览"),
            "rule_text": " ".join(summary_parts),
            "weight": 0,
            "is_active": 1,
            "is_virtual": True,
            "route_strategy": "library_summary",
            "route_confidence": confidence,
            "route_rationale": rationale or "library_summary",
            "route_categories": [],
        }

    async def create_category(
        self,
        name: str,
        description: str = "",
        aliases: Any = None,
        example_queries: Any = None,
        applies_to: str = "",
    ) -> dict:
        normalized = self._normalize_text(name)
        if not normalized:
            raise ValueError("分类名称不能为空")
        await storage.ensure_knowhow_category(
            normalized,
            description=self._normalize_text(description),
            aliases=self._dump_list(aliases),
            example_queries=self._dump_list(example_queries),
            applies_to=self._normalize_text(applies_to),
        )
        return {
            "name": normalized,
            "description": self._normalize_text(description),
            "aliases": self._normalize_list(aliases),
            "example_queries": self._normalize_list(example_queries),
            "applies_to": self._normalize_text(applies_to),
            "rule_count": 0,
            "manageable_rule_count": 0,
            "can_manage": False,
        }

    async def update_category(self, name: str, updates: dict[str, Any]) -> dict:
        normalized_name = self._normalize_text(name)
        if not normalized_name:
            raise ValueError("分类名称不能为空")
        existing = {item["name"]: item for item in await self.list_categories()}
        if normalized_name not in existing:
            raise ValueError("分类不存在")

        payload: dict[str, Any] = {}
        if "description" in updates:
            payload["description"] = self._normalize_text(updates.get("description"))
        if "aliases" in updates:
            payload["aliases"] = self._dump_list(updates.get("aliases"))
        if "example_queries" in updates:
            payload["example_queries"] = self._dump_list(updates.get("example_queries"))
        if "applies_to" in updates:
            payload["applies_to"] = self._normalize_text(updates.get("applies_to"))
        await storage.update_knowhow_category_profile(normalized_name, **payload)
        refreshed = {item["name"]: item for item in await self.list_categories()}
        return refreshed[normalized_name]

    async def rename_category(self, old_name: str, new_name: str) -> int:
        normalized_new_name = self._normalize_text(new_name)
        if not normalized_new_name:
            raise ValueError("新分类名称不能为空")
        await storage.rename_knowhow_category(old_name, normalized_new_name)
        cursor = await storage.db.execute(
            "UPDATE knowhow_rules SET category=?, updated_at=? WHERE category=?",
            (normalized_new_name, datetime.now(timezone.utc).isoformat(), old_name),
        )
        await storage.db.commit()
        await self._refresh_category_profile(normalized_new_name)
        return cursor.rowcount

    async def rename_category_for_group(
        self,
        old_name: str,
        new_name: str,
        *,
        owner_group_id: str,
    ) -> int:
        normalized_old_name = self._normalize_text(old_name)
        normalized_new_name = self._normalize_text(new_name)
        normalized_group_id = self._normalize_text(owner_group_id)
        if not normalized_old_name or not normalized_new_name:
            raise ValueError("分类名称不能为空")
        if not normalized_group_id:
            raise ValueError("缺少用户组信息")

        affected_rules = [
            rule
            for rule in await storage.list_knowhow_rules(active_only=False)
            if self._normalize_text(rule.get("category")) == normalized_old_name
            and self._normalize_text(rule.get("owner_group_id")) == normalized_group_id
        ]
        if not affected_rules:
            raise ValueError("没有可管理的分类规则")

        existing_category = next(
            (
                item
                for item in await storage.list_knowhow_categories()
                if self._normalize_text(item.get("name")) == normalized_old_name
            ),
            None,
        )
        await storage.ensure_knowhow_category(
            normalized_new_name,
            description=self._normalize_text(existing_category.get("description") if existing_category else ""),
            aliases=existing_category.get("aliases") if existing_category else None,
            example_queries=existing_category.get("example_queries") if existing_category else None,
            applies_to=self._normalize_text(existing_category.get("applies_to") if existing_category else ""),
        )
        cursor = await storage.db.execute(
            "UPDATE knowhow_rules SET category=?, updated_at=? WHERE category=? AND owner_group_id=?",
            (
                normalized_new_name,
                datetime.now(timezone.utc).isoformat(),
                normalized_old_name,
                normalized_group_id,
            ),
        )
        await storage.db.commit()
        await self._refresh_category_profile(normalized_new_name)
        remaining = [
            rule
            for rule in await storage.list_knowhow_rules(active_only=False)
            if self._normalize_text(rule.get("category")) == normalized_old_name
        ]
        if not remaining:
            await storage.delete_knowhow_category(normalized_old_name)
        return cursor.rowcount

    async def delete_category(self, name: str, delete_rules: bool = True) -> int:
        if delete_rules:
            cursor = await storage.db.execute("DELETE FROM knowhow_rules WHERE category=?", (name,))
        else:
            cursor = await storage.db.execute(
                "UPDATE knowhow_rules SET category=?, updated_at=? WHERE category=?",
                (UNCATEGORIZED, datetime.now(timezone.utc).isoformat(), name),
            )
            await storage.ensure_knowhow_category(UNCATEGORIZED)
            await self._refresh_category_profile(UNCATEGORIZED)
        await storage.delete_knowhow_category(name)
        await storage.db.commit()
        return cursor.rowcount

    async def delete_category_for_group(
        self,
        name: str,
        *,
        owner_group_id: str,
        delete_rules: bool = True,
    ) -> int:
        normalized_name = self._normalize_text(name)
        normalized_group_id = self._normalize_text(owner_group_id)
        if not normalized_name:
            raise ValueError("分类名称不能为空")
        if not normalized_group_id:
            raise ValueError("缺少用户组信息")

        existing = [
            rule
            for rule in await storage.list_knowhow_rules(active_only=False)
            if self._normalize_text(rule.get("category")) == normalized_name
            and self._normalize_text(rule.get("owner_group_id")) == normalized_group_id
        ]
        if not existing:
            raise ValueError("没有可管理的分类规则")

        if delete_rules:
            cursor = await storage.db.execute(
                "DELETE FROM knowhow_rules WHERE category=? AND owner_group_id=?",
                (normalized_name, normalized_group_id),
            )
        else:
            cursor = await storage.db.execute(
                "UPDATE knowhow_rules SET category=?, updated_at=? WHERE category=? AND owner_group_id=?",
                (
                    UNCATEGORIZED,
                    datetime.now(timezone.utc).isoformat(),
                    normalized_name,
                    normalized_group_id,
                ),
            )
            await storage.ensure_knowhow_category(UNCATEGORIZED)
            await self._refresh_category_profile(UNCATEGORIZED)
        await storage.db.commit()
        remaining = [
            rule
            for rule in await storage.list_knowhow_rules(active_only=False)
            if self._normalize_text(rule.get("category")) == normalized_name
        ]
        if not remaining:
            await storage.delete_knowhow_category(normalized_name)
        return cursor.rowcount


knowhow_service = KnowhowService()
