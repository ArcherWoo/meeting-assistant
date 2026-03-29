/**
 * 全局类型定义
 * 遵循 PRD §10.2 前端状态结构 + §4.2 请求格式
 */

// ===== 角色系统（动态，替代旧的三模式硬编码架构）=====
export interface Role {
  id: string;
  name: string;
  icon: string;
  description: string;
  system_prompt: string;
  agent_prompt: string;
  capabilities: string[];   // e.g. ['rag', 'skills']
  chat_capabilities: string[];
  agent_preflight: string[];
  allowed_surfaces: Array<'chat' | 'agent'>;
  agent_allowed_tools: string[];
  is_builtin: number;       // 1 = default seeded role, 0 = user-created
  sort_order: number;
  created_at?: string;
  updated_at?: string;
}

// ===== 消息类型 =====
export type MessageRole = 'system' | 'user' | 'assistant' | 'tool';

export interface ContextCitation {
  id: string;
  source_type: 'knowledge' | 'knowhow' | 'skill' | 'file';
  label: string;
  title: string;
  snippet: string;
  location?: string;
  file_name?: string;
  page?: number;
  chunk_type?: string;
  chunk_index?: number;
  char_start?: number;
  char_end?: number;
}

export interface RetrievalPlanAction {
  surface: 'knowledge' | 'knowhow' | 'skill';
  query: string;
  limit: number;
  required: boolean;
  rationale?: string;
}

export interface RetrievalPlan {
  strategy: 'llm' | 'fallback';
  intent: string;
  normalized_query: string;
  actions: RetrievalPlanAction[];
  notes: string[];
}

export interface ContextMetadata {
  knowledge_count: number;
  knowhow_count: number;
  skill_count: number;
  summary: string;
  citations: ContextCitation[];
  retrieval_plan?: RetrievalPlan | null;
  schema_version?: number;
  truncated?: boolean;
  retrieved_summary?: string;
  retrieved_knowledge_count?: number;
  retrieved_knowhow_count?: number;
  retrieved_skill_count?: number;
  retrieved_citations?: ContextCitation[];
}

export interface SkillSuggestionEvent {
  skill_id: string;
  skill_name: string;
  description: string;
  score: number;
  confidence: string;
  schema_version?: number;
  matched_keywords?: string[];
}

export interface AgentResultSnapshot {
  runId?: string;
  summary: string;
  raw_text: string;
  used_tools: string[];
  citations: ContextCitation[];
  artifacts: Array<{
    type: 'report' | 'table' | 'checklist' | 'json';
    title: string;
    content: string;
    mime_type?: string;
  }>;
  next_actions: string[];
  structured_payload?: Record<string, unknown>;
}

export interface MessageMetadata {
  context?: ContextMetadata;
  skillSuggestion?: SkillSuggestionEvent;
  agentResult?: AgentResultSnapshot;
}

export interface Message {
  id: string;
  conversationId: string;
  role: MessageRole;
  content: string;
  model?: string;
  tokenInput?: number;
  tokenOutput?: number;
  durationMs?: number;
  attachments?: Attachment[];
  metadata?: MessageMetadata;
  createdAt: string;
}

// ===== 对话类型 =====
export interface Conversation {
  id: string;
  workspaceId: string;
  title: string;
  surface: 'chat' | 'agent';
  roleId: string;
  isPinned: boolean;
  isTitleCustomized: boolean; // true = 用户已手动命名，自动命名不覆盖
  createdAt: string;
  updatedAt: string;
  lastMessage?: string; // 最后一条消息预览
}

// ===== 工作区类型 =====
export interface Workspace {
  id: string;
  name: string;
  description: string;
  icon: string;
  createdAt: string;
  updatedAt: string;
}

// ===== 附件类型 =====
export interface Attachment {
  id: string;
  fileName: string;
  fileSize: number;
  fileType: string;
  file?: File; // 前端暂存的文件对象
}

// ===== LLM 配置 =====
export interface LLMConfig {
  apiUrl: string;
  apiKey: string;
  model: string;
  temperature: number;
  maxTokens: number;
  stream: boolean;
}

export interface LLMProfile extends LLMConfig {
  id: string;
  name: string;
  availableModels?: string[];
}

export interface LLMConnectionTestResult {
  success: boolean;
  message: string;
  model: string;
  available_models: string[];
  selected_model_available: boolean;
  fallback: boolean;
}

export interface SystemPromptPreset {
  id: string;
  name: string;
  role_id: string;
  prompt: string;
  created_at: string;
  updated_at: string;
}

// ===== PPT 解析结果 =====
export interface PPTParseResult {
  metadata: {
    title: string;
    author: string;
    created: string;
    modified: string;
    slide_count: number;
    file_size: string;
    parser: string;
  };
  slides: PPTSlide[];
  full_markdown: string;
  extraction_stats: {
    total_tables: number;
    total_images: number;
    parser: string;
  };
}

export interface PPTSlide {
  index: number;
  title: string;
  texts: string[];
  tables: { rows: string[][]; markdown: string; row_count: number }[];
  images: { desc: string; index: number }[];
  notes: string;
}

