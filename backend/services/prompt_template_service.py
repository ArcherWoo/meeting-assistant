import json
import re
from datetime import date
from typing import Any, Optional

from services.storage import gen_id, storage

# 保留向后兼容——这些常量被 settings.py / chat.py 导入
VALID_PROMPT_MODES = {"copilot", "builder", "agent"}
VALID_PROMPT_SCOPES = {"global", *VALID_PROMPT_MODES}
DYNAMIC_VARIABLE_KEYS = {"mode", "mode_label", "today", "current_date"}
MODE_LABELS: dict[str, str] = {
    "copilot": "Copilot",
    "builder": "Skill Builder",
    "agent": "Agent",
}
DEFAULT_SYSTEM_PROMPTS: dict[str, str] = {
    "copilot": (
        "你是一个专业的会议助手。请根据用户的问题，提供清晰、准确、有帮助的回答。"
        "回答时请保持简洁，优先给出结论，再补充细节。"
    ),
    "builder": (
        "你是一个 Skill Builder 助手，专门帮助用户创建和优化工作流技能（Skill）。"
        "请引导用户描述他们的工作场景和重复性任务，帮助他们将这些任务抽象为可执行的 Skill 模板。"
        "生成的 Skill 应使用标准 Markdown 格式，包含描述、触发条件、执行步骤和输出格式。"
    ),
    "agent": (
        "你是一个智能 Agent，能够调用各种工具和技能完成复杂任务。"
        "请分析用户的需求，选择合适的工具，并逐步执行任务。"
        "执行过程中保持透明，让用户了解每一步的进展。"
    ),
}

_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][\w.-]*)\s*}}")
_CONFIG_KEY_PREFIX = "system_prompt_config_"
_BUILTIN_TEMPLATE_PREFIX = "builtin:"

_BUILTIN_PROMPT_PACKS = [
    {
        "id": "executive-brief",
        "name": "高管简报包",
        "icon": "BRIEF",
        "description": "把回答收束成结论、依据、风险和下一步，适合汇报、纪要和决策沟通。",
        "recommended_modes": ["copilot", "agent"],
        "tags": ["结论优先", "汇报", "决策"],
        "templates": [
            {
                "slug": "conclusion-first",
                "name": "结论先行",
                "description": "先给结论，再给依据和建议动作。",
                "scope": "global",
                "content": (
                    "请优先输出“结论 -> 关键依据 -> 下一步建议”三段结构。"
                    "结论不超过 {{conclusion_count}} 条，每条 1-2 句。"
                ),
                "variables": {"conclusion_count": "3"},
            },
            {
                "slug": "decision-risk",
                "name": "决策与风险",
                "description": "涉及取舍时明确推荐方案、主要风险和建议动作。",
                "scope": "global",
                "content": (
                    "如果问题涉及方案选择、预算或推进建议，请明确给出推荐方案，"
                    "并列出最多 {{risk_count}} 个关键风险与对应建议动作。"
                ),
                "variables": {"risk_count": "3"},
            },
            {
                "slug": "source-grounding",
                "name": "依据锚点",
                "description": "引用资料时优先指出来源和定位。",
                "scope": "copilot",
                "content": "引用附件或知识库内容时，优先说明来源文件、位置和依据，不编造来源。",
                "variables": {},
            },
            {
                "slug": "agent-status",
                "name": "执行状态摘要",
                "description": "Agent 模式下同步汇报执行状态与待确认事项。",
                "scope": "agent",
                "content": (
                    "在执行型回答中，请补充“当前进度 / 已完成 / 待确认事项”三个小节，"
                    "让读者快速理解推进状态。"
                ),
                "variables": {},
            },
        ],
    },
    {
        "id": "evidence-review",
        "name": "证据审阅包",
        "icon": "REVIEW",
        "description": "强调基于证据判断、暴露不确定性和开放问题，适合评审与复盘。",
        "recommended_modes": ["copilot", "builder"],
        "tags": ["审阅", "证据", "开放问题"],
        "templates": [
            {
                "slug": "evidence-first",
                "name": "证据优先",
                "description": "判断前先给证据，不足时明确说明。",
                "scope": "global",
                "content": (
                    "在做出判断前，请先列出支持判断的证据。"
                    "如果证据不足，请明确说明“目前无法确认”的原因，而不是补全猜测。"
                ),
                "variables": {},
            },
            {
                "slug": "open-questions",
                "name": "开放问题清单",
                "description": "最后保留待确认项，便于继续推进。",
                "scope": "global",
                "content": (
                    "回答结尾请补充“待确认问题”小节，列出最多 {{question_count}} 个影响结论的开放问题。"
                ),
                "variables": {"question_count": "3"},
            },
            {
                "slug": "copilot-checklist",
                "name": "Copilot 审阅检查点",
                "description": "Copilot 模式下优先检查遗漏、矛盾和风险。",
                "scope": "copilot",
                "content": "如果用户在审阅材料，请优先指出信息遗漏、前后矛盾、风险点和需要补证的部分。",
                "variables": {},
            },
            {
                "slug": "builder-constraints",
                "name": "Builder 约束澄清",
                "description": "Builder 模式下先确认目标、输入和约束。",
                "scope": "builder",
                "content": (
                    "在设计 Skill 或工作流前，请先澄清目标、输入、输出、边界条件与失败场景。"
                ),
                "variables": {},
            },
        ],
    },
    {
        "id": "workflow-delivery",
        "name": "流程交付包",
        "icon": "FLOW",
        "description": "强调结构化交付、步骤拆解和执行透明，适合搭建流程和代理执行。",
        "recommended_modes": ["builder", "agent"],
        "tags": ["流程设计", "执行透明", "交付物"],
        "templates": [
            {
                "slug": "structured-deliverable",
                "name": "结构化交付",
                "description": "统一用目标、步骤、产出的结构回答。",
                "scope": "global",
                "content": "请尽量用“目标 / 步骤 / 输出物”结构组织回答，便于直接执行和交付。",
                "variables": {},
            },
            {
                "slug": "builder-blueprint",
                "name": "Skill 蓝图",
                "description": "Builder 模式下先产出 Skill 蓝图再细化正文。",
                "scope": "builder",
                "content": (
                    "在 Builder 模式下，请先给出 Skill 蓝图：触发条件、输入、步骤、输出、失败兜底，"
                    "再补充完整内容。"
                ),
                "variables": {},
            },
            {
                "slug": "agent-transparency",
                "name": "Agent 透明执行",
                "description": "Agent 模式下同步说明计划、执行与阻塞。",
                "scope": "agent",
                "content": (
                    "在 Agent 模式下，请显式说明执行计划、当前动作、已完成结果和阻塞项。"
                    "如果需要用户决策，请单独列出。"
                ),
                "variables": {},
            },
        ],
    },
]


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


