from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

import httpx
from pydantic import BaseModel, Field, model_validator

from services.llm_service import LLMService

logger = logging.getLogger(__name__)

RetrievalSurface = Literal["knowledge", "knowhow", "skill"]
_SURFACE_ORDER: tuple[RetrievalSurface, ...] = ("knowledge", "knowhow", "skill")
_DEFAULT_LIMITS: dict[RetrievalSurface, int] = {
    "knowledge": 5,
    "knowhow": 4,
    "skill": 3,
}


@dataclass(frozen=True)
class RetrievalPlannerSettings:
    api_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url.strip() and self.api_key.strip())


class RetrievalPlanAction(BaseModel):
    surface: RetrievalSurface
    query: str = Field(min_length=2, max_length=120)
    limit: int = Field(default=5, ge=1, le=10)
    required: bool = False
    rationale: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def normalize_values(self) -> "RetrievalPlanAction":
        self.query = " ".join(self.query.split())
        self.rationale = " ".join(self.rationale.split())
        return self


class RetrievalPlan(BaseModel):
    strategy: Literal["llm", "fallback"] = "fallback"
    intent: str = ""
    normalized_query: str = ""
    actions: list[RetrievalPlanAction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_values(self) -> "RetrievalPlan":
        self.intent = " ".join(self.intent.split())
        self.normalized_query = " ".join(self.normalized_query.split())
        self.notes = [" ".join(str(note).split()) for note in self.notes if str(note).strip()]

        deduped_actions: list[RetrievalPlanAction] = []
        seen: set[tuple[str, str]] = set()
        for action in self.actions:
            key = (action.surface, action.query)
            if key in seen:
                continue
            seen.add(key)
            deduped_actions.append(action)
        self.actions = deduped_actions
        return self

    def describe(self) -> str:
        if not self.actions:
            return f"{self.strategy} planner: no retrieval"

        action_parts = [
            f"{action.surface}({action.query})"
            for action in self.actions
        ]
        return f"{self.strategy} planner: " + ", ".join(action_parts)


class RetrievalPlanner:
    def __init__(self, llm_service: LLMService | None = None) -> None:
        self._llm_service = llm_service or LLMService()

    _SMALL_TALK_HINTS: tuple[str, ...] = (
        "你好",
        "您好",
        "hello",
        "hi",
        "在吗",
        "你是谁",
        "你是干嘛的",
        "你能做什么",
        "你可以做什么",
        "能做什么",
        "可以做什么",
        "介绍一下你自己",
        "介绍下你自己",
        "谢谢",
        "谢了",
    )
    _KNOWLEDGE_HINTS: tuple[str, ...] = (
        "文件",
        "文档",
        "材料",
        "附件",
        "ppt",
        "pdf",
        "合同",
        "报价",
        "价格",
        "均价",
        "参数",
        "规格",
        "记录",
        "数据",
        "内容",
        "清单",
        "名单",
        "供应商",
        "采购",
        "条款",
        "交付",
        "付款",
        "金额",
        "预算",
    )
    _KNOWHOW_HINTS: tuple[str, ...] = (
        "资质",
        "认证",
        "合规",
        "审批",
        "流程",
        "风险",
        "规范",
        "规则",
        "政策",
        "要求",
        "必须",
        "应当",
        "单一来源",
        "单一",
        "审查",
        "审计",
        "招标",
        "资格",
        "售后",
        "违约",
    )
    _SKILL_HINTS: tuple[str, ...] = (
        "模板",
        "流程",
        "步骤",
        "清单",
        "生成",
        "起草",
        "工作流",
        "自动化",
        "skill",
        "技能",
        "playbook",
        "执行方案",
    )

    _BASE_INSTRUCTIONS = """
You are a retrieval planner for a Chinese enterprise assistant.

Your job is to decide whether retrieval is needed, and if needed, which retrieval surfaces to use.
Do not answer the user question itself. Only output a structured retrieval plan.

Surface guidance:
- knowledge: enterprise knowledge base, documents, quotations, parameters, contracts, factual evidence
- knowhow: rules, compliance, procurement policies, certifications, approval paths, risk and single-source guidance
- skill: reusable agent skills, workflows, templates, execution playbooks

Planning rules:
- Keep actions minimal and relevant. Do not add actions just to fill space.
- Query strings must be short retrieval queries, not long natural-language paragraphs.
- Prefer knowledge when the user needs factual evidence or file-based recall.
- Prefer knowhow when the user is asking about norms, qualifications, compliance, risk, approval, or policy judgment.
- Prefer skill only when the user clearly needs a reusable workflow, template, or task capability.
- It is valid to return zero actions when retrieval is unnecessary.
- normalized_query should preserve the original meaning while making it easier to retrieve.
""".strip()

    async def plan(
        self,
        *,
        user_query: str,
        enabled_surfaces: set[RetrievalSurface] | None = None,
        settings: RetrievalPlannerSettings | None = None,
    ) -> RetrievalPlan:
        normalized_query = " ".join((user_query or "").split())
        allowed_surfaces = self._normalize_enabled_surfaces(enabled_surfaces)

        if len(normalized_query) < 2:
            return RetrievalPlan(
                strategy="fallback",
                normalized_query=normalized_query,
                notes=["query_too_short"],
            )

        planner_settings = settings or RetrievalPlannerSettings()
        if planner_settings.is_configured:
            llm_planner_error: Exception | None = None
            try:
                llm_plan = await self._plan_with_llm(
                    user_query=normalized_query,
                    allowed_surfaces=allowed_surfaces,
                    settings=planner_settings,
                )
                return self._sanitize_plan(
                    llm_plan,
                    user_query=normalized_query,
                    allowed_surfaces=allowed_surfaces,
                    strategy="llm",
                )
            except Exception as exc:
                llm_planner_error = exc
                logger.info(
                    "[RetrievalPlanner] Structured planner failed, trying JSON fallback: %s",
                    exc,
                )
            try:
                json_plan = await self._plan_with_json_prompt(
                    user_query=normalized_query,
                    allowed_surfaces=allowed_surfaces,
                    settings=planner_settings,
                )
                return self._sanitize_plan(
                    json_plan,
                    user_query=normalized_query,
                    allowed_surfaces=allowed_surfaces,
                    strategy="llm",
                )
            except Exception as exc:
                logger.warning(
                    "[RetrievalPlanner] JSON planner failed, falling back to heuristic plan: structured=%s json=%s",
                    llm_planner_error,
                    exc,
                )

        fallback_plan = self._build_fallback_plan(
            user_query=normalized_query,
            allowed_surfaces=allowed_surfaces,
        )
        return self._sanitize_plan(
            fallback_plan,
            user_query=normalized_query,
            allowed_surfaces=allowed_surfaces,
            strategy="fallback",
        )

    def _normalize_enabled_surfaces(
        self,
        enabled_surfaces: set[RetrievalSurface] | None,
    ) -> tuple[RetrievalSurface, ...]:
        surfaces = enabled_surfaces or set(_SURFACE_ORDER)
        return tuple(surface for surface in _SURFACE_ORDER if surface in surfaces)

    async def _plan_with_llm(
        self,
        *,
        user_query: str,
        allowed_surfaces: tuple[RetrievalSurface, ...],
        settings: RetrievalPlannerSettings,
    ) -> RetrievalPlan:
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        async with httpx.AsyncClient(
            timeout=45.0,
            follow_redirects=True,
            trust_env=False,
        ) as http_client:
            provider = OpenAIProvider(
                base_url=settings.api_url.rstrip("/"),
                api_key=settings.api_key,
                http_client=http_client,
            )
            model = OpenAIChatModel(
                settings.model.strip() or "gpt-4o",
                provider=provider,
            )
            agent = Agent(
                model=model,
                output_type=RetrievalPlan,
                instructions=self._build_instructions(allowed_surfaces),
                retries=1,
                output_retries=1,
                defer_model_check=True,
            )
            result = await agent.run(self._build_user_prompt(user_query, allowed_surfaces))
            return result.output

    def _build_instructions(self, allowed_surfaces: tuple[RetrievalSurface, ...]) -> str:
        allowed_lines = {
            "knowledge": "- knowledge is available",
            "knowhow": "- knowhow is available",
            "skill": "- skill is available",
        }
        availability_text = "\n".join(
            allowed_lines[surface]
            for surface in allowed_surfaces
        )
        return f"{self._BASE_INSTRUCTIONS}\n\nAvailable surfaces:\n{availability_text}"

    @staticmethod
    def _build_user_prompt(
        user_query: str,
        allowed_surfaces: tuple[RetrievalSurface, ...],
    ) -> str:
        allowed = ", ".join(allowed_surfaces) or "none"
        return (
            "Plan retrieval for the following user query.\n"
            f"Allowed surfaces: {allowed}\n"
            f"User query: {user_query}\n"
        )

    async def _plan_with_json_prompt(
        self,
        *,
        user_query: str,
        allowed_surfaces: tuple[RetrievalSurface, ...],
        settings: RetrievalPlannerSettings,
    ) -> RetrievalPlan:
        response = await self._llm_service.chat(
            messages=[
                {
                    "role": "system",
                    "content": self._build_json_system_prompt(allowed_surfaces),
                },
                {
                    "role": "user",
                    "content": self._build_json_user_prompt(user_query, allowed_surfaces),
                },
            ],
            model=settings.model.strip() or "gpt-4o",
            temperature=0.1,
            max_tokens=900,
            api_url=settings.api_url,
            api_key=settings.api_key,
        )
        text = self._llm_service.extract_text_content(response)
        if not text:
            raise ValueError("planner returned empty text")
        return RetrievalPlan.model_validate_json(self._extract_json_payload(text))

    @staticmethod
    def _build_json_system_prompt(allowed_surfaces: tuple[RetrievalSurface, ...]) -> str:
        allowed = ", ".join(allowed_surfaces) or "none"
        return f"""
你是一个中文检索规划器，只负责决定“查什么、去哪里查”，不要回答用户问题本身。

当前可用的检索面有：{allowed}

请只输出 JSON，不要输出 Markdown，不要解释。
JSON schema:
{{
  "intent": "一句话概括用户意图",
  "normalized_query": "保留原始业务语义的检索友好查询",
  "actions": [
    {{
      "surface": "knowledge | knowhow | skill",
      "query": "面向检索的短查询，保留业务关键词",
      "limit": 1-10,
      "required": true,
      "rationale": "为什么查这个面"
    }}
  ],
  "notes": ["可选说明"]
}}

强规则:
- 只能使用当前可用的 surface。
- 可以返回空 actions，但不要为了凑数乱加 action。
- normalized_query 必须贴近用户原句，不要改写成“企业知识库文档检索”这种抽象话。
- query 要保留业务词，例如“价格偏差、报价、均价、供应商资质、认证、单一来源、风险、审批、付款方式”。
- knowledge 用于事实证据、报价、合同、参数、文件内容、历史记录。
- knowhow 用于资质、认证、合规、审批、风险、单一来源、规则判断。
- skill 只用于工作流、模板、执行能力，不要把普通问答误判成 skill。
- 如果一个问题同时包含事实核查和规则判断，可以同时给 knowledge 和 knowhow 两个 action。

示例 1:
用户: 请重点看这次采购里的价格偏差、供应商资质，以及单一来源风险是否需要补充说明
输出:
{{
  "intent": "核查采购报价、资质与单一来源风险",
  "normalized_query": "价格偏差 供应商资质 单一来源风险 补充说明",
  "actions": [
    {{
      "surface": "knowledge",
      "query": "价格偏差 报价 供应商资质",
      "limit": 5,
      "required": true,
      "rationale": "需要事实证据和文档内容来核查报价与供应商材料"
    }},
    {{
      "surface": "knowhow",
      "query": "供应商资质 单一来源 风险 补充说明",
      "limit": 4,
      "required": true,
      "rationale": "需要规则和风险要求来判断是否合规"
    }}
  ],
  "notes": []
}}

示例 2:
用户: 帮我生成采购预审清单
输出:
{{
  "intent": "寻找可复用的采购预审执行模板",
  "normalized_query": "采购预审清单 模板",
  "actions": [
    {{
      "surface": "skill",
      "query": "采购预审 清单 模板",
      "limit": 3,
      "required": true,
      "rationale": "用户需要可执行模板和工作流"
    }}
  ],
  "notes": []
}}
""".strip()

    @staticmethod
    def _build_json_user_prompt(
        user_query: str,
        allowed_surfaces: tuple[RetrievalSurface, ...],
    ) -> str:
        allowed = ", ".join(allowed_surfaces) or "none"
        return (
            f"可用 surface: {allowed}\n"
            f"用户问题: {user_query}\n"
            "只输出 JSON。"
        )

    @staticmethod
    def _extract_json_payload(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError(f"planner response did not contain JSON: {text[:200]}")
        return stripped[start:end + 1]

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _compact_query(query: str, max_chars: int = 60) -> str:
        compact = " ".join((query or "").split())
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars].rstrip()

    def _build_fallback_plan(
        self,
        *,
        user_query: str,
        allowed_surfaces: tuple[RetrievalSurface, ...],
    ) -> RetrievalPlan:
        normalized_query = " ".join((user_query or "").lower().split())
        compact_query = self._compact_query(user_query)
        allowed_set = set(allowed_surfaces)

        if not normalized_query:
            return RetrievalPlan(
                strategy="fallback",
                intent="empty query",
                normalized_query=compact_query,
                actions=[],
                notes=["empty_query"],
            )

        is_small_talk = (
            len(normalized_query) <= 18
            and self._contains_any(normalized_query, self._SMALL_TALK_HINTS)
        )
        if is_small_talk:
            return RetrievalPlan(
                strategy="fallback",
                intent="casual chat",
                normalized_query=compact_query,
                actions=[],
                notes=["heuristic_skip_small_talk"],
            )

        wants_skill = "skill" in allowed_set and self._contains_any(normalized_query, self._SKILL_HINTS)
        wants_knowledge = "knowledge" in allowed_set and self._contains_any(normalized_query, self._KNOWLEDGE_HINTS)
        wants_knowhow = "knowhow" in allowed_set and self._contains_any(normalized_query, self._KNOWHOW_HINTS)

        actions: list[RetrievalPlanAction] = []
        if wants_skill:
            actions.append(
                RetrievalPlanAction(
                    surface="skill",
                    query=compact_query,
                    limit=min(2, _DEFAULT_LIMITS["skill"]),
                    required=True,
                    rationale="heuristic_skill_match",
                )
            )
        if wants_knowledge:
            actions.append(
                RetrievalPlanAction(
                    surface="knowledge",
                    query=compact_query,
                    limit=min(4, _DEFAULT_LIMITS["knowledge"]),
                    required=True,
                    rationale="heuristic_document_or_fact_lookup",
                )
            )
        if wants_knowhow:
            actions.append(
                RetrievalPlanAction(
                    surface="knowhow",
                    query=compact_query,
                    limit=min(4, _DEFAULT_LIMITS["knowhow"]),
                    required=True,
                    rationale="heuristic_rule_or_risk_lookup",
                )
            )

        if not actions:
            return RetrievalPlan(
                strategy="fallback",
                intent="general answer without retrieval",
                normalized_query=compact_query,
                actions=[],
                notes=["heuristic_skip_retrieval"],
            )

        return RetrievalPlan(
            strategy="fallback",
            intent="heuristic retrieval",
            normalized_query=compact_query,
            actions=actions,
            notes=["llm_planner_unavailable", "heuristic_targeted_surfaces"],
        )

    def _sanitize_plan(
        self,
        plan: RetrievalPlan,
        *,
        user_query: str,
        allowed_surfaces: tuple[RetrievalSurface, ...],
        strategy: Literal["llm", "fallback"],
    ) -> RetrievalPlan:
        allowed_set = set(allowed_surfaces)
        sanitized_actions: list[RetrievalPlanAction] = []
        seen: set[tuple[str, str]] = set()

        for action in plan.actions:
            if action.surface not in allowed_set:
                continue

            query = " ".join((action.query or "").split()) or user_query
            key = (action.surface, query)
            if key in seen:
                continue
            seen.add(key)

            sanitized_actions.append(
                RetrievalPlanAction(
                    surface=action.surface,
                    query=query,
                    limit=action.limit or _DEFAULT_LIMITS[action.surface],
                    required=action.required,
                    rationale=action.rationale,
                )
            )

        return RetrievalPlan(
            strategy=strategy,
            intent=plan.intent or "retrieval planning",
            normalized_query=plan.normalized_query or user_query,
            actions=sanitized_actions,
            notes=list(plan.notes),
        )


retrieval_planner = RetrievalPlanner()
