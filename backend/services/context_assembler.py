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

    def to_prompt_suffix(self) -> str:
        """将检索结果格式化为 system prompt 的追加段落"""
        parts: list[str] = []

        # ── 知识库检索结果 ──
        if self.knowledge_results:
            parts.append("\n\n📚 以下是从知识库中检索到的相关参考信息，请在回答时优先参考：")
            for i, r in enumerate(self.knowledge_results[:5], 1):
                # 结构化采购记录
                if "item_name" in r:
                    line = f"[{i}] {r.get('category', '')} - {r['item_name']}"
                    if r.get("supplier"):
                        line += f"（供应商: {r['supplier']}）"
                    if r.get("unit_price"):
                        line += f" 单价: {r['unit_price']}"
                    if r.get("raw_text"):
                        line += f"\n    原文: {r['raw_text'][:200]}"
                    parts.append(line)
                # 语义检索的文本块
                elif "content" in r:
                    source = r.get("source_file", "未知来源")
                    parts.append(f"[{i}] 来源: {source}\n    {r['content'][:300]}")

        # ── Know-how 规则（✅ Issue 3: 移除 [:8] 截断，注入全部活跃规则）──
        if self.knowhow_rules:
            parts.append("\n\n📋 以下是相关的业务规则（Know-how），请在回答时检查是否涉及：")
            for i, rule in enumerate(self.knowhow_rules, 1):
                weight_icon = "⚠️" if rule.get("weight", 0) >= 3 else "ℹ️"
                parts.append(f"{weight_icon} [{i}] {rule['rule_text']}")

        # ── Skill 匹配结果（✅ Issue 2: 新增 Skill 提示段落）──
        if self.matched_skills:
            parts.append("\n\n🛠️ 检测到用户意图可能匹配以下技能（Skill），可按需引导用户使用：")
            for s in self.matched_skills:
                confidence_icon = "✅" if s["confidence"] == "high" else "💡"
                parts.append(
                    f"{confidence_icon} 【{s['skill_name']}】（匹配度: {s['score']:.0%}）"
                    f" - {s['description']}"
                )

        return "\n".join(parts)


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

        # 生成来源摘要（用于日志）
        sources = []
        if ctx.knowledge_results:
            sources.append(f"知识库({len(ctx.knowledge_results)}条)")
        if ctx.knowhow_rules:
            sources.append(f"Know-how({len(ctx.knowhow_rules)}条)")
        if ctx.matched_skills:
            sources.append(f"Skill({len(ctx.matched_skills)}个)")
        ctx.source_summary = " + ".join(sources) if sources else ""

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