class PromptTemplateService:
    @staticmethod
    def _build_builtin_template(pack: dict, template: dict) -> dict:
        template_id = f"{_BUILTIN_TEMPLATE_PREFIX}{pack['id']}/{template['slug']}"
        content = str(template.get("content") or "")
        variables = PromptTemplateService._normalize_variables(template.get("variables") or {})
        return {
            "id": template_id,
            "name": str(template.get("name") or template["slug"]),
            "description": str(template.get("description") or ""),
            "scope": str(template.get("scope") or "global"),
            "content": content,
            "variables": variables,
            "placeholders": PromptTemplateService.extract_placeholders(content),
            "is_builtin": True,
            "source": "builtin",
            "pack_id": pack["id"],
            "pack_name": pack["name"],
        }

    @classmethod
    def _list_builtin_templates(cls, scope: Optional[str] = None) -> list[dict]:
        normalized_scope = cls._validate_scope(scope) if scope else None
        templates: list[dict] = []
        for pack in _BUILTIN_PROMPT_PACKS:
            for template in pack["templates"]:
                normalized = cls._build_builtin_template(pack, template)
                if normalized_scope and normalized["scope"] not in {"global", normalized_scope}:
                    continue
                if normalized_scope == "global" and normalized["scope"] != "global":
                    continue
                templates.append(normalized)
        return templates

    @classmethod
    def _get_builtin_template(cls, template_id: str) -> Optional[dict]:
        for template in cls._list_builtin_templates():
            if template["id"] == template_id:
                return template
        return None

    @classmethod
    def _available_template_map(cls, scope: Optional[str], user_templates: list[dict]) -> dict[str, dict]:
        templates = [*cls._list_builtin_templates(scope), *user_templates]
        return {template["id"]: template for template in templates}

    @staticmethod
    def _validate_mode(mode: str) -> str:
        """接受任意非空字符串作为 mode（角色 ID）。"""
        normalized = (mode or "").strip()
        if not normalized:
            raise ValueError("模式不能为空")
        return normalized

    @staticmethod
    def _validate_scope(scope: str) -> str:
        """接受 'global' 或任意非空字符串（动态角色 ID）作为 scope。"""
        normalized = (scope or "global").strip() or "global"
        return normalized

    @staticmethod
    def _normalize_variables(raw_variables: Any) -> dict[str, str]:
        if not isinstance(raw_variables, dict):
            return {}

        normalized: dict[str, str] = {}
        for key, value in raw_variables.items():
            name = str(key or "").strip()
            if not name:
                continue
            normalized[name] = str(value or "").strip()
        return normalized

    @staticmethod
    def extract_placeholders(content: str) -> list[str]:
        return _ordered_unique(_PLACEHOLDER_RE.findall(content or ""))

    @staticmethod
    def render_content(content: str, variables: dict[str, str]) -> tuple[str, list[str]]:
        missing: list[str] = []

        def replace(match: re.Match[str]) -> str:
            variable_name = match.group(1)
            value = variables.get(variable_name)
            if value is None or value == "":
                missing.append(variable_name)
                return ""
            return value

        rendered = _PLACEHOLDER_RE.sub(replace, content or "")
        rendered = re.sub(r"\n{3,}", "\n\n", rendered).strip()
        return rendered, _ordered_unique(missing)

    @staticmethod
    def _normalize_template_row(row: dict) -> dict:
        try:
            raw_variables = json.loads(row.get("variables_json") or "{}") if row.get("variables_json") else {}
        except json.JSONDecodeError:
            raw_variables = {}
        variables = PromptTemplateService._normalize_variables(raw_variables)
        content = str(row.get("content") or "")
        return {
            **row,
            "description": str(row.get("description") or ""),
            "scope": str(row.get("scope") or "global"),
            "content": content,
            "variables": variables,
            "placeholders": PromptTemplateService.extract_placeholders(content),
            "is_builtin": False,
            "source": "user",
            "pack_id": None,
            "pack_name": None,
        }

    @staticmethod
    def _config_key(mode: str) -> str:
        return f"{_CONFIG_KEY_PREFIX}{mode}"

    @staticmethod
    def get_dynamic_variables(mode: str) -> dict[str, str]:
        normalized_mode = PromptTemplateService._validate_mode(mode)
        today = date.today().isoformat()
        return {
            "mode": normalized_mode,
            "mode_label": MODE_LABELS.get(normalized_mode, normalized_mode),
            "today": today,
            "current_date": today,
        }

    @staticmethod
    def compose_prompt(base_prompt: str, template_contents: list[str], extra_prompt: str = "") -> str:
        sections = [section.strip() for section in [base_prompt, *template_contents, extra_prompt] if section and section.strip()]
        return "\n\n".join(sections).strip()

    async def list_templates(self, scope: Optional[str] = None) -> list[dict]:
        normalized_scope = self._validate_scope(scope) if scope else None
        rows = await storage.list_prompt_templates(
            normalized_scope if normalized_scope and normalized_scope != "global" else None
        )
        user_templates = [self._normalize_template_row(row) for row in rows]
        if normalized_scope == "global":
            user_templates = [template for template in user_templates if template["scope"] == "global"]

        builtin_templates = self._list_builtin_templates(normalized_scope)
        return [*builtin_templates, *user_templates]

    async def create_template(
        self,
        name: str,
        description: str,
        scope: str,
        content: str,
        variables: Optional[dict[str, str]] = None,
    ) -> dict:
        normalized_name = (name or "").strip()
        if not normalized_name:
            raise ValueError("模板名称不能为空")

        normalized_content = (content or "").strip()
        if not normalized_content:
            raise ValueError("模板内容不能为空")

        normalized_scope = self._validate_scope(scope)
        normalized_variables = self._normalize_variables(variables or {})
        template_id = gen_id()
        await storage.add_prompt_template(
            template_id=template_id,
            name=normalized_name,
            description=(description or "").strip(),
            scope=normalized_scope,
            content=normalized_content,
            variables_json=json.dumps(normalized_variables, ensure_ascii=False),
        )
        created = await storage.get_prompt_template(template_id)
        return self._normalize_template_row(created or {
            "id": template_id,
            "name": normalized_name,
            "description": (description or "").strip(),
            "scope": normalized_scope,
            "content": normalized_content,
            "variables_json": json.dumps(normalized_variables, ensure_ascii=False),
        })

    async def update_template(
        self,
        template_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        scope: Optional[str] = None,
        content: Optional[str] = None,
        variables: Optional[dict[str, str]] = None,
    ) -> dict:
        if template_id.startswith(_BUILTIN_TEMPLATE_PREFIX):
            raise ValueError("内置模板不可直接修改，请复制后再编辑")
        existing = await storage.get_prompt_template(template_id)
        if not existing:
            raise KeyError("模板不存在")

        updates: dict[str, str] = {}
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("模板名称不能为空")
            updates["name"] = normalized_name
        if description is not None:
            updates["description"] = description.strip()
        if scope is not None:
            updates["scope"] = self._validate_scope(scope)
        if content is not None:
            normalized_content = content.strip()
            if not normalized_content:
                raise ValueError("模板内容不能为空")
            updates["content"] = normalized_content
        if variables is not None:
            updates["variables_json"] = json.dumps(self._normalize_variables(variables), ensure_ascii=False)

        updated = await storage.update_prompt_template(template_id, **updates)
        if not updated:
            raise RuntimeError("模板更新失败")

        current = await storage.get_prompt_template(template_id)
        if not current:
            raise RuntimeError("模板更新后无法读取")
        return self._normalize_template_row(current)

    async def delete_template(self, template_id: str) -> None:
        if template_id.startswith(_BUILTIN_TEMPLATE_PREFIX):
            raise ValueError("内置模板不可删除")
        deleted = await storage.delete_prompt_template(template_id)
        if not deleted:
            raise KeyError("模板不存在")

    async def list_builtin_packs(self) -> list[dict]:
        # 使用数据库中的角色列表，而非硬编码模式
        db_roles = await storage.list_roles()
        role_ids = sorted(r["id"] for r in db_roles) if db_roles else sorted(VALID_PROMPT_MODES)
        packs: list[dict] = []
        for pack in _BUILTIN_PROMPT_PACKS:
            templates = [self._build_builtin_template(pack, template) for template in pack["templates"]]
            counts_by_mode = {
                mode: len([template for template in templates if template["scope"] in {"global", mode}])
                for mode in role_ids
            }
            packs.append({
                "id": pack["id"],
                "name": pack["name"],
                "icon": pack.get("icon", "PACK"),
                "description": pack["description"],
                "recommended_modes": list(pack.get("recommended_modes", [])),
                "tags": list(pack.get("tags", [])),
                "templates": templates,
                "template_count": len(templates),
                "template_count_by_mode": counts_by_mode,
            })
        return packs

    async def get_builtin_pack(self, pack_id: str) -> dict:
        for pack in await self.list_builtin_packs():
            if pack["id"] == pack_id:
                return pack
        raise KeyError("内置模板包不存在")

    async def _filter_variables_for_template_ids(
        self,
        mode: str,
        template_ids: list[str],
        variables: dict[str, str],
    ) -> dict[str, str]:
        template_map = {template["id"]: template for template in await self.list_templates(mode)}
        relevant_keys: set[str] = set()
        for template_id in template_ids:
            template = template_map.get(template_id)
            if not template:
                continue
            for placeholder in template.get("placeholders", []):
                if placeholder not in DYNAMIC_VARIABLE_KEYS:
                    relevant_keys.add(placeholder)
        return {
            key: value
            for key, value in self._normalize_variables(variables).items()
            if key in relevant_keys
        }

    async def get_mode_config(self, mode: str) -> dict:
        normalized_mode = self._validate_mode(mode)
        raw_value = await storage.get_setting(self._config_key(normalized_mode), default="")
        config = {
            "mode": normalized_mode,
            "template_ids": [],
            "variables": {},
            "extra_prompt": "",
        }
        if not raw_value.strip():
            return config

        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return config

        template_ids = []
        for template_id in parsed.get("template_ids", []):
            normalized_id = str(template_id or "").strip()
            if normalized_id:
                template_ids.append(normalized_id)

        config["template_ids"] = _ordered_unique(template_ids)
        config["variables"] = self._normalize_variables(parsed.get("variables", {}))
        config["extra_prompt"] = str(parsed.get("extra_prompt") or "").strip()
        return config

    async def save_mode_config(
        self,
        mode: str,
        template_ids: list[str],
        variables: Optional[dict[str, str]] = None,
        extra_prompt: str = "",
    ) -> dict:
        normalized_mode = self._validate_mode(mode)
        template_map = {template["id"]: template for template in await self.list_templates(normalized_mode)}
        valid_template_ids: list[str] = []
        for template_id in template_ids:
            normalized_id = str(template_id or "").strip()
            if normalized_id and normalized_id in template_map:
                valid_template_ids.append(normalized_id)

        payload = {
            "template_ids": _ordered_unique(valid_template_ids),
            "variables": await self._filter_variables_for_template_ids(
                normalized_mode,
                _ordered_unique(valid_template_ids),
                self._normalize_variables(variables or {}),
            ),
            "extra_prompt": (extra_prompt or "").strip(),
        }
        await storage.set_setting(
            self._config_key(normalized_mode),
            json.dumps(payload, ensure_ascii=False),
        )
        return await self.get_mode_config(normalized_mode)

    async def reset_mode_config(self, mode: str) -> dict:
        normalized_mode = self._validate_mode(mode)
        await storage.set_setting(self._config_key(normalized_mode), "")
        return await self.get_mode_config(normalized_mode)

    async def resolve_mode_prompt(self, mode: str, base_prompt: str) -> dict:
        normalized_mode = self._validate_mode(mode)
        config = await self.get_mode_config(normalized_mode)
        available_templates = await self.list_templates(normalized_mode)
        template_map = {template["id"]: template for template in available_templates}
        dynamic_variables = self.get_dynamic_variables(normalized_mode)

        rendered_templates: list[dict] = []
        missing_variables: list[str] = []
        rendered_contents: list[str] = []

        for template_id in config["template_ids"]:
            template = template_map.get(template_id)
            if not template:
                continue

            merged_variables = {
                **template["variables"],
                **config["variables"],
                **dynamic_variables,
            }
            rendered_content, missing = self.render_content(template["content"], merged_variables)
            rendered_templates.append({
                **template,
                "rendered_content": rendered_content,
                "missing_variables": missing,
            })
            if rendered_content:
                rendered_contents.append(rendered_content)
            missing_variables.extend(missing)

        resolved_prompt = self.compose_prompt(base_prompt, rendered_contents, config["extra_prompt"])

        return {
            **config,
            "mode": normalized_mode,
            "dynamic_variables": dynamic_variables,
            "templates": rendered_templates,
            "missing_variables": _ordered_unique(missing_variables),
            "resolved_prompt": resolved_prompt,
        }

    async def apply_builtin_pack(
        self,
        pack_id: str,
        modes: list[str],
        strategy: str = "append",
    ) -> dict:
        normalized_strategy = (strategy or "append").strip().lower()
        if normalized_strategy not in {"append", "replace"}:
            raise ValueError("不支持的应用策略，仅支持 append 或 replace")

        pack = await self.get_builtin_pack(pack_id)
        normalized_modes = _ordered_unique([self._validate_mode(mode) for mode in modes])
        if not normalized_modes:
            raise ValueError("至少选择一个模式")

        results: list[dict] = []
        for mode in normalized_modes:
            applicable_templates = [
                template for template in pack["templates"]
                if template["scope"] in {"global", mode}
            ]
            applicable_template_ids = [template["id"] for template in applicable_templates]
            current_config = await self.get_mode_config(mode)

            if not applicable_template_ids:
                results.append({
                    "mode": mode,
                    "status": "skipped",
                    "applied_template_ids": [],
                    "template_ids": current_config["template_ids"],
                })
                continue

            if normalized_strategy == "replace":
                next_template_ids = applicable_template_ids
            else:
                next_template_ids = _ordered_unique(current_config["template_ids"] + applicable_template_ids)

            next_variables = await self._filter_variables_for_template_ids(
                mode,
                next_template_ids,
                current_config["variables"],
            )
            saved_config = await self.save_mode_config(
                mode,
                template_ids=next_template_ids,
                variables=next_variables,
                extra_prompt=current_config["extra_prompt"],
            )
            base_prompt = await storage.get_setting(f"system_prompt_{mode}", default="")
            resolved = await self.resolve_mode_prompt(
                mode,
                base_prompt or DEFAULT_SYSTEM_PROMPTS.get(mode, ""),
            )
            results.append({
                "mode": mode,
                "status": "applied",
                "applied_template_ids": applicable_template_ids,
                "template_ids": saved_config["template_ids"],
                "missing_variables": resolved["missing_variables"],
            })

        return {
            "pack": pack,
            "strategy": normalized_strategy,
            "results": results,
        }


prompt_template_service = PromptTemplateService()
