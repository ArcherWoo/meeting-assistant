"""
上下文组装器 - Context Assembler
在 Copilot 模式下，自动检索知识库、匹配 Skill 和注入 Know-how 规则，
将相关上下文注入 System Prompt，实现 RAG 增强回答。

设计原则：
  - 零阻塞：任何检索失败都静默降级，不影响正常对话
  - 低延迟：并行执行各路检索，总体 <200ms
  - 最小侵入：仅修改 system prompt 尾部，不改变用户消息
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from services.hybrid_search import hybrid_search
from services.knowhow_service import knowhow_service
from services.skill_manager import skill_manager
from services.skill_matcher import skill_matcher

logger = logging.getLogger(__name__)


@dataclass
class AssembledContext:
    """组装后的上下文结果"""
    knowledge_results: List[dict] = field(default_factory=list)
    knowhow_rules: List[dict] = field(default_factory=list)
    matched_skills: List[dict] = field(default_factory=list)   # ✅ Issue 2: 新增 Skill 匹配结果
    source_summary: str = ""

    @property
    def has_context(self) -> bool:
        return bool(self.knowledge_results or self.knowhow_rules or self.matched_skills)

    def _build_source_summary(self) -> str:
        sources = []
        if self.knowledge_results:
            sources.append(f"知识库({len(self.knowledge_results)}条)")
        if self.knowhow_rules:
            sources.append(f"Know-how({len(self.knowhow_rules)}条)")
        if self.matched_skills:
            sources.append(f"Skill({len(self.matched_skills)}个)")
        return " + ".join(sources) if sources else ""

    @staticmethod
    def _format_knowhow_rule(rule: dict, index: int) -> str:
        weight_icon = "⚠️" if rule.get("weight", 0) >= 3 else "ℹ️"
        return f"{weight_icon} [{index}] {rule['rule_text']}"

    @staticmethod
    def _format_knowledge_result(result: dict, index: int) -> str:
        if "item_name" in result:
            line = f"[{index}] {result.get('category', '')} - {result['item_name']}"
            if result.get("supplier"):
                line += f"（供应商: {result['supplier']}）"
            if result.get("unit_price"):
                line += f" 单价: {result['unit_price']}"
            if result.get("raw_text"):
                line += f"\n    原文: {result['raw_text'][:200]}"
            return line

        if "content" in result:
            source = result.get("source_file", "未知来源")
            return f"[{index}] 来源: {source}\n    {result['content'][:300]}"

        return ""

    @staticmethod
    def _format_skill_match(skill: dict) -> str:
        confidence_icon = "✅" if skill["confidence"] == "high" else "💡"
        return (
            f"{confidence_icon} 【{skill['skill_name']}】（匹配度: {skill['score']:.0%}）"
            f" - {skill['description']}"
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
                    part for part in [
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
            chunk_type_map = {
                "text": "正文片段",
                "table": "表格片段",
                "note": "备注片段",
            }
            slide_index = cls._coerce_int(result.get("slide_index"))
            if slide_index is not None and slide_index <= 0:
                slide_index = None
            chunk_type = str(result.get("chunk_type") or "").strip().lower()
            chunk_type_label = chunk_type_map.get(chunk_type, chunk_type or "正文片段")
            chunk_index = cls._coerce_int(result.get("chunk_index"))
            if chunk_index is not None and chunk_index <= 0:
                chunk_index = None
            raw_char_start = cls._coerce_int(result.get("char_start"))
            raw_char_end = cls._coerce_int(result.get("char_end"))
            char_start = raw_char_start + 1 if raw_char_start is not None and raw_char_start >= 0 else None
            char_end = raw_char_end if raw_char_end is not None and raw_char_end > 0 else None

            title_parts = []
            if slide_index is not None:
                title_parts.append(f"第{slide_index}页")
            if chunk_type_label:
                title_parts.append(chunk_type_label)
            title = " · ".join(title_parts) if title_parts else f"知识片段 {index}"
            snippet = cls._normalize_text_snippet(result.get("content") or "")
            location_parts = []
            if chunk_index is not None:
                location_parts.append(f"片段 #{chunk_index}")
            if (
                char_start is not None
                and char_end is not None
                and char_end >= char_start
            ):
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

        citation.update({
            "title": title,
            "snippet": snippet,
            "location": location,
        })
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
            "location": f"匹配度 {skill.get('score', 0):.0%} · {skill.get('confidence', 'low')}",
        }

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
        }

    def fit_to_budget(self, max_chars: int) -> "AssembledContext":
        """按条目粒度裁剪上下文，保证被保留的条目都是完整的。"""
        if max_chars <= 0 or not self.has_context:
            return AssembledContext()

        fitted = AssembledContext()
        used = 0

        def _try_add_section(
            header: str,
            items: list[dict],
            formatter,
            target_attr: str,
        ) -> None:
            nonlocal used
            if not items:
                return

            section_items: list[dict] = []
            header_used = False
            header_cost = len(header) + 1

            for index, item in enumerate(items, 1):
                line = formatter(item, index) if formatter.__code__.co_argcount == 2 else formatter(item)
                if not line:
                    continue

                cost = len(line) + 1
                if not header_used:
                    cost += header_cost

                if used + cost > max_chars:
                    break

                if not header_used:
                    used += header_cost
                    header_used = True

                used += len(line) + 1
                section_items.append(item)

            if section_items:
                setattr(fitted, target_attr, section_items)

        _try_add_section(
            "📋 以下是相关的业务规则（Know-how），请在回答时检查是否涉及：",
            self.knowhow_rules,
            self._format_knowhow_rule,
            "knowhow_rules",
        )
        _try_add_section(
            "📚 以下是从知识库中检索到的相关参考信息，请在回答时优先参考：",
            self.knowledge_results[:5],
            self._format_knowledge_result,
            "knowledge_results",
        )
        _try_add_section(
            "🛠️ 检测到用户意图可能匹配以下技能（Skill），可按需引导用户使用：",
            self.matched_skills,
            self._format_skill_match,
            "matched_skills",
        )

        fitted.source_summary = fitted._build_source_summary()
        return fitted

    def to_prompt_suffix(self, max_chars: int | None = None) -> str:
        """将检索结果格式化为 system prompt 的追加段落。"""
        ctx = self.fit_to_budget(max_chars) if max_chars is not None else self
        sections: list[str] = []

        if ctx.knowhow_rules:
            lines = [
                "📋 以下是相关的业务规则（Know-how），请在回答时检查是否涉及：",
                *[
                    ctx._format_knowhow_rule(rule, index)
                    for index, rule in enumerate(ctx.knowhow_rules, 1)
                ],
            ]
            sections.append("\n".join(lines))

        if ctx.knowledge_results:
            lines = [
                "📚 以下是从知识库中检索到的相关参考信息，请在回答时优先参考：",
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
    """
    上下文组装器 - 根据用户查询并行检索：
      1. 知识库混合检索（SQLite 结构化 + LanceDB 语义）
      2. Know-how 规则全量注入（按权重降序，全部活跃规则）
      3. Skill 关键词意图匹配（top-1 high/medium 置信度）
    """

    async def assemble(
        self,
        user_query: str,
        mode: str = "copilot",
        category: Optional[str] = None,
    ) -> AssembledContext:
        """
        根据用户最新消息，组装增强上下文。
        仅在 copilot 模式下执行检索；其他模式返回空上下文。
        """
        ctx = AssembledContext()

        if mode != "copilot":
            return ctx

        if not user_query or len(user_query.strip()) < 2:
            return ctx

        # 并行执行三路检索（任一失败均静默降级）
        knowledge_task = asyncio.create_task(
            self._search_knowledge(user_query, category)
        )
        knowhow_task = asyncio.create_task(
            self._get_knowhow_rules(user_query)
        )
        skills_task = asyncio.create_task(
            self._match_skills(user_query)
        )

        ctx.knowledge_results = await knowledge_task
        ctx.knowhow_rules = await knowhow_task
        ctx.matched_skills = await skills_task

        ctx.source_summary = ctx._build_source_summary()

        if ctx.has_context:
            logger.info(f"[ContextAssembler] 已组装上下文: {ctx.source_summary}")
        else:
            logger.debug("[ContextAssembler] 未检索到任何上下文，将直接使用基础 system prompt")

        return ctx

    async def _search_knowledge(
        self, query: str, category: Optional[str] = None,
    ) -> List[dict]:
        """检索知识库（结构化 + 语义），合并去重"""
        try:
            results = await hybrid_search.search(
                query=query, category=category, limit=5,
            )
            combined: list[dict] = []
            seen_ids: set[str] = set()
            _dedup_counter = 0  # 用于无 id 语义结果的唯一占位键

            for r in results.get("structured", []):
                rid = str(r.get("id", ""))
                if not rid:
                    rid = f"_s{_dedup_counter}"
                    _dedup_counter += 1
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    combined.append(r)

            for r in results.get("semantic", []):
                # 语义结果可能用 chunk_id 或 id
                rid = str(r.get("chunk_id") or r.get("id") or "")
                if not rid:
                    rid = f"_sem{_dedup_counter}"
                    _dedup_counter += 1
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    combined.append(r)

            logger.debug(
                f"[ContextAssembler] 知识库检索完成: "
                f"结构化={len(results.get('structured', []))} "
                f"语义={len(results.get('semantic', []))} "
                f"去重后={len(combined)}"
            )
            return combined[:5]
        except Exception as e:
            logger.warning(f"[ContextAssembler] 知识库检索失败: {e}", exc_info=True)
            return []

    async def _get_knowhow_rules(self, query: str) -> List[dict]:
        """获取全部活跃 Know-how 规则（按权重降序，✅ Issue 3: 不限数量）"""
        try:
            rules = await knowhow_service.list_rules(active_only=True)
            logger.debug(f"[ContextAssembler] Know-how 规则获取完成: 共 {len(rules)} 条活跃规则")
            # ✅ Issue 3: 移除 [:8] 限制，注入全部活跃规则
            return rules
        except Exception as e:
            logger.warning(f"[ContextAssembler] Know-how 规则获取失败: {e}", exc_info=True)
            return []

    async def _match_skills(self, query: str) -> List[dict]:
        """✅ Issue 2: 根据用户 query 匹配 Skill，返回 high/medium 置信度的结果"""
        try:
            # 确保 skill_manager 已初始化
            if not skill_manager._loaded:
                await skill_manager.initialize()

            skills = skill_manager.list_skills()
            if not skills:
                logger.debug("[ContextAssembler] 未发现任何已加载的 Skill，跳过匹配")
                return []

            matches = skill_matcher.match(query, skills, top_k=3)
            # 只保留置信度 high 或 medium 的结果（score >= 0.6）
            relevant = [
                {
                    "skill_id": m.skill.id,
                    "skill_name": m.skill.name,
                    "description": m.skill.description[:150],
                    "score": m.score,
                    "confidence": m.confidence,
                    "matched_keywords": m.matched_keywords,
                }
                for m in matches
                if m.confidence in ("high", "medium")
            ]
            if relevant:
                logger.debug(
                    f"[ContextAssembler] Skill 匹配完成: "
                    f"命中 {len(relevant)}/{len(skills)} 个 Skill"
                )
            return relevant
        except Exception as e:
            logger.warning(f"[ContextAssembler] Skill 匹配失败: {e}", exc_info=True)
            return []


# 全局单例
context_assembler = ContextAssembler()