// ===== Phase 2: Skill 类型 =====
export interface SkillMeta {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  input_types: string[];
  parameters: SkillParam[];
  steps: string[];
  dependencies: string[];
  output_template: string;
  execution_profile: SkillExecutionProfile;
  is_builtin: boolean;
  source_path: string;
}

export interface SkillParam {
  name: string;
  type: string;
  required: boolean;
  default?: string;
  description: string;
  options?: string[];
  source?: string;
}

export interface SkillExecutionProfile {
  surface: string;
  preferred_role_id: string;
  allowed_tools: string[];
  output_kind: string;
  output_sections: string[];
  notes: string[];
}

export interface SkillMatch {
  skill_id: string;
  skill_name: string;
  score: number;
  confidence: string;
  match_type: string;
  matched_keywords: string[];
}

// ===== Phase 2: Know-how 类型 =====
export interface KnowhowRule {
  id: string;
  category: string;
  rule_text: string;
  weight: number;
  hit_count: number;
  confidence: number;
  source: string;
  is_active: number;
  created_at: string;
  updated_at: string;
}

export type KnowhowImportStrategy = 'append' | 'replace';

export interface KnowhowExportData {
  kind: string;
  schema_version: number;
  exported_at: string;
  total_rules: number;
  rules: KnowhowRule[];
}

export interface KnowhowImportResult {
  strategy: KnowhowImportStrategy;
  total_in_file: number;
  imported_count: number;
  skipped_count: number;
  deleted_count: number;
  total_after_import: number;
}

// ===== Phase 2: 知识库类型 =====
export interface KnowledgeStats {
  total_ppt_imports: number;
  completed_imports: number;
  total_procurement_records: number;
  total_vector_chunks: number;
}

export interface IngestResult {
  import_id: string;
  status: string;
  file_type?: string;
  extracted_count: number;
  chunks_count: number;
  slide_count?: number;
  text_length?: number;
  table_count?: number;
  image_count?: number;
  char_count?: number;
}

// ===== Phase 2: Agent 执行类型 =====
export interface AgentMatchResult {
  matched: boolean;
  skill_id?: string;
  skill_name?: string;
  score?: number;
  confidence?: string;
  matched_keywords?: string[];
  parameters?: SkillParam[];
  execution_profile?: SkillExecutionProfile;
  role_id?: string;
  surface?: 'agent';
  message?: string;
}

export interface AgentFinalResult {
  summary: string;
  raw_text: string;
  used_tools: string[];
  citations: Array<{
    source_type: 'knowledge' | 'knowhow' | 'skill' | 'file';
    label: string;
    title?: string;
    snippet: string;
    location?: string;
  }>;
  artifacts: Array<{
    type: 'report' | 'table' | 'checklist' | 'json';
    title: string;
    content: string;
    mime_type?: string;
  }>;
  next_actions: string[];
  structured_payload?: Record<string, unknown>;
}

export interface AgentRunStep {
  id: string;
  runId: string;
  index: number;
  step_key: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled';
  result?: string;
  error?: string;
  toolName?: string;
  metadata?: Record<string, unknown>;
  startedAt?: string;
  completedAt?: string;
}

export interface AgentRunRecord {
  id: string;
  runId: string;
  conversationId?: string;
  surface: 'agent';
  roleId: string;
  continueFromRunId?: string;
  continueMode?: 'continue' | 'retry' | '';
  skillId?: string;
  skillName?: string;
  query: string;
  params: Record<string, unknown>;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  model?: string;
  llmProfileId?: string;
  messageHistoryCount?: number;
  finalResult?: AgentFinalResult;
  error?: string;
  steps: AgentRunStep[];
  startedAt?: string;
  completedAt?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface AgentRunCancelResponse {
  run: AgentRunRecord | null;
  cancel_requested: boolean;
  message: string;
}

export interface AgentExecutionEvent {
  type: 'execution_start' | 'step_start' | 'step_complete' | 'step_error' | 'complete' | 'error' | 'cancelled';
  run_id?: string;
  role_id?: string;
  skill_id?: string;
  skill_name?: string;
  step?: number;
  step_key?: string;
  description?: string;
  result?: string;
  error?: string;
  message?: string;
  final_result?: AgentFinalResult;
  step_state?: {
    index: number;
    step_key: string;
    description: string;
    status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'cancelled';
    tool_name?: string;
    result?: string;
    error?: string;
    metadata?: Record<string, unknown>;
    started_at?: string;
    completed_at?: string;
  };
  context?: {
    status: string;
    steps: {
      index: number;
      step_key?: string;
      description: string;
      status: string;
      tool_name?: string;
      result?: string;
      error?: string;
      metadata?: Record<string, unknown>;
      started_at?: string;
      completed_at?: string;
    }[];
    result?: string;
  };
}

// ===== UI 状态 =====
export type Theme = 'light' | 'dark' | 'system';

export interface BackendStatus {
  connected: boolean;
  port: number;
}
