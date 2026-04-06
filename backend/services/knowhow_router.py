from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Literal

from services.knowhow_service import knowhow_service
from services.llm_service import LLMService
from services.retrieval_planner import RetrievalPlannerSettings
from utils.text_utils import extract_han_segments

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowhowRouteDecision:
    should_retrieve: bool
    categories: tuple[str, ...] = ()
    strategy: Literal[
        "heuristic_skip",
        "heuristic_route",
        "heuristic_rule_match",
        "heuristic_category_match",
        "llm_route",
        "llm_skip",
    ] = "heuristic_skip"
    rationale: str = ""
    confidence: Literal["low", "medium", "high"] = "low"
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowhowCategoryProfile:
    name: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    example_queries: tuple[str, ...] = ()
    applies_to: str = ""
    keywords: tuple[str, ...] = ()
    sample_rules: tuple[str, ...] = ()
    searchable_text: str = ""


@dataclass(frozen=True)
class KnowhowRoutingResult:
    decision: KnowhowRouteDecision
    rules: tuple[dict, ...] = ()
    candidate_categories: tuple[str, ...] = ()


class KnowhowRouter:
    SMALL_TALK_HINTS: tuple[str, ...] = (
        "你好",
        "您好",
        "hello",
        "hi",
        "在吗",
        "你是谁",
        "你能做什么",
        "介绍一下你自己",
        "谢谢",
        "谢了",
    )
    STRONG_RULE_HINTS: tuple[str, ...] = (
        "资质",
        "资格",
        "认证",
        "合规",
        "审批",
        "审批流",
        "门槛",
        "流程要求",
        "规范",
        "规则",
        "政策",
        "制度",
        "风险",
        "审查",
        "审计",
        "招标",
        "投标",
        "单一来源",
        "single source",
        "multi-source",
        "补充说明",
        "必须",
        "应当",
        "是否合规",
        "是否合理",
    )
    DECISION_HINTS: tuple[str, ...] = (
        "是否",
        "要不要",
        "需不需要",
        "能不能",
        "可不可以",
        "合不合理",
        "合不合规",
        "有没有风险",
        "是否需要",
        "是否应该",
        "怎么判断",
    )
    DOC_ONLY_HINTS: tuple[str, ...] = (
        "总结",
        "概括",
        "提炼",
        "翻译",
        "润色",
        "改写",
        "解释这份文件",
        "分析这份文件",
        "分析内容",
        "看下附件",
    )
    STOPWORDS: set[str] = {
        "请问", "帮我", "帮忙", "看看", "看下", "分析", "说明", "介绍", "告诉我",
        "关于", "这个", "这份", "一个", "一种", "是否", "怎么", "如何", "哪些",
        "什么", "需要", "里面", "内容", "材料", "文件", "文档", "问题", "情况",
        "重点", "有无", "有没有",
    }
    WEAK_TERMS: set[str] = {"合理", "说明", "要求", "问题", "情况", "内容", "材料", "文件", "重点", "需要"}
    TERM_ALIASES: dict[str, str] = {
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

    def __init__(self, llm_service: LLMService | None = None) -> None:
        self._llm_service = llm_service or LLMService()

    async def retrieve_rules(
        self,
        query: str,
        rules: list[dict],
        *,
        category_profiles: list[dict] | None = None,
        limit: int = 5,
        settings: RetrievalPlannerSettings | None = None,
    ) -> KnowhowRoutingResult:
        decision, candidate_categories = await self.route(
            query,
            rules,
            category_profiles=category_profiles,
            settings=settings,
        )
        if not decision.should_retrieve:
            return KnowhowRoutingResult(
                decision=decision,
                rules=(),
                candidate_categories=tuple(candidate_categories),
            )

        query_terms = self._extract_terms(query)
        query_text = self._normalize_text(query)
        routed_categories = set(decision.categories)
        filtered_rules = [
            rule for rule in rules
            if not routed_categories or str(rule.get("category") or "") in routed_categories
        ]

        scored_rules: list[tuple[float, dict]] = []
        for rule in filtered_rules:
            score = self._score_rule(
                query_terms=query_terms,
                query_text=query_text,
                rule=rule,
                routed_categories=routed_categories,
            )
            if score < 2.4:
                continue
            enriched_rule = dict(rule)
            enriched_rule["route_strategy"] = decision.strategy
            enriched_rule["route_confidence"] = decision.confidence
            enriched_rule["route_rationale"] = decision.rationale
            enriched_rule["route_categories"] = list(decision.categories)
            scored_rules.append((score, enriched_rule))

        scored_rules.sort(
            key=lambda item: (
                item[0],
                float(item[1].get("weight", 0)),
                float(item[1].get("hit_count", 0)),
            ),
            reverse=True,
        )
        top_score = scored_rules[0][0] if scored_rules else 0.0
        score_cutoff = max(2.4, top_score * 0.66)
        filtered_scored_rules = [
            (score, rule)
            for score, rule in scored_rules
            if score >= score_cutoff
        ] or scored_rules
        selected_rules = [rule for _, rule in filtered_scored_rules[: max(limit, 6)]]
        if settings and settings.is_configured and selected_rules:
            selected_rules = await self._judge_rules_with_llm(
                query=query,
                rules=selected_rules,
                settings=settings,
                limit=limit,
            )
        return KnowhowRoutingResult(
            decision=decision,
            rules=tuple(selected_rules[:limit]),
            candidate_categories=tuple(candidate_categories),
        )

    async def route(
        self,
        query: str,
        rules: list[dict],
        *,
        category_profiles: list[dict] | None = None,
        settings: RetrievalPlannerSettings | None = None,
    ) -> tuple[KnowhowRouteDecision, list[str]]:
        normalized_query = self._normalize_text(query)
        query_terms = self._extract_terms(query)
        profiles = self._build_category_profiles(rules, category_profiles or [])
        ranked_categories = self._rank_categories(
            query_terms=query_terms,
            query_text=normalized_query,
            profiles=profiles,
        )
        candidate_categories = [name for _, name in ranked_categories[:3]]
        ranked_rule_categories = self._rank_rule_categories(
            query_terms=query_terms,
            query_text=normalized_query,
            rules=rules,
        )
        rule_candidate_categories = [name for _, name in ranked_rule_categories[:3]]
        if not candidate_categories and rule_candidate_categories:
            candidate_categories = rule_candidate_categories

        if not normalized_query or not query_terms or (not profiles and not rules):
            return (
                KnowhowRouteDecision(
                    should_retrieve=False,
                    strategy="heuristic_skip",
                    rationale="missing_query_or_profiles",
                    notes=("no_terms_or_profiles",),
                ),
                candidate_categories,
            )

        gate_result = self._hard_skip_gate(query_text=normalized_query, ranked_categories=ranked_categories)
        if gate_result is not None:
            return gate_result, candidate_categories

        planner_settings = settings or RetrievalPlannerSettings()
        if planner_settings.is_configured and profiles:
            try:
                llm_decision = await self._route_with_llm(
                    query=query,
                    profiles=profiles,
                    ranked_categories=ranked_categories,
                    settings=planner_settings,
                )
                resolved_categories = candidate_categories or rule_candidate_categories
                if llm_decision.should_retrieve and not llm_decision.categories and resolved_categories:
                    llm_decision = KnowhowRouteDecision(
                        should_retrieve=True,
                        categories=(resolved_categories[0],),
                        strategy="llm_route",
                        rationale=llm_decision.rationale or "llm_selected_knowhow",
                        confidence=llm_decision.confidence,
                        notes=llm_decision.notes + ("fallback_to_top_category",),
                    )
                return llm_decision, candidate_categories
            except Exception as exc:
                logger.info("[KnowhowRouter] LLM route fallback: %s", exc)

        gate_result = self._heuristic_gate(
            query_text=normalized_query,
            query_terms=query_terms,
            ranked_categories=ranked_categories,
            ranked_rule_categories=ranked_rule_categories,
        )
        if gate_result is not None:
            return gate_result, candidate_categories

        top_score = ranked_categories[0][0] if ranked_categories else 0.0
        if top_score >= 3.8 and candidate_categories:
            return (
                KnowhowRouteDecision(
                    should_retrieve=True,
                    categories=tuple(candidate_categories[:2]),
                    strategy="heuristic_category_match",
                    rationale="high_category_match",
                    confidence="medium",
                    notes=("llm_route_unavailable",),
                ),
                candidate_categories,
            )

        return (
            KnowhowRouteDecision(
                should_retrieve=False,
                strategy="heuristic_skip",
                rationale="query_not_specific_enough_for_knowhow",
                confidence="low",
                notes=("ambiguous_without_confident_category",),
            ),
            candidate_categories,
        )

    def _hard_skip_gate(
        self,
        *,
        query_text: str,
        ranked_categories: list[tuple[float, str]],
    ) -> KnowhowRouteDecision | None:
        if len(query_text) <= 18 and self._contains_any(query_text, self.SMALL_TALK_HINTS):
            return KnowhowRouteDecision(
                should_retrieve=False,
                strategy="heuristic_skip",
                rationale="small_talk",
                confidence="high",
                notes=("skip_small_talk",),
            )

        top_score = ranked_categories[0][0] if ranked_categories else 0.0
        has_strong_rule_hint = self._contains_any(query_text, self.STRONG_RULE_HINTS)
        doc_only = self._contains_any(query_text, self.DOC_ONLY_HINTS) and not has_strong_rule_hint
        if doc_only and top_score < 3.2:
            return KnowhowRouteDecision(
                should_retrieve=False,
                strategy="heuristic_skip",
                rationale="document_analysis_without_rule_signal",
                confidence="medium",
                notes=("skip_doc_only_query",),
            )
        return None

    def _heuristic_gate(
        self,
        *,
        query_text: str,
        query_terms: list[str],
        ranked_categories: list[tuple[float, str]],
        ranked_rule_categories: list[tuple[float, str]],
    ) -> KnowhowRouteDecision | None:
        del query_terms
        has_strong_rule_hint = self._contains_any(query_text, self.STRONG_RULE_HINTS)
        has_decision_hint = self._contains_any(query_text, self.DECISION_HINTS)
        candidate_categories = [name for _, name in ranked_categories[:3]]
        top_score = ranked_categories[0][0] if ranked_categories else 0.0
        rule_candidate_categories = [name for _, name in ranked_rule_categories[:3]]
        top_rule_score = ranked_rule_categories[0][0] if ranked_rule_categories else 0.0

        if has_strong_rule_hint and candidate_categories:
            return KnowhowRouteDecision(True, tuple(candidate_categories[:2]), "heuristic_route", "strong_rule_signal", "high", ("strong_rule_hint",))
        if has_strong_rule_hint:
            return KnowhowRouteDecision(True, tuple(rule_candidate_categories[:2]), "heuristic_route", "strong_rule_signal_without_category_match", "medium" if rule_candidate_categories else "high", ("strong_rule_hint", "no_category_match"))
        if top_rule_score >= 4.2:
            return KnowhowRouteDecision(True, tuple(rule_candidate_categories[:2]), "heuristic_rule_match", "direct_rule_text_match", "medium" if top_rule_score < 5.6 else "high", ("rule_text_match",))
        if has_decision_hint and top_score >= 3.4 and candidate_categories:
            return KnowhowRouteDecision(True, (candidate_categories[0],), "heuristic_category_match", "decision_question_with_category_match", "medium", ("decision_hint",))
        if top_score >= 5.2 and candidate_categories:
            return KnowhowRouteDecision(True, (candidate_categories[0],), "heuristic_category_match", "exact_category_match", "high", ("top_category_exact_match",))
        return None

    def _rank_rule_categories(
        self,
        *,
        query_terms: list[str],
        query_text: str,
        rules: Iterable[dict],
    ) -> list[tuple[float, str]]:
        category_scores: dict[str, float] = {}
        for rule in rules:
            score = self._score_rule(
                query_terms=query_terms,
                query_text=query_text,
                rule=rule,
                routed_categories=set(),
            )
            if score <= 0:
                continue
            category = str(rule.get("category") or "").strip()
            if category:
                category_scores[category] = max(category_scores.get(category, 0.0), score)

        ranked = [(score, category) for category, score in category_scores.items()]
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked

    async def _route_with_llm(
        self,
        *,
        query: str,
        profiles: list[KnowhowCategoryProfile],
        ranked_categories: list[tuple[float, str]],
        settings: RetrievalPlannerSettings,
    ) -> KnowhowRouteDecision:
        top_candidates = [name for _, name in ranked_categories[:6]]
        ordered_profiles = [profile for profile in profiles if not top_candidates or profile.name in top_candidates]
        if not ordered_profiles:
            ordered_profiles = profiles[:6]
        category_block = "\n".join(self._format_profile_for_llm(profile) for profile in ordered_profiles[:6])
        response = await self._llm_service.chat(
            messages=[
                {"role": "system", "content": self._build_llm_system_prompt()},
                {"role": "user", "content": f"User query:\n{query}\n\nCandidate categories:\n{category_block}"},
            ],
            model=settings.model.strip() or "gpt-4o",
            temperature=0.1,
            max_tokens=500,
            api_url=settings.api_url,
            api_key=settings.api_key,
        )
        text = self._llm_service.extract_text_content(response)
        if not text:
            raise ValueError("empty knowhow routing response")
        payload = json.loads(self._extract_json_payload(text))
        available = {profile.name for profile in ordered_profiles}
        raw_categories = payload.get("categories") or []
        categories = tuple(category for category in raw_categories if isinstance(category, str) and category in available)[:3]
        confidence = str(payload.get("confidence") or "medium").lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = "medium"
        return KnowhowRouteDecision(
            should_retrieve=bool(payload.get("use_knowhow")),
            categories=categories,
            strategy="llm_route" if payload.get("use_knowhow") else "llm_skip",
            rationale=" ".join(str(payload.get("rationale") or "").split()) or "llm_route_decision",
            confidence=confidence,
            notes=("llm_routed",),
        )

    async def _judge_rules_with_llm(
        self,
        *,
        query: str,
        rules: list[dict],
        settings: RetrievalPlannerSettings,
        limit: int,
    ) -> list[dict]:
        candidate_rules = rules[:6]
        payload = [
            {
                "id": str(rule.get("id") or ""),
                "category": str(rule.get("category") or ""),
                "title": str(rule.get("title") or ""),
                "rule_text": str(rule.get("rule_text") or ""),
                "trigger_terms": list(rule.get("trigger_terms") or []),
                "applies_when": str(rule.get("applies_when") or ""),
                "not_applies_when": str(rule.get("not_applies_when") or ""),
            }
            for rule in candidate_rules
        ]
        response = await self._llm_service.chat(
            messages=[
                {"role": "system", "content": self._build_llm_rule_judge_prompt()},
                {"role": "user", "content": json.dumps({"query": query, "rules": payload, "limit": max(1, limit)}, ensure_ascii=False)},
            ],
            model=settings.model.strip() or "gpt-4o",
            temperature=0.1,
            max_tokens=700,
            api_url=settings.api_url,
            api_key=settings.api_key,
        )
        text = self._llm_service.extract_text_content(response)
        if not text:
            return candidate_rules[:limit]
        data = json.loads(self._extract_json_payload(text))
        selected_ids = [str(item).strip() for item in (data.get("selected_ids") or []) if str(item).strip()]
        if not selected_ids:
            return candidate_rules[:limit]
        selected = [rule for rule in candidate_rules if str(rule.get("id") or "") in selected_ids]
        return selected[:limit] or candidate_rules[:limit]

    def _build_category_profiles(
        self,
        rules: Iterable[dict],
        category_profiles: list[dict],
    ) -> list[KnowhowCategoryProfile]:
        grouped_rules: dict[str, list[dict]] = {}
        for rule in rules:
            category = str(rule.get("category") or "").strip() or "未分类"
            grouped_rules.setdefault(category, []).append(rule)

        category_profile_map = {
            str(item.get("name") or "").strip(): item
            for item in category_profiles
            if str(item.get("name") or "").strip()
        }

        profiles: list[KnowhowCategoryProfile] = []
        for category in sorted(set(grouped_rules) | set(category_profile_map)):
            category_rules = grouped_rules.get(category, [])
            profile_payload = category_profile_map.get(category, {})
            keyword_counter: Counter[str] = Counter()
            ranked_rules = sorted(
                category_rules,
                key=lambda item: (float(item.get("weight", 0)), float(item.get("hit_count", 0))),
                reverse=True,
            )
            for rule in ranked_rules:
                keyword_counter.update(self._extract_rule_keywords(rule))
                keyword_counter.update(self._extract_terms(str(rule.get("rule_text") or "")))
                keyword_counter.update(self._extract_terms(str(rule.get("title") or "")))

            category_terms = self._extract_terms(category)
            alias_terms = self._extract_terms(" ".join(profile_payload.get("aliases") or []))
            example_query_terms = self._extract_terms(" ".join(profile_payload.get("example_queries") or []))
            keyword_counter.update(category_terms)
            keyword_counter.update(alias_terms)
            keyword_counter.update(example_query_terms)

            top_keywords = tuple(keyword for keyword, _ in keyword_counter.most_common(12) if len(keyword) >= 2)
            sample_rules = tuple(
                " ".join(str(rule.get("rule_text") or "").split())[:80]
                for rule in ranked_rules[:3]
                if str(rule.get("rule_text") or "").strip()
            )
            searchable_text = self._normalize_text(
                " ".join(
                    [
                        category,
                        str(profile_payload.get("description") or ""),
                        " ".join(profile_payload.get("aliases") or []),
                        " ".join(profile_payload.get("example_queries") or []),
                        str(profile_payload.get("applies_to") or ""),
                        *category_terms,
                        *alias_terms,
                        *example_query_terms,
                        *top_keywords,
                        *sample_rules,
                    ]
                )
            )
            profiles.append(
                KnowhowCategoryProfile(
                    name=category,
                    description=str(profile_payload.get("description") or ""),
                    aliases=tuple(str(item).strip() for item in (profile_payload.get("aliases") or []) if str(item).strip()),
                    example_queries=tuple(str(item).strip() for item in (profile_payload.get("example_queries") or []) if str(item).strip()),
                    applies_to=str(profile_payload.get("applies_to") or ""),
                    keywords=top_keywords,
                    sample_rules=sample_rules,
                    searchable_text=searchable_text,
                )
            )

        profiles.sort(key=lambda item: item.name)
        return profiles

    def _rank_categories(
        self,
        *,
        query_terms: list[str],
        query_text: str,
        profiles: list[KnowhowCategoryProfile],
    ) -> list[tuple[float, str]]:
        ranked: list[tuple[float, str]] = []
        for profile in profiles:
            score = 0.0
            normalized_name = self._normalize_text(profile.name)
            if normalized_name and normalized_name in query_text:
                score += 5.0

            matched_terms: set[str] = set()
            for term in query_terms:
                canonical_term = self.TERM_ALIASES.get(term, term)
                if canonical_term in matched_terms or len(canonical_term) < 2:
                    continue
                if canonical_term in profile.keywords:
                    score += 2.6
                    matched_terms.add(canonical_term)
                    continue
                if canonical_term in normalized_name:
                    score += 2.1
                    matched_terms.add(canonical_term)
                    continue
                if canonical_term in profile.searchable_text:
                    score += 1.2
                    matched_terms.add(canonical_term)

            if query_text and query_text in profile.searchable_text:
                score += 2.8
            if score > 0:
                ranked.append((score, profile.name))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked

    def _score_rule(
        self,
        *,
        query_terms: list[str],
        query_text: str,
        rule: dict,
        routed_categories: set[str],
    ) -> float:
        rule_text = str(rule.get("rule_text") or "")
        if not rule_text:
            return 0.0

        rule_text_normalized = self._build_rule_searchable_text(rule)
        category_text = self._normalize_text(str(rule.get("category") or ""))
        rule_keywords = set(self._extract_rule_keywords(rule))
        exclude_terms = {
            self._normalize_text(term)
            for term in (rule.get("exclude_terms") or [])
            if self._normalize_text(term)
        }

        score = 0.0
        strong_match_count = 0
        weak_match_count = 0
        if routed_categories and str(rule.get("category") or "") in routed_categories:
            score += 0.9

        matched_terms: set[str] = set()
        for term in query_terms:
            canonical_term = self.TERM_ALIASES.get(term, term)
            if len(canonical_term) < 2 or canonical_term in matched_terms:
                continue
            is_weak_term = canonical_term in self.WEAK_TERMS
            if canonical_term in rule_keywords:
                score += 1.0 if is_weak_term else 2.8
                if is_weak_term:
                    weak_match_count += 1
                else:
                    strong_match_count += 1
                matched_terms.add(canonical_term)
                continue
            if canonical_term in rule_text_normalized:
                score += 0.6 if is_weak_term else 2.0
                if is_weak_term:
                    weak_match_count += 1
                else:
                    strong_match_count += 1
                matched_terms.add(canonical_term)
                continue
            if canonical_term in category_text:
                score += 0.4 if is_weak_term else 0.8
                if is_weak_term:
                    weak_match_count += 1
                else:
                    strong_match_count += 1
                matched_terms.add(canonical_term)

        for keyword in rule_keywords:
            if len(keyword) < 2 or keyword in matched_terms or keyword not in query_text:
                continue
            is_weak_term = keyword in self.WEAK_TERMS
            score += 0.8 if is_weak_term else 2.2
            if is_weak_term:
                weak_match_count += 1
            else:
                strong_match_count += 1
            matched_terms.add(keyword)

        has_exact_match = len(query_text) >= 4 and query_text in rule_text_normalized
        if strong_match_count == 0 and weak_match_count < 2 and not has_exact_match and not routed_categories:
            return 0.0

        if exclude_terms and any(term in query_text for term in exclude_terms):
            score -= 1.8
        if has_exact_match:
            score += 3.2

        score += float(rule.get("weight", 0)) * 0.18
        score += float(rule.get("hit_count", 0)) * 0.01
        return score

    def _extract_rule_keywords(self, rule: dict) -> list[str]:
        rule_text = " ".join(
            [
                str(rule.get("title") or ""),
                str(rule.get("rule_text") or ""),
                str(rule.get("applies_when") or ""),
                str(rule.get("not_applies_when") or ""),
                " ".join(rule.get("trigger_terms") or []),
                " ".join(rule.get("examples") or []),
            ]
        )
        keywords = [
            keyword.lower()
            for keyword in knowhow_service._extract_keywords(rule_text)
            if len(str(keyword).strip()) >= 2
        ]
        keywords.extend(self._extract_terms(str(rule.get("category") or "")))
        keywords.extend(self._extract_terms(" ".join(rule.get("trigger_terms") or [])))
        return keywords

    def _build_rule_searchable_text(self, rule: dict) -> str:
        return self._normalize_text(
            " ".join(
                [
                    str(rule.get("title") or ""),
                    str(rule.get("rule_text") or ""),
                    str(rule.get("applies_when") or ""),
                    str(rule.get("not_applies_when") or ""),
                    " ".join(rule.get("trigger_terms") or []),
                    " ".join(rule.get("examples") or []),
                    str(rule.get("category") or ""),
                ]
            )
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = " ".join((text or "").lower().split())
        for raw, canonical in KnowhowRouter.TERM_ALIASES.items():
            normalized = normalized.replace(raw, canonical)
        return normalized

    def _extract_terms(self, text: str) -> list[str]:
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        candidates: list[str] = []
        candidates.extend(
            term.strip()
            for term in re.split(r"[\s,.;:!?，。；：！？、()（）【】\[\]\"'`]+", normalized)
            if len(term.strip()) >= 2
        )
        candidates.extend(re.findall(r"[a-z0-9][a-z0-9_.-]{1,}", normalized))

        for segment in extract_han_segments(normalized, min_length=2):
            cleaned = segment
            for stopword in sorted(self.STOPWORDS, key=len, reverse=True):
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
        return expanded[:30]

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _format_profile_for_llm(profile: KnowhowCategoryProfile) -> str:
        aliases = ", ".join(profile.aliases[:4]) or "none"
        keywords = ", ".join(profile.keywords[:6]) or "none"
        examples = " | ".join(profile.example_queries[:2]) or "none"
        sample_rules = " | ".join(profile.sample_rules[:2]) or "none"
        applies_to = profile.applies_to or "unspecified"
        description = profile.description or "no description"
        return (
            f"- {profile.name}\n"
            f"  description: {description}\n"
            f"  aliases: {aliases}\n"
            f"  applies_to: {applies_to}\n"
            f"  keywords: {keywords}\n"
            f"  example_queries: {examples}\n"
            f"  sample_rules: {sample_rules}"
        )

    @staticmethod
    def _build_llm_system_prompt() -> str:
        return """
You are the knowhow routing layer for a chat system.
Decide whether the user message should consult the knowhow library, and if so which candidate categories are relevant.

Return JSON only. Do not use markdown. Do not explain outside JSON.
Schema:
{
  "use_knowhow": true,
  "categories": ["category_name"],
  "confidence": "low | medium | high",
  "rationale": "short reason"
}

Rules:
- Greetings, small talk, self-introduction, thanks, and pure summarization / translation / polishing requests usually mean "use_knowhow": false.
- Questions about qualification, compliance, approval flow, risk, single source, whether something is reasonable, or whether supporting rationale is sufficient usually mean "use_knowhow": true.
- Only choose categories from the provided candidates.
- Return at most 3 categories.
- If use_knowhow is false, return an empty categories array.
""".strip()

    @staticmethod
    def _build_llm_rule_judge_prompt() -> str:
        return """
You are the final judge for knowhow rule applicability.
You will receive a user query and a short list of candidate rules that were already retrieved by heuristics.
Select only the rules that are genuinely applicable to answering the user's question.

Return JSON only. Do not use markdown.
Schema:
{
  "selected_ids": ["rule-id-1", "rule-id-2"],
  "rationale": "short reason"
}

Rules:
- Prefer precision over recall.
- Do not select rules that are only loosely related.
- Keep the number of selected rules small and useful.
- Never invent rule ids. Only return ids that exist in the candidate list.
- If none are applicable, return an empty selected_ids array.
""".strip()

    @staticmethod
    def _extract_json_payload(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError(f"router response did not contain JSON: {text[:200]}")
        return stripped[start:end + 1]


knowhow_router = KnowhowRouter()
