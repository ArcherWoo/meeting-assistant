"""
Context assembler for planner-driven retrieval and prompt injection.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

from services.access_control import filter_accessible_skills, is_admin
from services.hybrid_search import hybrid_search
from services.knowhow_router import knowhow_router
from services.knowhow_service import knowhow_service
from services.retrieval_planner import (
    RetrievalPlan,
    RetrievalPlanAction,
    RetrievalPlannerSettings,
    RetrievalSurface,
    retrieval_planner,
)
from services.skill_manager import skill_manager
from services.skill_matcher import skill_matcher
from utils.text_utils import extract_han_segments

logger = logging.getLogger(__name__)


class RetrievalTraceHandler(Protocol):
    async def on_stage_start(
        self,
        step_key: str,
        *,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int: ...

    async def on_stage_complete(
        self,
        step_index: int,
        step_key: str,
        result: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def on_stage_error(
        self,
        step_index: int,
        step_key: str,
        error: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...


@dataclass
class AssembledContext:
    knowledge_results: List[dict] = field(default_factory=list)
    knowhow_rules: List[dict] = field(default_factory=list)
    matched_skills: List[dict] = field(default_factory=list)
    source_summary: str = ""
    retrieval_plan: RetrievalPlan | None = None

    @property
    def has_context(self) -> bool:
        return bool(self.knowledge_results or self.knowhow_rules or self.matched_skills)

    def _build_source_summary(self) -> str:
        parts: list[str] = []
        if self.knowledge_results:
            parts.append(f"知识库({len(self.knowledge_results)}条)")
        if self.knowhow_rules:
            parts.append(f"Know-how({len(self.knowhow_rules)}条)")
        if self.matched_skills:
            parts.append(f"Skill({len(self.matched_skills)}个)")
        return " + ".join(parts) if parts else ""

    @staticmethod
    def _format_knowhow_rule(rule: dict, index: int) -> str:
        weight_icon = "⚠️" if int(rule.get("weight", 0) or 0) >= 3 else "ℹ️"
        category = str(rule.get("category") or "").strip()
        category_prefix = f"({category}) " if category and category != "未分类" else ""
        return f"{weight_icon} [{index}] {category_prefix}{rule.get('rule_text', '')}"

    @staticmethod
    def _format_knowledge_result(result: dict, index: int) -> str:
        if "item_name" in result:
            line = f"[{index}] {result.get('category', '')} - {result.get('item_name', '')}".strip(" -")
            if result.get("supplier"):
                line += f"（供应商: {result['supplier']}）"
            if result.get("unit_price"):
                line += f" 单价: {result['unit_price']}"
            if result.get("raw_text"):
                line += f"\n    原文: {str(result['raw_text'])[:200]}"
            return line
        if "content" in result:
            source = result.get("source_file", "未知来源")
            return f"[{index}] 来源: {source}\n    {str(result.get('content', ''))[:300]}"
        return ""

    @staticmethod
    def _format_skill_match(skill: dict) -> str:
        confidence_icon = "✅" if skill.get("confidence") == "high" else "🧩"
        return (
            f"{confidence_icon} 《{skill.get('skill_name', '')}》"
            f"（匹配度 {float(skill.get('score', 0.0)):.0%}）"
            f" - {skill.get('description', '')}"
        )

    @staticmethod
    def _normalize_text_snippet(value: str, max_chars: int = 180) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @staticmethod
    def _coerce_int(value: object) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _build_chunk_locator(cls, result: dict) -> tuple[str, dict]:
        slide_index = cls._coerce_int(result.get("slide_index"))
        if slide_index is not None and slide_index <= 0:
            slide_index = None
        page = cls._coerce_int(result.get("page"))
        if page is not None and page <= 0:
            page = None
        chunk_index = cls._coerce_int(result.get("chunk_index"))
        if chunk_index is not None and chunk_index <= 0:
            chunk_index = None
        raw_char_start = cls._coerce_int(result.get("char_start"))
        raw_char_end = cls._coerce_int(result.get("char_end"))
        char_start = raw_char_start + 1 if raw_char_start is not None and raw_char_start >= 0 else None
        char_end = raw_char_end if raw_char_end is not None and raw_char_end > 0 else None
        row_start = cls._coerce_int(result.get("row_start"))
        row_end = cls._coerce_int(result.get("row_end"))

        locator_fields = {
            "page": page or slide_index,
            "sheet": str(result.get("sheet") or "").strip() or None,
            "story": str(result.get("story") or "").strip() or None,
            "row_start": row_start,
            "row_end": row_end,
            "chunk_index": chunk_index,
            "char_start": char_start,
            "char_end": char_end,
            "source": str(result.get("source") or "").strip() or None,
            "ocr_segment_index": cls._coerce_int(result.get("ocr_segment_index")),
            "table_title": str(result.get("table_title") or "").strip() or None,
        }

        location_parts: list[str] = []
        include_page_in_location = bool(result.get("page")) or any(
            locator_fields.get(key)
            for key in ("sheet", "story", "row_start", "row_end", "ocr_segment_index", "table_title")
        ) or locator_fields.get("source") == "ocr"
        if locator_fields["sheet"]:
            location_parts.append(f"工作表 {locator_fields['sheet']}")
        if locator_fields["page"] and include_page_in_location:
            location_parts.append(f"第{locator_fields['page']}页")
        if locator_fields["story"]:
            location_parts.append(f"区域 {locator_fields['story']}")
        if row_start is not None and row_end is not None:
            location_parts.append(f"行 {row_start}" if row_start == row_end else f"行 {row_start}-{row_end}")
        if locator_fields["ocr_segment_index"] is not None:
            location_parts.append(f"OCR 段 #{locator_fields['ocr_segment_index']}")
        if chunk_index is not None:
            location_parts.append(f"片段 #{chunk_index}")
        if char_start is not None and char_end is not None and char_end >= char_start:
            location_parts.append(f"字符 {char_start}-{char_end}")
        if locator_fields["table_title"]:
            location_parts.append(f"表 {locator_fields['table_title']}")
        if locator_fields["source"] == "ocr":
            location_parts.append("OCR 恢复")

        return " · ".join(location_parts), locator_fields

    @classmethod
    def _build_knowledge_citation(cls, result: dict, index: int) -> dict:
        source_name = str(result.get("source_file") or "知识库文档")
        citation = {
            "id": str(result.get("id") or result.get("chunk_id") or f"knowledge-{index}"),
            "source_type": "knowledge",
            "label": source_name,
            "file_name": source_name,
        }

        if "item_name" in result:
            title_parts = [str(part).strip() for part in (result.get("category"), result.get("item_name")) if part]
            title = " - ".join(title_parts) if title_parts else f"知识记录 {index}"
            snippet = cls._normalize_text_snippet(
                result.get("raw_text")
                or "；".join(
                    part
                    for part in [
                        f"供应商: {result['supplier']}" if result.get("supplier") else "",
                        f"单价: {result['unit_price']}" if result.get("unit_price") else "",
                        f"总价: {result['total_price']}" if result.get("total_price") else "",
                    ]
                    if part
                )
                or title
            )
            location_parts = []
            if result.get("supplier"):
                location_parts.append(f"供应商: {result['supplier']}")
            if result.get("unit_price"):
                location_parts.append(f"单价: {result['unit_price']}")
            location = " · ".join(location_parts)
        else:
            chunk_type_map = {"text": "正文片段", "table": "表格片段", "note": "备注片段"}
            location, locator_fields = cls._build_chunk_locator(result)
            page = cls._coerce_int(locator_fields.get("page"))
            chunk_type = str(result.get("chunk_type") or "").strip().lower()
            chunk_type_label = chunk_type_map.get(chunk_type, chunk_type or "正文片段")
            chunk_index = cls._coerce_int(locator_fields.get("chunk_index"))
            char_start = cls._coerce_int(locator_fields.get("char_start"))
            char_end = cls._coerce_int(locator_fields.get("char_end"))

            title_parts = []
            if locator_fields.get("sheet"):
                title_parts.append(str(locator_fields["sheet"]))
            if page is not None:
                title_parts.append(f"第{slide_index}页")
            if chunk_type_label:
                title_parts.append(chunk_type_label)
            title = " · ".join(title_parts) if title_parts else f"知识片段 {index}"
            snippet = cls._normalize_text_snippet(result.get("content") or "")
            location_parts = []
            if chunk_index is not None:
                location_parts.append(f"片段 #{chunk_index}")
            if char_start is not None and char_end is not None and char_end >= char_start:
                location_parts.append(f"字符 {char_start}-{char_end}")
            if not location_parts and title_parts:
                location_parts = title_parts.copy()
            location = " · ".join(location_parts)

            if slide_index is not None:
                citation["page"] = slide_index
            if chunk_type:
                citation["chunk_type"] = chunk_type
            if chunk_index is not None:
                citation["chunk_index"] = chunk_index
            if char_start is not None:
                citation["char_start"] = char_start
            if char_end is not None:
                citation["char_end"] = char_end

        citation.update({"title": title, "snippet": snippet, "location": location})
        return citation

    @classmethod
    def _build_knowhow_citation(cls, rule: dict, index: int) -> dict:
        return {
            "id": str(rule.get("id") or f"knowhow-{index}"),
            "source_type": "knowhow",
            "label": str(rule.get("category") or "Know-how"),
            "title": f"规则 {index}",
            "snippet": cls._normalize_text_snippet(rule.get("rule_text") or ""),
            "location": f"权重 {rule.get('weight', 0)}",
        }

    @classmethod
    def _build_skill_citation(cls, skill: dict, index: int) -> dict:
        return {
            "id": str(skill.get("skill_id") or f"skill-{index}"),
            "source_type": "skill",
            "label": str(skill.get("skill_name") or f"Skill {index}"),
            "title": "技能匹配",
            "snippet": cls._normalize_text_snippet(skill.get("description") or ""),
            "location": f"匹配度 {float(skill.get('score', 0.0)):.0%} · {skill.get('confidence', 'low')}",
        }

    @classmethod
    def _build_knowledge_citation(cls, result: dict, index: int) -> dict:
        source_name = str(result.get("source_file") or "知识库文档")
        citation = {
            "id": str(result.get("id") or result.get("chunk_id") or f"knowledge-{index}"),
            "source_type": "knowledge",
            "label": source_name,
            "file_name": source_name,
        }

        if "item_name" in result:
            title_parts = [str(part).strip() for part in (result.get("category"), result.get("item_name")) if part]
            title = " - ".join(title_parts) if title_parts else f"知识记录 {index}"
            snippet = cls._normalize_text_snippet(
                result.get("raw_text")
                or "；".join(
                    part
                    for part in [
                        f"供应商: {result['supplier']}" if result.get("supplier") else "",
                        f"单价: {result['unit_price']}" if result.get("unit_price") else "",
                        f"总价: {result['total_price']}" if result.get("total_price") else "",
                    ]
                    if part
                )
                or title
            )
            location_parts = []
            if result.get("supplier"):
                location_parts.append(f"供应商: {result['supplier']}")
            if result.get("unit_price"):
                location_parts.append(f"单价: {result['unit_price']}")
            location = " · ".join(location_parts)
            citation.update({"title": title, "snippet": snippet, "location": location})
            return citation

        chunk_type_map = {"text": "正文片段", "table": "表格片段", "note": "备注片段"}
        chunk_type = str(result.get("chunk_type") or "").strip().lower()
        chunk_type_label = chunk_type_map.get(chunk_type, chunk_type or "正文片段")
        location, locator_fields = cls._build_chunk_locator(result)
        page = cls._coerce_int(locator_fields.get("page"))
        chunk_index = cls._coerce_int(locator_fields.get("chunk_index"))
        char_start = cls._coerce_int(locator_fields.get("char_start"))
        char_end = cls._coerce_int(locator_fields.get("char_end"))

        title_parts = []
        if locator_fields.get("sheet"):
            title_parts.append(str(locator_fields["sheet"]))
        if page is not None:
            title_parts.append(f"第{page}页")
        if chunk_type_label:
            title_parts.append(chunk_type_label)
        title = " · ".join(title_parts) if title_parts else f"知识片段 {index}"
        snippet = cls._normalize_text_snippet(result.get("content") or "")
        if not location and title_parts:
            location = " · ".join(title_parts)

        if page is not None:
            citation["page"] = page
        if chunk_type:
            citation["chunk_type"] = chunk_type
        if chunk_index is not None:
            citation["chunk_index"] = chunk_index
        if char_start is not None:
            citation["char_start"] = char_start
        if char_end is not None:
            citation["char_end"] = char_end
        for key in ("sheet", "row_start", "row_end", "story", "source", "ocr_segment_index", "table_title"):
            value = locator_fields.get(key)
            if value is not None and value != "":
                citation[key] = value

        citation.update({"title": title, "snippet": snippet, "location": location})
        return citation

    def to_metadata_payload(self) -> dict:
        citations = [
            *[
                self._build_knowledge_citation(result, index)
                for index, result in enumerate(self.knowledge_results[:5], 1)
            ],
            *[
                self._build_knowhow_citation(rule, index)
                for index, rule in enumerate(self.knowhow_rules[:4], 1)
            ],
            *[
                self._build_skill_citation(skill, index)
                for index, skill in enumerate(self.matched_skills[:3], 1)
            ],
        ]
        return {
            "knowledge_count": len(self.knowledge_results),
            "knowhow_count": len(self.knowhow_rules),
            "skill_count": len(self.matched_skills),
            "summary": self.source_summary,
            "citations": citations,
            "retrieval_plan": (
                self.retrieval_plan.model_dump(mode="json")
                if self.retrieval_plan is not None
                else None
            ),
        }

    def fit_to_budget(self, max_chars: int) -> "AssembledContext":
        if max_chars <= 0 or not self.has_context:
            return AssembledContext(retrieval_plan=self.retrieval_plan)

        fitted = AssembledContext(retrieval_plan=self.retrieval_plan)
        used = 0

        def try_add_section(header: str, items: list[dict], formatter, target_attr: str) -> None:
            nonlocal used
            if not items:
                return

            header_cost = len(header) + 1
            header_used = False
            collected: list[dict] = []

            for index, item in enumerate(items, 1):
                line = formatter(item, index) if formatter.__code__.co_argcount == 2 else formatter(item)
                if not line:
                    continue
                cost = len(line) + 1 + (0 if header_used else header_cost)
                if used + cost > max_chars:
                    break
                if not header_used:
                    used += header_cost
                    header_used = True
                used += len(line) + 1
                collected.append(item)

            if collected:
                setattr(fitted, target_attr, collected)

        try_add_section(
            "📋 以下是相关业务规则（Know-how），回答时请优先核查：",
            self.knowhow_rules,
            self._format_knowhow_rule,
            "knowhow_rules",
        )
        try_add_section(
            "📚 以下是从知识库检索到的相关信息，回答时请优先参考：",
            self.knowledge_results[:5],
            self._format_knowledge_result,
            "knowledge_results",
        )
        try_add_section(
            "🛠️ 检测到用户意图可能匹配以下技能（Skill），可按需引导用户使用：",
            self.matched_skills,
            self._format_skill_match,
            "matched_skills",
        )

        fitted.source_summary = fitted._build_source_summary()
        return fitted

    def to_prompt_suffix(self, max_chars: int | None = None) -> str:
        ctx = self.fit_to_budget(max_chars) if max_chars is not None else self
        sections: list[str] = []

        if ctx.knowhow_rules:
            lines = [
                "📋 以下是相关业务规则（Know-how），回答时请优先核查：",
                *[
                    ctx._format_knowhow_rule(rule, index)
                    for index, rule in enumerate(ctx.knowhow_rules, 1)
                ],
            ]
            sections.append("\n".join(lines))

        if ctx.knowledge_results:
            lines = [
                "📚 以下是从知识库检索到的相关信息，回答时请优先参考：",
                *[
                    text
                    for index, result in enumerate(ctx.knowledge_results[:5], 1)
                    if (text := ctx._format_knowledge_result(result, index))
                ],
            ]
            sections.append("\n".join(lines))

        if ctx.matched_skills:
            lines = [
                "🛠️ 检测到用户意图可能匹配以下技能（Skill），可按需引导用户使用：",
                *[ctx._format_skill_match(skill) for skill in ctx.matched_skills],
            ]
            sections.append("\n".join(lines))

        return "\n\n".join(sections)


class ContextAssembler:
    def __init__(self, planner=None) -> None:
        self._planner = planner or retrieval_planner

    QUERY_STOPWORDS = {
        "请问", "帮我", "帮忙", "看看", "看下", "分析", "说明", "介绍", "告诉我",
        "关于", "这个", "这份", "一个", "一下", "是否", "怎么", "如何", "哪些",
        "什么", "需要", "里面", "内容", "材料", "文件", "文档", "问题", "情况",
        "重点", "合理", "有无", "有没有", "吗", "呢", "啊", "吧", "的", "了", "和",
    }

    TERM_ALIASES = {
        "报价": "价格",
        "价钱": "价格",
        "均价": "价格",
        "厂商": "供应商",
        "交期": "交付",
        "交货": "交付",
        "资信": "资质",
        "证书": "认证",
        "参数": "技术参数",
        "规格": "技术参数",
        "质保": "售后",
        "保修": "售后",
        "回款": "付款",
        "付款方式": "付款",
        "审批流": "审批",
        "流程": "审批",
        "单一来源": "single source",
    }

    def _extract_query_terms(self, query: str) -> list[str]:
        normalized = " ".join((query or "").lower().split())
        if not normalized:
            return []

        candidates: list[str] = []
        candidates.extend(
            term.strip()
            for term in re.split(r"[\s,.;:!?，。；：！？、\\()（）【】\[\]\"'`]+", normalized)
            if len(term.strip()) >= 2
        )
        candidates.extend(re.findall(r"[a-z0-9][a-z0-9_.-]{1,}", normalized))

        for segment in extract_han_segments(normalized, min_length=2):
            cleaned = segment
            for stopword in sorted(self.QUERY_STOPWORDS, key=len, reverse=True):
                cleaned = cleaned.replace(stopword, " ")
            parts = [part.strip() for part in cleaned.split() if len(part.strip()) >= 2]
            candidates.extend(parts)
            for part in parts:
                if len(part) <= 4:
                    candidates.append(part)
                    continue
                for size in range(2, min(len(part), 4) + 1):
                    for index in range(0, len(part) - size + 1):
                        candidates.append(part[index:index + size])

        expanded: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            term = candidate.strip()
            if len(term) < 2 or term in seen:
                continue
            seen.add(term)
            expanded.append(term)
            canonical = self.TERM_ALIASES.get(term)
            if canonical and canonical not in seen:
                seen.add(canonical)
                expanded.append(canonical)

        return expanded[:24]

    def _normalize_rule_text(self, text: str) -> str:
        normalized = " ".join((text or "").lower().split())
        for raw, canonical in self.TERM_ALIASES.items():
            normalized = normalized.replace(raw, canonical)
        return normalized

    def _score_knowhow_rule(self, query_terms: list[str], query_text: str, rule: dict) -> float:
        rule_text = str(rule.get("rule_text") or "")
        if not rule_text:
            return 0.0

        rule_text_normalized = self._normalize_rule_text(rule_text)
        category_text = self._normalize_rule_text(str(rule.get("category") or ""))
        rule_keywords = {
            keyword.lower()
            for keyword in knowhow_service._extract_keywords(rule_text)
            if len(keyword) >= 2
        }

        score = 0.0
        matched_terms: set[str] = set()
        for term in query_terms:
            canonical_term = self.TERM_ALIASES.get(term, term)
            if len(canonical_term) < 2 or canonical_term in matched_terms:
                continue
            if canonical_term in rule_keywords:
                score += 3.2
                matched_terms.add(canonical_term)
                continue
            if canonical_term in rule_text_normalized:
                score += 2.4
                matched_terms.add(canonical_term)
                continue
            if canonical_term in category_text:
                score += 1.6
                matched_terms.add(canonical_term)

        if len(query_text) >= 4 and query_text in rule_text_normalized:
            score += 3.0
        return score

    async def assemble(
        self,
        user_query: str,
        role_id: str = "copilot",
        category: Optional[str] = None,
        planner_settings: RetrievalPlannerSettings | None = None,
        enabled_surfaces: set[RetrievalSurface] | None = None,
        trace_handler: RetrievalTraceHandler | None = None,
        user: Optional[dict] = None,
    ) -> AssembledContext:
        ctx = AssembledContext()
        normalized_query = " ".join((user_query or "").split())
        if len(normalized_query) < 2:
            return ctx

        allowed_surfaces = self._normalize_enabled_surfaces(enabled_surfaces)
        plan = await self._plan_retrieval(
            user_query=normalized_query,
            role_id=role_id,
            planner_settings=planner_settings,
            enabled_surfaces=allowed_surfaces,
            trace_handler=trace_handler,
        )
        ctx.retrieval_plan = plan

        knowledge_actions = [action for action in plan.actions if action.surface == "knowledge"]
        knowhow_actions = [action for action in plan.actions if action.surface == "knowhow"]
        skill_actions = [action for action in plan.actions if action.surface == "skill"]

        knowledge_task = asyncio.create_task(
            self._collect_surface_results(
                surface="knowledge",
                actions=knowledge_actions,
                planner_settings=planner_settings,
                category=category,
                trace_handler=trace_handler,
                user=user,
            )
        )
        knowhow_task = asyncio.create_task(
            self._collect_surface_results(
                surface="knowhow",
                actions=knowhow_actions,
                planner_settings=planner_settings,
                trace_handler=trace_handler,
                user=user,
            )
        )
        skills_task = asyncio.create_task(
            self._collect_surface_results(
                surface="skill",
                actions=skill_actions,
                trace_handler=trace_handler,
                user=user,
            )
        )

        ctx.knowledge_results = await knowledge_task
        ctx.knowhow_rules = await knowhow_task
        ctx.matched_skills = await skills_task
        ctx.source_summary = ctx._build_source_summary()

        if ctx.has_context:
            logger.info("[ContextAssembler] Assembled context: %s", ctx.source_summary)
        else:
            logger.debug("[ContextAssembler] No context found, using base system prompt")
        return ctx

    def _normalize_enabled_surfaces(
        self,
        enabled_surfaces: set[RetrievalSurface] | None,
    ) -> tuple[RetrievalSurface, ...]:
        surfaces = enabled_surfaces or {"knowledge", "knowhow", "skill"}
        return tuple(
            surface
            for surface in ("knowledge", "knowhow", "skill")
            if surface in surfaces
        )

    async def _plan_retrieval(
        self,
        *,
        user_query: str,
        role_id: str,
        planner_settings: RetrievalPlannerSettings | None,
        enabled_surfaces: tuple[RetrievalSurface, ...],
        trace_handler: RetrievalTraceHandler | None,
    ) -> RetrievalPlan:
        step_index = await self._trace_stage_start(
            trace_handler,
            "planner",
            description="规划检索策略",
            metadata={
                "role_id": role_id,
                "query": user_query,
                "enabled_surfaces": list(enabled_surfaces),
            },
        )
        try:
            plan = await self._planner.plan(
                user_query=user_query,
                enabled_surfaces=set(enabled_surfaces),
                settings=planner_settings,
            )
            await self._trace_stage_complete(
                trace_handler,
                step_index,
                "planner",
                plan.describe(),
                metadata={"strategy": plan.strategy, "action_count": len(plan.actions)},
            )
            return plan
        except Exception as exc:
            await self._trace_stage_error(trace_handler, step_index, "planner", str(exc))
            raise

    async def _collect_surface_results(
        self,
        *,
        surface: RetrievalSurface,
        actions: list[RetrievalPlanAction],
        trace_handler: RetrievalTraceHandler | None,
        planner_settings: RetrievalPlannerSettings | None = None,
        category: Optional[str] = None,
        user: Optional[dict] = None,
    ) -> list[dict]:
        if not actions:
            return []

        step_key = f"retrieve_{surface}"
        step_index = await self._trace_stage_start(
            trace_handler,
            step_key,
            description=self._surface_description(surface, actions),
            metadata={"surface": surface, "queries": [action.query for action in actions]},
        )

        try:
            surface_limit_map = {"knowledge": 8, "knowhow": 6, "skill": 3}
            surface_limit = min(sum(action.limit for action in actions), surface_limit_map[surface])

            if surface == "knowledge":
                result_sets = await asyncio.gather(
                    *[
                        self.search_knowledge(
                            action.query,
                            category=category,
                            limit=action.limit,
                            planner_settings=planner_settings,
                        )
                        for action in actions
                    ]
                )
            elif surface == "knowhow":
                result_sets = await asyncio.gather(
                    *[
                        self.get_knowhow_rules(
                            action.query,
                            limit=action.limit,
                            user=user,
                            planner_settings=planner_settings,
                        )
                        for action in actions
                    ]
                )
            else:
                result_sets = await asyncio.gather(
                    *[
                        self.match_skills(action.query, limit=action.limit, user=user)
                        for action in actions
                    ]
                )

            results = self._fuse_surface_results(
                surface=surface,
                actions=actions,
                result_sets=result_sets,
                limit=surface_limit,
            )
            await self._trace_stage_complete(
                trace_handler,
                step_index,
                step_key,
                self._surface_summary(surface, len(results)),
                metadata={
                    "surface": surface,
                    "result_count": len(results),
                    "candidate_count": sum(len(result_set) for result_set in result_sets),
                    "action_count": len(actions),
                },
            )
            return results
        except Exception as exc:
            await self._trace_stage_error(trace_handler, step_index, step_key, str(exc))
            return []

    @staticmethod
    def _surface_description(surface: RetrievalSurface, actions: list[RetrievalPlanAction]) -> str:
        labels = {"knowledge": "检索知识库", "knowhow": "检索规则库", "skill": "检索技能库"}
        queries = "；".join(action.query for action in actions[:3])
        return f"{labels[surface]}：{queries}" if queries else labels[surface]

    @staticmethod
    def _surface_summary(surface: RetrievalSurface, result_count: int) -> str:
        if surface == "knowledge":
            return f"知识库命中 {result_count} 条"
        if surface == "knowhow":
            return f"规则库命中 {result_count} 条"
        return f"匹配到 {result_count} 个技能"

    def _surface_key_builder(self, surface: RetrievalSurface):
        if surface == "knowledge":
            return self._knowledge_record_key
        if surface == "knowhow":
            return self._knowhow_record_key
        return self._skill_record_key

    def _fuse_surface_results(
        self,
        *,
        surface: RetrievalSurface,
        actions: list[RetrievalPlanAction],
        result_sets: list[list[dict]],
        limit: int,
    ) -> list[dict]:
        if limit <= 0:
            return []

        key_builder = self._surface_key_builder(surface)
        aggregates: dict[str, dict[str, Any]] = {}

        for action_index, (action, result_set) in enumerate(zip(actions, result_sets)):
            for result_index, item in enumerate(result_set):
                key = key_builder(item)
                candidate_score = self._score_surface_candidate(
                    surface=surface,
                    item=item,
                    action=action,
                    action_index=action_index,
                    result_index=result_index,
                )
                existing = aggregates.get(key)
                if existing is None:
                    aggregates[key] = {
                        "item": item,
                        "score_sum": candidate_score,
                        "best_score": candidate_score,
                        "matched_actions": {action_index},
                        "first_action_index": action_index,
                    }
                    continue

                existing["score_sum"] += candidate_score
                existing["best_score"] = max(existing["best_score"], candidate_score)
                existing["matched_actions"].add(action_index)
                if action_index < existing["first_action_index"]:
                    existing["first_action_index"] = action_index
                    existing["item"] = item

        # 知识库最低相关度门槛：低于此值的结果不注入上下文，避免弱相关内容污染 prompt
        _MIN_SCORE: dict[str, float] = {"knowledge": 4.5, "knowhow": 0.0, "skill": 0.0}
        min_threshold = _MIN_SCORE.get(surface, 0.0)

        ranked: list[tuple[float, int, int, dict]] = []
        for aggregate in aggregates.values():
            repeat_bonus = 0.6 * max(0, len(aggregate["matched_actions"]) - 1)
            final_score = aggregate["best_score"] + 0.35 * max(
                0.0,
                aggregate["score_sum"] - aggregate["best_score"],
            ) + repeat_bonus
            if final_score < min_threshold:
                continue
            ranked.append(
                (
                    final_score,
                    len(aggregate["matched_actions"]),
                    -aggregate["first_action_index"],
                    aggregate["item"],
                )
            )

        ranked.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
        return [item for _, _, _, item in ranked[:limit]]

    def _score_surface_candidate(
        self,
        *,
        surface: RetrievalSurface,
        item: dict,
        action: RetrievalPlanAction,
        action_index: int,
        result_index: int,
    ) -> float:
        priority_bonus = max(0.0, 1.8 - action_index * 0.25)
        required_bonus = 1.1 if action.required else 0.0
        rank_bonus = max(0.0, 0.7 - result_index * 0.08)

        if surface == "knowledge":
            base_score = self._score_knowledge_candidate(item, action.query)
        elif surface == "knowhow":
            query_terms = self._extract_query_terms(action.query)
            query_text = self._normalize_rule_text(action.query)
            base_score = self._score_knowhow_rule(query_terms, query_text, item)
            base_score += float(item.get("weight", 0)) * 0.12
            base_score += float(item.get("hit_count", 0)) * 0.005
        else:
            base_score = self._score_skill_candidate(item, action.query)

        return base_score + priority_bonus + required_bonus + rank_bonus

    def _score_knowledge_candidate(self, item: dict, query: str) -> float:
        query_terms = self._extract_query_terms(query)
        normalized_query = self._normalize_search_text(query)
        searchable_text = " ".join(
            [
                self._normalize_search_text(item.get("item_name")),
                self._normalize_search_text(item.get("category")),
                self._normalize_search_text(item.get("supplier")),
                self._normalize_search_text(item.get("raw_text")),
                self._normalize_search_text(item.get("content")),
                self._normalize_search_text(item.get("source_file")),
            ]
        )
        overlap_ratio = self._query_overlap_ratio(query_terms, searchable_text)
        score = overlap_ratio * 4.0
        if normalized_query and normalized_query in searchable_text:
            score += 1.4
        raw_score = self._coerce_float(item.get("score"))
        if raw_score is not None:
            if "content" in item:
                score += max(0.0, 1.8 - min(max(raw_score, 0.0), 1.8))
            elif 0.0 <= raw_score <= 1.0:
                score += raw_score * 1.2
        if item.get("item_name"):
            score += 0.35
        return score

    def _score_skill_candidate(self, item: dict, query: str) -> float:
        query_terms = self._extract_query_terms(query)
        searchable_text = " ".join(
            [
                self._normalize_search_text(item.get("skill_name")),
                self._normalize_search_text(item.get("description")),
                self._normalize_search_text(" ".join(item.get("matched_keywords") or [])),
            ]
        )
        overlap_ratio = self._query_overlap_ratio(query_terms, searchable_text)
        confidence_bonus = {"high": 1.0, "medium": 0.45}.get(
            str(item.get("confidence") or "").lower(),
            0.0,
        )
        return overlap_ratio * 3.0 + float(item.get("score", 0.0)) * 4.0 + confidence_bonus

    @staticmethod
    def _normalize_search_text(value: object) -> str:
        return " ".join(str(value or "").lower().split())

    def _query_overlap_ratio(self, query_terms: list[str], searchable_text: str) -> float:
        if not query_terms or not searchable_text:
            return 0.0
        matched_terms = {term for term in query_terms if len(term) >= 2 and term in searchable_text}
        return len(matched_terms) / max(len(query_terms), 1)

    @staticmethod
    def _knowledge_record_key(record: dict) -> str:
        return str(
            record.get("id")
            or record.get("chunk_id")
            or (
                f"{record.get('source_file', '')}:"
                f"{record.get('chunk_index', '')}:"
                f"{record.get('char_start', '')}:"
                f"{str(record.get('content', ''))[:80]}"
            )
        )

    @staticmethod
    def _knowhow_record_key(record: dict) -> str:
        return str(record.get("id") or f"{record.get('category', '')}:{record.get('rule_text', '')}")

    @staticmethod
    def _skill_record_key(record: dict) -> str:
        return str(
            record.get("skill_id")
            or record.get("skill_name")
            or record.get("description")
            or ""
        )

    async def _trace_stage_start(
        self,
        trace_handler: RetrievalTraceHandler | None,
        step_key: str,
        *,
        description: str,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        if trace_handler is None:
            return None
        try:
            return await trace_handler.on_stage_start(
                step_key,
                description=description,
                metadata=metadata,
            )
        except Exception:
            logger.debug("[ContextAssembler] Failed to emit stage start", exc_info=True)
            return None

    async def _trace_stage_complete(
        self,
        trace_handler: RetrievalTraceHandler | None,
        step_index: int | None,
        step_key: str,
        result: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if trace_handler is None or step_index is None:
            return
        try:
            await trace_handler.on_stage_complete(
                step_index,
                step_key,
                result,
                metadata=metadata,
            )
        except Exception:
            logger.debug("[ContextAssembler] Failed to emit stage completion", exc_info=True)

    async def _trace_stage_error(
        self,
        trace_handler: RetrievalTraceHandler | None,
        step_index: int | None,
        step_key: str,
        error: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if trace_handler is None or step_index is None:
            return
        try:
            await trace_handler.on_stage_error(
                step_index,
                step_key,
                error,
                metadata=metadata,
            )
        except Exception:
            logger.debug("[ContextAssembler] Failed to emit stage error", exc_info=True)

    async def search_knowledge(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        limit: int = 5,
        planner_settings: RetrievalPlannerSettings | None = None,
    ) -> List[dict]:
        return await self._search_knowledge(
            query,
            category=category,
            limit=limit,
            planner_settings=planner_settings,
        )

    async def _search_knowledge(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 5,
        planner_settings: RetrievalPlannerSettings | None = None,
    ) -> List[dict]:
        try:
            results = await hybrid_search.search(
                query=query,
                category=category,
                limit=limit,
                llm_settings=planner_settings,
            )
            combined: list[dict] = []
            seen_ids: set[str] = set()
            dedup_counter = 0

            for record in results.get("structured", []):
                record_id = str(record.get("id", ""))
                if not record_id:
                    record_id = f"_s{dedup_counter}"
                    dedup_counter += 1
                if record_id not in seen_ids:
                    seen_ids.add(record_id)
                    combined.append(record)

            for record in results.get("semantic", []):
                record_id = str(record.get("chunk_id") or record.get("id") or "")
                if not record_id:
                    record_id = f"_sem{dedup_counter}"
                    dedup_counter += 1
                if record_id not in seen_ids:
                    seen_ids.add(record_id)
                    combined.append(record)

            logger.debug(
                "[ContextAssembler] knowledge search structured=%s semantic=%s merged=%s",
                len(results.get("structured", [])),
                len(results.get("semantic", [])),
                len(combined),
            )
            return combined[:limit]
        except Exception as exc:
            logger.warning("[ContextAssembler] knowledge search failed: %s", exc, exc_info=True)
            return []

    async def get_knowhow_rules(
        self,
        query: str,
        *,
        limit: int = 5,
        user: Optional[dict] = None,
        planner_settings: RetrievalPlannerSettings | None = None,
    ) -> List[dict]:
        return await self._get_knowhow_rules(
            query,
            limit=limit,
            user=user,
            planner_settings=planner_settings,
        )

    async def _get_knowhow_rules(
        self,
        query: str,
        limit: int = 5,
        user: Optional[dict] = None,
        planner_settings: RetrievalPlannerSettings | None = None,
    ) -> List[dict]:
        try:
            if isinstance(user, dict):
                rules = await knowhow_service.list_rules(
                    active_only=True,
                    user_id=user.get("id"),
                    group_id=user.get("group_id"),
                    is_admin=is_admin(user),
                )
            else:
                rules = await knowhow_service.list_rules(active_only=True)
            if not rules:
                logger.debug("[ContextAssembler] skip knowhow injection because query has no useful terms")
                return []
            try:
                categories = await knowhow_service.list_categories()
            except Exception:
                logger.debug(
                    "[ContextAssembler] knowhow categories unavailable, fall back to rule-only routing",
                    exc_info=True,
                )
                categories = None
            if categories is None:
                relevant_rules = self._select_knowhow_rules_without_profiles(
                    query=query,
                    rules=rules,
                    limit=limit,
                )
                strategy = "legacy_rule_only"
                routed_categories: list[str] = []
            else:
                routing = await knowhow_router.retrieve_rules(
                    query,
                    rules,
                    category_profiles=categories,
                    limit=limit,
                    settings=planner_settings,
                )
                relevant_rules = list(routing.rules)
                strategy = routing.decision.strategy
                routed_categories = list(routing.decision.categories)
            logger.debug(
                "[ContextAssembler] knowhow rules active=%s relevant=%s strategy=%s categories=%s",
                len(rules),
                len(relevant_rules),
                strategy,
                routed_categories,
            )
            return relevant_rules
        except Exception as exc:
            logger.warning("[ContextAssembler] knowhow fetch failed: %s", exc, exc_info=True)
            return []

    def _select_knowhow_rules_without_profiles(
        self,
        *,
        query: str,
        rules: list[dict],
        limit: int,
    ) -> List[dict]:
        query_terms = self._extract_query_terms(query)
        query_text = self._normalize_rule_text(query)
        scored_rules: list[tuple[float, dict]] = []

        for rule in rules:
            score = self._score_knowhow_rule(query_terms, query_text, rule)
            if score <= 0:
                continue
            score += float(rule.get("weight", 0)) * 0.12
            score += float(rule.get("hit_count", 0)) * 0.005
            scored_rules.append((score, rule))

        scored_rules.sort(
            key=lambda item: (
                item[0],
                float(item[1].get("weight", 0)),
                float(item[1].get("hit_count", 0)),
            ),
            reverse=True,
        )
        if not scored_rules:
            return []
        top_score = scored_rules[0][0]
        cutoff = max(0.1, top_score * 0.7)
        filtered = [(score, rule) for score, rule in scored_rules if score >= cutoff] or scored_rules
        return [rule for _, rule in filtered[:limit]]

    async def match_skills(self, query: str, *, limit: int = 3, user: Optional[dict] = None) -> List[dict]:
        return await self._match_skills(query, limit=limit, user=user)

    async def _match_skills(self, query: str, limit: int = 3, user: Optional[dict] = None) -> List[dict]:
        try:
            if not skill_manager._loaded:
                await skill_manager.initialize()

            skills = skill_manager.list_skills()
            skills = await filter_accessible_skills(skills, user if isinstance(user, dict) else None)
            if not skills:
                logger.debug("[ContextAssembler] no loaded skills, skip skill matching")
                return []

            matches = skill_matcher.match(query, skills, top_k=max(limit, 1))
            relevant = [
                {
                    "skill_id": match.skill.id,
                    "skill_name": match.skill.name,
                    "description": match.skill.description[:150],
                    "score": match.score,
                    "confidence": match.confidence,
                    "matched_keywords": match.matched_keywords,
                }
                for match in matches
                if match.confidence in ("high", "medium")
            ]
            if relevant:
                logger.debug(
                    "[ContextAssembler] skill match relevant=%s total=%s",
                    len(relevant),
                    len(skills),
                )
            return relevant[:limit]
        except Exception as exc:
            logger.warning("[ContextAssembler] skill match failed: %s", exc, exc_info=True)
            return []

    @staticmethod
    def _coerce_float(value: object) -> Optional[float]:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None


context_assembler = ContextAssembler()
