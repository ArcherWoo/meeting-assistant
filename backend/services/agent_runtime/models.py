from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


AgentSurface = Literal["agent"]
AgentStepStatus = Literal["pending", "running", "completed", "failed", "skipped", "cancelled"]
AgentExecutionStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
AgentContinueMode = Literal["continue", "retry"]
AgentEventType = Literal[
    "execution_start",
    "step_start",
    "step_complete",
    "step_error",
    "complete",
    "error",
    "cancelled",
]


class AgentMatchRequest(BaseModel):
    query: str
    role_id: str | None = None


class AgentSkillExecutionProfile(BaseModel):
    surface: str = "agent"
    preferred_role_id: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    output_kind: str = ""
    output_sections: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AgentMatchResponse(BaseModel):
    matched: bool
    skill_id: str | None = None
    skill_name: str | None = None
    score: float | None = None
    confidence: str | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    execution_profile: AgentSkillExecutionProfile | None = None
    role_id: str | None = None
    surface: AgentSurface = "agent"
    message: str | None = None


class AgentExecuteRequest(BaseModel):
    role_id: str
    query: str = ""
    skill_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = None
    run_id: str | None = None
    continue_from_run_id: str | None = None
    continue_mode: AgentContinueMode = "continue"
    continue_notes: str = ""
    llm_profile_id: str | None = None
    api_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o"
    dry_run: bool = False
    client_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_required_text(self) -> "AgentExecuteRequest":
        self.role_id = self.role_id.strip()
        self.query = self.query.strip()
        self.continue_from_run_id = (self.continue_from_run_id or "").strip() or None
        self.continue_notes = self.continue_notes.strip()
        if not self.role_id:
            raise ValueError("role_id is required")
        if not self.query and not self.continue_from_run_id:
            raise ValueError("query is required")
        return self


class AgentCitation(BaseModel):
    id: str | None = None
    source_type: Literal["knowledge", "knowhow", "skill", "file"]
    label: str
    title: str | None = None
    snippet: str
    location: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentArtifact(BaseModel):
    type: Literal["report", "table", "checklist", "json", "file"]
    title: str
    content: str
    mime_type: str | None = None
    download_url: str | None = None


class AgentFinalResult(BaseModel):
    summary: str = ""
    raw_text: str = ""
    used_tools: list[str] = Field(default_factory=list)
    citations: list[AgentCitation] = Field(default_factory=list)
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    structured_payload: dict[str, Any] = Field(default_factory=dict)


class AgentStepState(BaseModel):
    index: int
    step_key: str
    description: str
    status: AgentStepStatus = "pending"
    tool_name: str | None = None
    result: str | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentToolCallRecord(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    summary: str = ""
    started_at: str
    completed_at: str | None = None


class AgentExecutionState(BaseModel):
    run_id: str
    surface: AgentSurface = "agent"
    role_id: str
    skill_id: str | None = None
    skill_name: str | None = None
    query: str
    status: AgentExecutionStatus = "pending"
    steps: list[AgentStepState] = Field(default_factory=list)
    used_tools: list[str] = Field(default_factory=list)
    tool_calls: list[AgentToolCallRecord] = Field(default_factory=list)
    conversation_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    final_result: AgentFinalResult | None = None
    error: str | None = None


class AgentEvent(BaseModel):
    type: AgentEventType
    run_id: str | None = None
    surface: AgentSurface | None = None
    role_id: str | None = None
    skill_id: str | None = None
    skill_name: str | None = None
    query: str | None = None
    step: int | None = None
    step_key: str | None = None
    description: str | None = None
    result: str | None = None
    error: str | None = None
    message: str | None = None
    step_state: AgentStepState | None = None
    context: dict[str, Any] | None = None
    final_result: AgentFinalResult | None = None


class RolePolicy(BaseModel):
    role_id: str
    surface: AgentSurface = "agent"
    allowed: bool
    capabilities: list[str] = Field(default_factory=list)
    chat_capabilities: list[str] = Field(default_factory=list)
    agent_preflight: list[str] = Field(default_factory=list)
    allowed_surfaces: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    enable_rag: bool = False
    enable_skill_matching: bool = False
    instructions: str
    display_name: str
    icon: str | None = None


class GetSkillDefinitionInput(BaseModel):
    skill_id: str


class GetSkillDefinitionOutput(BaseModel):
    skill_id: str
    name: str
    description: str
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    output_template: str = ""


class ExtractFileTextInput(BaseModel):
    import_id: str | None = None
    filename: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "ExtractFileTextInput":
        if not (self.import_id or self.filename):
            raise ValueError("import_id or filename is required")
        return self


class ExtractFileTextOutput(BaseModel):
    source: str
    text: str
    char_count: int


class QueryKnowledgeInput(BaseModel):
    query: str
    limit: int = 5


class QueryKnowledgeOutput(BaseModel):
    summary: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[AgentCitation] = Field(default_factory=list)


class SearchKnowhowRulesInput(BaseModel):
    query: str
    limit: int = 5


class SearchKnowhowRulesOutput(BaseModel):
    summary: str
    rules: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[AgentCitation] = Field(default_factory=list)


class RunExcelCategoryMappingInput(BaseModel):
    template_import_id: str
    data_import_id: str
    template_sheet: str = ""
    data_sheet: str = ""
    name_column: int = 2
    knowhow_categories: str = ""
    mode: Literal["strict", "balanced", "recall"] = "balanced"
    review_threshold: float = 0.55

    @model_validator(mode="after")
    def validate_fields(self) -> "RunExcelCategoryMappingInput":
        self.template_import_id = self.template_import_id.strip()
        self.data_import_id = self.data_import_id.strip()
        self.template_sheet = self.template_sheet.strip()
        self.data_sheet = self.data_sheet.strip()
        self.knowhow_categories = self.knowhow_categories.strip()
        if not self.template_import_id:
            raise ValueError("template_import_id is required")
        if not self.data_import_id:
            raise ValueError("data_import_id is required")
        if self.name_column < 1:
            raise ValueError("name_column must be >= 1")
        self.review_threshold = max(0.0, min(1.0, float(self.review_threshold)))
        return self


class RunExcelCategoryMappingOutput(BaseModel):
    summary: str
    output_path: str
    output_filename: str
    processed_count: int
    matched_count: int
    review_count: int
    template_path_count: int
    knowhow_rule_count: int
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class AgentRuntimeMemory:
    used_tools: list[str] = field(default_factory=list)
    citations: list[AgentCitation] = field(default_factory=list)
    artifacts: list[AgentArtifact] = field(default_factory=list)
    tool_calls: list[AgentToolCallRecord] = field(default_factory=list)


@dataclass
class AgentDeps:
    role_id: str
    surface: AgentSurface
    policy: RolePolicy
    role: dict[str, Any]
    storage: Any
    knowledge_service: Any
    knowhow_service: Any
    skill_manager: Any
    context_assembler: Any
    api_url: str
    api_key: str
    model: str
    run_id: str
    request_params: dict[str, Any]
    user_id: str | None = None
    group_id: str | None = None
    is_admin: bool = False
    conversation_id: str | None = None
    llm_profile_id: str | None = None
    skill: Any = None
    skill_execution_profile: AgentSkillExecutionProfile | None = None
    event_adapter: Any = None
    memory: AgentRuntimeMemory = field(default_factory=AgentRuntimeMemory)
