"""
Skill 匹配引擎 - 根据用户输入找到最佳 Skill
遵循 PRD §5.2 匹配优先级：
  1. 精确关键词命中 → 直接执行
  2. 语义相似度 > 0.85 → 确认后执行
  3. 语义相似度 0.6-0.85 → 候选列表
  4. 无匹配 → 建议创建新 Skill
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from services.skill_parser import SkillMeta


@dataclass
class MatchResult:
    """Skill 匹配结果"""
    skill: SkillMeta
    score: float              # 综合得分 0-1
    match_type: str           # keyword / semantic / none
    matched_keywords: list[str] = field(default_factory=list)
    confidence: str = ""      # high / medium / low


class SkillMatcher:
    """
    多阶段 Skill 匹配引擎
    Phase 2: 关键词匹配（已实现）+ 语义匹配接口（预留）
    """

    # 匹配阈值（PRD §5.2）
    THRESHOLD_HIGH = 0.85     # 直接执行
    THRESHOLD_MEDIUM = 0.6    # 候选列表

    def match(self, query: str, skills: list[SkillMeta], top_k: int = 3) -> list[MatchResult]:
        """
        对用户输入进行多阶段匹配，返回按得分排序的候选列表
        Stage 1: 关键词精确匹配
        Stage 2: TODO - 语义相似度（需 Embedding Service）
        Stage 3: TODO - LLM 确认（需 LLM Service）
        """
        results: list[MatchResult] = []

        for skill in skills:
            result = self._keyword_match(query, skill)
            if result.score > 0:
                results.append(result)

        # 按得分降序排列
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _keyword_match(self, query: str, skill: SkillMeta) -> MatchResult:
        """
        关键词匹配 - 检查用户输入是否包含 Skill 的触发关键词
        得分规则：
          - 每命中一个关键词 +0.3（上限 1.0）
          - 名称完全包含 +0.2
          - 描述关键词命中 +0.1
        """
        query_lower = query.lower()
        score = 0.0
        matched: list[str] = []

        # 1. 关键词匹配（权重最高）
        for kw in skill.keywords:
            kw_lower = kw.lower()
            if kw_lower in query_lower:
                # 完整关键词命中
                score += 0.3
                matched.append(kw)
            elif len(kw_lower) >= 4:
                # 长关键词的部分匹配（至少2字符重叠）
                overlap = sum(1 for c in kw_lower if c in query_lower)
                if overlap >= len(kw_lower) * 0.6:
                    score += 0.15
                    matched.append(f"[partial]{kw}")

        # 2. Skill 名称匹配
        if skill.name and skill.name.lower() in query_lower:
            score += 0.2
            matched.append(f"[name]{skill.name}")

        # 3. 描述关键词匹配（提取描述中的关键名词）
        if skill.description:
            desc_keywords = self._extract_keywords(skill.description)
            for dk in desc_keywords:
                if dk in query_lower and len(dk) >= 2:
                    score += 0.1
                    matched.append(f"[desc]{dk}")

        # 4. 输入类型匹配（检查是否提到文件类型）
        for ft in skill.input_types:
            if ft.lower() in query_lower:
                score += 0.15
                matched.append(f"[type]{ft}")

        score = min(score, 1.0)

        # 判定置信度
        if score >= self.THRESHOLD_HIGH:
            confidence = "high"
        elif score >= self.THRESHOLD_MEDIUM:
            confidence = "medium"
        else:
            confidence = "low"

        return MatchResult(
            skill=skill,
            score=score,
            match_type="keyword" if score > 0 else "none",
            matched_keywords=matched,
            confidence=confidence,
        )

    def _extract_keywords(self, text: str) -> list[str]:
        """从文本中提取关键词（简单分词，取长度>=2的词）"""
        # 中文按标点分割，英文按空格分割
        segments = re.split(r'[，。、；：！？\s,.:;!?\n]+', text)
        keywords: list[str] = []
        for seg in segments:
            seg = seg.strip()
            if len(seg) >= 2:
                keywords.append(seg.lower())
        return keywords

    async def match_with_semantic(
        self, query: str, skills: list[SkillMeta],
        embedding_fn: Optional[object] = None, top_k: int = 3,
    ) -> list[MatchResult]:
        """
        带语义匹配的完整匹配流程（Phase 2 后续实现）
        TODO: 集成 Embedding Service 进行语义相似度计算
        当前降级为纯关键词匹配
        """
        # Phase 2: 先用关键词匹配
        results = self.match(query, skills, top_k=top_k)

        # TODO: Phase 2 后续 - 对关键词未命中的 Skill 进行语义匹配
        # if embedding_fn:
        #     query_vec = await embedding_fn(query)
        #     for skill in skills:
        #         if skill.id not in {r.skill.id for r in results}:
        #             skill_vec = await embedding_fn(skill.description)
        #             sim = cosine_similarity(query_vec, skill_vec)
        #             if sim > self.THRESHOLD_MEDIUM:
        #                 results.append(MatchResult(...))

        return results


# 全局单例
skill_matcher = SkillMatcher()

