/**
 * 全局类型定义
 * 遵循 PRD §10.2 前端状态结构 + §4.2 请求格式
 */

// ===== Electron API 类型 =====
export interface ElectronAPI {
  getBackendPort: () => Promise<number>;
  getBackendStatus: () => Promise<boolean>;
  platform: string;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

// ===== 三模式架构 =====
export type AppMode = 'copilot' | 'builder' | 'agent';

export const MODE_CONFIG: Record<AppMode, { label: string; icon: string; color: string }> = {
  copilot: { label: 'Copilot', icon: '💬', color: 'blue' },
  builder: { label: 'Skill Builder', icon: '🔧', color: 'orange' },
  agent: { label: 'Agent', icon: '🤖', color: 'green' },
};

// ===== 消息类型 =====
export type MessageRole = 'system' | 'user' | 'assistant' | 'tool';

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
  createdAt: string;
}

// ===== 对话类型 =====
export interface Conversation {
  id: string;
  workspaceId: string;
  title: string;
  mode: AppMode;
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
  is_builtin: boolean;
  source_path: string;
}

export interface SkillParam {
  name: string;
  type: string;
  required: boolean;
  default?: string;
  description: string;
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
  message?: string;
}

export interface AgentExecutionEvent {
  type: 'execution_start' | 'step_start' | 'step_complete' | 'step_error' | 'complete' | 'error';
  step?: number;
  description?: string;
  result?: string;
  error?: string;
  message?: string;
  context?: {
    skill_id: string;
    skill_name: string;
    params: Record<string, unknown>;
    status: string;
    steps: {
      index: number;
      description: string;
      status: string;
      result?: string;
      error?: string;
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

