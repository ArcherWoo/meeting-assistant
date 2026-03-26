/**
 * API 服务层
 * 封装与 Python FastAPI 后端的所有 HTTP 通信
 * 支持流式 SSE 和普通 REST 请求
 */
import type {
  Role, LLMConfig, LLMConnectionTestResult, PPTParseResult,
  SkillMeta, SkillMatch,
  KnowhowRule, KnowhowExportData, KnowhowImportResult, KnowhowImportStrategy, KnowledgeStats, IngestResult,
  AgentMatchResult, AgentExecutionEvent,
  ContextMetadata, SkillSuggestionEvent,
  PromptModeConfig, PromptPack, PromptTemplate, PromptScope, SystemPromptMap, SystemPromptPreset,
} from '@/types';

/** 获取后端 API 基础 URL */
function getBaseUrl(): string {
  const configured = (import.meta.env.VITE_API_BASE_URL || '').trim();
  if (configured) {
    return configured.replace(/\/+$/, '');
  }
  return '/api';
}

// ===== 健康检查 =====

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${getBaseUrl()}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

// ===== 聊天接口 =====

interface ChatMessage {
  role: string;
  content: string;
}

/**
 * 流式聊天 - 返回 SSE 事件流
 * @param messages 消息列表
 * @param config LLM 配置
 * @param onChunk 每收到一个 chunk 的回调
 * @param onDone 流结束回调
 * @param onError 错误回调
 * @param signal 中止信号
 * @param mode 当前交互模式
 * @param onMetadata 上下文来源元数据回调（可选）
 * @param onSkillSuggestion Skill 推荐事件回调（可选）
 */
export async function streamChat(
  messages: ChatMessage[],
  config: LLMConfig,
  onChunk: (content: string) => void,
  onDone: () => void,
  onError: (error: string) => void,
  signal?: AbortSignal,
  mode?: string,
  ragQuery?: string,
  onMetadata?: (metadata: ContextMetadata) => void,
  onSkillSuggestion?: (suggestion: SkillSuggestionEvent) => void,
): Promise<void> {
  try {
    let finished = false;

    const handleDataLine = (line: string): boolean => {
      if (!line.startsWith('data: ')) return false;

      const data = line.slice(6).trim();

      if (data === '[DONE]') {
        finished = true;
        onDone();
        return true;
      }

      try {
        const parsed = JSON.parse(data);
        if (parsed.stream_error) {
          onError(parsed.stream_error);
          return true;
        }
        if (parsed.type === 'context_metadata') {
          onMetadata?.(parsed.sources as ContextMetadata);
          return false;
        }
        if (parsed.type === 'skill_suggestion') {
          onSkillSuggestion?.(parsed as SkillSuggestionEvent);
          return false;
        }

        const content = parsed.choices?.[0]?.delta?.content;
        if (content) {
          onChunk(content);
        }
      } catch {
        // 忽略无法解析的行
      }

      return false;
    };

    let buffer = '';

    const drainBuffer = (final = false): boolean => {
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const rawLine of lines) {
        if (handleDataLine(rawLine.trimEnd())) {
          return true;
        }
      }

      if (final && buffer.trim()) {
        const lastLine = buffer.trimEnd();
        buffer = '';
        if (handleDataLine(lastLine)) {
          return true;
        }
      }

      return false;
    };

    const res = await fetch(`${getBaseUrl()}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages,
        model: config.model,
        temperature: config.temperature,
        max_tokens: config.maxTokens,
        stream: true,
        api_url: config.apiUrl,
        api_key: config.apiKey,
        mode: mode ?? '',
        rag_query: ragQuery ?? '',
      }),
      signal,
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: '请求失败' }));
      onError(error.detail || `HTTP ${res.status}`);
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      onError('无法读取响应流');
      return;
    }

    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (value) {
        buffer += decoder.decode(value, { stream: !done });
        if (drainBuffer(done)) {
          return;
        }
      }

      if (done) {
        break;
      }
    }

    buffer += decoder.decode();
    if (drainBuffer(true)) {
      return;
    }

    if (!finished) {
      onError('响应流在收到 [DONE] 前意外结束');
    }
  } catch (error: any) {
    if (error.name === 'AbortError') {
      return;
    } else {
      onError(error.message || '网络错误');
    }
  }
}

// ===== 连接测试 =====

export async function testLLMConnection(
  apiUrl: string,
  apiKey: string,
  model?: string
): Promise<LLMConnectionTestResult> {
  const res = await fetch(`${getBaseUrl()}/chat/test-connection`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_url: apiUrl, api_key: apiKey, model: model ?? '' }),
  });
  const data = await res.json().catch(() => ({ detail: '连接测试失败' }));
  if (!res.ok) {
    throw new Error(data.detail || data.message || '连接测试失败');
  }
  return data;
}

// ===== PPT 解析 =====

export async function parsePPT(file: File): Promise<PPTParseResult> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${getBaseUrl()}/ppt/parse`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'PPT 解析失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

// ===== Phase 2: Skill 接口 =====

/** 获取所有已加载的 Skill 列表 */
export async function listSkills(): Promise<SkillMeta[]> {
  const res = await fetch(`${getBaseUrl()}/skills`);
  if (!res.ok) throw new Error('获取 Skill 列表失败');
  const data = await res.json();
  // 后端返回 { skills: [...], total: N }
  return Array.isArray(data) ? data : (data.skills ?? []);
}

/** 获取单个 Skill 详情 */
export async function getSkill(skillId: string): Promise<SkillMeta> {
  const res = await fetch(`${getBaseUrl()}/skills/${encodeURIComponent(skillId)}`);
  if (!res.ok) throw new Error('获取 Skill 详情失败');
  return res.json();
}

/** 获取 Skill 原始 Markdown 内容 */
export async function getSkillContent(skillId: string): Promise<{ id: string; content: string; source_path: string; is_builtin: boolean }> {
  const res = await fetch(`${getBaseUrl()}/skills/${encodeURIComponent(skillId)}/content`);
  if (!res.ok) throw new Error('获取 Skill 内容失败');
  return res.json();
}

/** 保存新 Skill（后端返回 {id, name, message, source_path}） */
export async function saveSkill(content: string, filename?: string): Promise<{ id: string; name: string; message: string }> {
  const res = await fetch(`${getBaseUrl()}/skills`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, filename }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '保存 Skill 失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 更新已有 Skill 内容 */
export async function updateSkill(skillId: string, content: string): Promise<{ id: string; name: string; message: string }> {
  const res = await fetch(`${getBaseUrl()}/skills/${encodeURIComponent(skillId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '更新 Skill 失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 删除用户自建或覆盖的 Skill */
export async function deleteSkill(skillId: string): Promise<{ id: string; message: string }> {
  const res = await fetch(`${getBaseUrl()}/skills/${encodeURIComponent(skillId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除 Skill 失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

// ===== 系统提示词接口 =====

/** 获取指定模式的 System Prompt */
export async function getSystemPrompt(
  mode: string
): Promise<{ mode: string; prompt: string; is_custom: boolean; resolved_prompt?: string; template_ids?: string[]; missing_variables?: string[] }> {
  const res = await fetch(`${getBaseUrl()}/settings/system-prompt/${encodeURIComponent(mode)}`);
  if (!res.ok) throw new Error('获取 System Prompt 失败');
  return res.json();
}

/** 保存指定模式的 System Prompt */
export async function updateSystemPrompt(
  mode: string,
  prompt: string
): Promise<{ mode: string; prompt: string; resolved_prompt?: string; message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/system-prompt/${encodeURIComponent(mode)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '保存 System Prompt 失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 重置指定模式的 System Prompt 为默认值 */
export async function resetSystemPrompt(
  mode: string
): Promise<{ mode: string; prompt: string; resolved_prompt?: string; message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/system-prompt/${encodeURIComponent(mode)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '重置 System Prompt 失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function getSystemPrompts(): Promise<{
  prompts: SystemPromptMap;
  defaults: SystemPromptMap;
  custom_modes: string[];
}> {
  const res = await fetch(`${getBaseUrl()}/settings/system-prompts`);
  if (!res.ok) throw new Error('获取 System Prompts 失败');
  return res.json();
}

export async function updateSystemPrompts(
  prompts: SystemPromptMap
): Promise<{ prompts: SystemPromptMap; defaults: SystemPromptMap; custom_modes: string[]; message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/system-prompts`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompts }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '保存 System Prompts 失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function listSystemPromptPresets(): Promise<SystemPromptPreset[]> {
  const res = await fetch(`${getBaseUrl()}/settings/system-prompt-presets`);
  if (!res.ok) throw new Error('获取 System Prompt 预设失败');
  const data = await res.json();
  return Array.isArray(data) ? data : (data.presets ?? []);
}

export async function createSystemPromptPreset(
  name: string,
  mode: string,
  prompt: string
): Promise<{ preset: SystemPromptPreset; message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/system-prompt-presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, mode, prompt }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '保存预设失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function deleteSystemPromptPreset(presetId: string): Promise<{ id: string; message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/system-prompt-presets/${encodeURIComponent(presetId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除预设失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function listPromptTemplates(scope?: PromptScope): Promise<PromptTemplate[]> {
  const query = scope ? `?scope=${encodeURIComponent(scope)}` : '';
  const res = await fetch(`${getBaseUrl()}/settings/prompt-templates${query}`);
  if (!res.ok) throw new Error('获取提示词模板失败');
  const data = await res.json();
  return Array.isArray(data) ? data : (data.templates ?? []);
}

export async function listPromptPacks(): Promise<PromptPack[]> {
  const res = await fetch(`${getBaseUrl()}/settings/prompt-packs`);
  if (!res.ok) throw new Error('获取官方模板包失败');
  const data = await res.json();
  return Array.isArray(data) ? data : (data.packs ?? []);
}

export async function createPromptTemplate(
  payload: Pick<PromptTemplate, 'name' | 'description' | 'scope' | 'content' | 'variables'>
): Promise<{ template: PromptTemplate; message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/prompt-templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '创建提示词模板失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function updatePromptTemplate(
  templateId: string,
  payload: Partial<Pick<PromptTemplate, 'name' | 'description' | 'scope' | 'content' | 'variables'>>
): Promise<{ template: PromptTemplate; message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/prompt-templates/${encodeURIComponent(templateId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '更新提示词模板失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function deletePromptTemplate(templateId: string): Promise<{ id: string; message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/prompt-templates/${encodeURIComponent(templateId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除提示词模板失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function getPromptConfig(mode: string): Promise<PromptModeConfig> {
  const res = await fetch(`${getBaseUrl()}/settings/prompt-config/${encodeURIComponent(mode)}`);
  if (!res.ok) throw new Error('获取提示词挂载配置失败');
  return res.json();
}

export async function updatePromptConfig(
  mode: string,
  payload: Pick<PromptModeConfig, 'template_ids' | 'variables' | 'extra_prompt'>
): Promise<PromptModeConfig & { message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/prompt-config/${encodeURIComponent(mode)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '保存提示词挂载配置失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function resetPromptConfig(
  mode: string
): Promise<PromptModeConfig & { message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/prompt-config/${encodeURIComponent(mode)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '重置提示词挂载配置失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 匹配用户输入到最佳 Skill，返回命中列表（后端返回 {matches: [...], total: N}） */
export async function applyPromptPack(
  packId: string,
  payload: { modes: string[]; strategy?: 'append' | 'replace' }
): Promise<{
  pack: PromptPack;
  strategy: 'append' | 'replace';
  results: Array<{
    mode: string;
    status: 'applied' | 'skipped';
    applied_template_ids: string[];
    template_ids: string[];
    missing_variables?: string[];
  }>;
  message: string;
}> {
  const res = await fetch(`${getBaseUrl()}/settings/prompt-packs/${encodeURIComponent(packId)}/apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '应用模板包失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function matchSkill(query: string): Promise<SkillMatch[]> {
  const res = await fetch(`${getBaseUrl()}/skills/match`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error('Skill 匹配失败');
  const data = await res.json();
  return Array.isArray(data) ? data : (data.matches ?? []);
}

// ===== Phase 2: Know-how 接口 =====

/** 获取 Know-how 规则列表（后端返回 {rules: [...], total: N}） */
export async function listKnowhowRules(category?: string, activeOnly?: boolean): Promise<KnowhowRule[]> {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  if (typeof activeOnly === 'boolean') params.set('active_only', String(activeOnly));

  const query = params.toString();
  const res = await fetch(`${getBaseUrl()}/knowhow${query ? `?${query}` : ''}`);
  if (!res.ok) throw new Error('获取规则列表失败');
  const data = await res.json();
  return Array.isArray(data) ? data : (data.rules ?? []);
}

/** 创建 Know-how 规则（后端返回 {id, message}） */
export async function createKnowhowRule(
  rule: Pick<KnowhowRule, 'category' | 'rule_text' | 'weight' | 'source'>
): Promise<{ id: string; message: string }> {
  const res = await fetch(`${getBaseUrl()}/knowhow`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(rule),
  });
  if (!res.ok) throw new Error('创建规则失败');
  return res.json();
}

/** 更新 Know-how 规则（后端返回完整规则对象） */
export async function updateKnowhowRule(
  ruleId: string,
  updates: Partial<Pick<KnowhowRule, 'category' | 'rule_text' | 'weight' | 'is_active'>>
): Promise<KnowhowRule> {
  const res = await fetch(`${getBaseUrl()}/knowhow/${encodeURIComponent(ruleId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error('更新规则失败');
  return res.json();
}

/** 删除 Know-how 规则 */
export async function deleteKnowhowRule(ruleId: string): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/knowhow/${encodeURIComponent(ruleId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('删除规则失败');
}

/** 获取 Know-how 分类列表（含每个分类的规则数） */
export async function listKnowhowCategories(): Promise<{ name: string; rule_count: number }[]> {
  const res = await fetch(`${getBaseUrl()}/knowhow/categories`);
  if (!res.ok) throw new Error('获取分类列表失败');
  const data = await res.json();
  return data.categories ?? [];
}

/** 重命名分类（批量更新该分类下所有规则的 category） */
export async function renameKnowhowCategory(
  oldName: string,
  newName: string
): Promise<{ message: string; affected_rules: number }> {
  const res = await fetch(`${getBaseUrl()}/knowhow/categories/${encodeURIComponent(oldName)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_name: newName }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '重命名分类失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 删除分类（deleteRules=true 则同时删除该分类下的所有规则） */
export async function deleteKnowhowCategory(
  name: string,
  deleteRules = true
): Promise<{ message: string; affected_rules: number }> {
  const url = `${getBaseUrl()}/knowhow/categories/${encodeURIComponent(name)}?delete_rules=${deleteRules}`;
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除分类失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 获取 Know-how 统计信息（后端返回 {total_rules, active_rules, categories, total_hits}） */
export async function getKnowhowStats(): Promise<{
  total_rules: number;
  active_rules: number;
  categories: string[];
  total_hits: number;
}> {
  const res = await fetch(`${getBaseUrl()}/knowhow/stats`);
  if (!res.ok) throw new Error('获取规则统计失败');
  return res.json();
}

/** 导出当前 Know-how 规则库 */
export async function exportKnowhowRules(): Promise<KnowhowExportData> {
  const res = await fetch(`${getBaseUrl()}/knowhow/export`);
  if (!res.ok) throw new Error('导出规则库失败');
  return res.json();
}

/** 导入 Know-how 规则库 */
export async function importKnowhowRules(
  payload: unknown,
  strategy: KnowhowImportStrategy = 'append'
): Promise<KnowhowImportResult> {
  const res = await fetch(`${getBaseUrl()}/knowhow/import?strategy=${encodeURIComponent(strategy)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '导入规则库失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

// ===== Phase 2: 知识库接口 =====

export interface BatchIngestResult {
  results: IngestResult[];
  errors: Array<{ filename: string; error: string }>;
  total: number;
  success_count: number;
  failed_count: number;
}

export interface ExtractedTextResult {
  filename: string;
  file_type: string;
  text: string;
  char_count: number;
}

export interface BatchExtractTextResult {
  files: ExtractedTextResult[];
  errors: Array<{ filename: string; error: string }>;
  total: number;
  success_count: number;
  failed_count: number;
}

/** 批量上传文件到知识库（支持 PPT/PDF/DOCX/图片/文本等） */
export async function uploadFiles(files: File[]): Promise<BatchIngestResult> {
  if (files.length === 0) {
    return { results: [], errors: [], total: 0, success_count: 0, failed_count: 0 };
  }
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  const res = await fetch(`${getBaseUrl()}/knowledge/ingest`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '知识库导入失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 上传单个文件到知识库（兼容旧调用方） */
export async function uploadFile(file: File): Promise<IngestResult> {
  const result = await uploadFiles([file]);
  if (result.results.length > 0) {
    return result.results[0];
  }
  throw new Error(result.errors[0]?.error || '知识库导入失败');
}

/** 批量提取文件文本内容（不写入知识库，用于附件模式） */
export async function extractFilesText(files: File[]): Promise<BatchExtractTextResult> {
  if (files.length === 0) {
    return { files: [], errors: [], total: 0, success_count: 0, failed_count: 0 };
  }
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  const res = await fetch(`${getBaseUrl()}/knowledge/extract-text`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '文件文本提取失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 提取单个文件文本内容（兼容旧调用方） */
export async function extractFileText(file: File): Promise<ExtractedTextResult> {
  const result = await extractFilesText([file]);
  if (result.files.length > 0) {
    return result.files[0];
  }
  throw new Error(result.errors[0]?.error || '文件文本提取失败');
}

/** 获取已导入文件列表 */
export async function listKnowledgeImports(): Promise<{ imports: Array<{ id: string; file_name: string; file_size: number; slide_count: number; import_status: string; imported_at: string }>; total: number }> {
  const res = await fetch(`${getBaseUrl()}/knowledge/imports`);
  if (!res.ok) throw new Error('获取导入列表失败');
  return res.json();
}

/** 删除知识库导入记录 */
export async function deleteKnowledgeImport(importId: string): Promise<{ deleted: boolean; filename: string }> {
  const res = await fetch(`${getBaseUrl()}/knowledge/imports/${encodeURIComponent(importId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 知识库混合检索 */
export async function queryKnowledge(
  query: string,
  filters?: { category?: string; min_amount?: number; max_amount?: number }
): Promise<{ results: Record<string, unknown>[]; analysis?: string }> {
  const res = await fetch(`${getBaseUrl()}/knowledge/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, ...filters }),
  });
  if (!res.ok) throw new Error('知识库检索失败');
  return res.json();
}

/** 获取知识库统计信息 */
export async function getKnowledgeStats(): Promise<KnowledgeStats> {
  const res = await fetch(`${getBaseUrl()}/knowledge/stats`);
  if (!res.ok) throw new Error('获取知识库统计失败');
  return res.json();
}

// ===== Phase 2: Agent 执行接口 =====

/** Agent 模式 - 匹配 Skill */
export async function agentMatch(
  query: string
): Promise<AgentMatchResult> {
  const res = await fetch(`${getBaseUrl()}/agent/match`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error('Agent 匹配失败');
  return res.json();
}

/** Agent 模式 - 执行 Skill（SSE 流式） */
export async function agentExecute(
  skillId: string,
  params: Record<string, unknown>,
  onEvent: (event: AgentExecutionEvent) => void,
  onError: (error: string) => void,
  signal?: AbortSignal
): Promise<void> {
  try {
    const res = await fetch(`${getBaseUrl()}/agent/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_id: skillId, params }),
      signal,
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Agent 执行失败' }));
      onError(error.detail || `HTTP ${res.status}`);
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      onError('无法读取响应流');
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6).trim();
        if (!data) continue;

        try {
          const event = JSON.parse(data) as AgentExecutionEvent;
          onEvent(event);
        } catch {
          // 忽略无法解析的行
        }
      }
    }
  } catch (error: unknown) {
    const err = error as Error;
    if (err.name === 'AbortError') return;
    onError(err.message || '网络错误');
  }
}

// ===== 对话自动命名 =====

/**
 * 根据前 3 轮对话消息，调用 LLM 生成语义化中文标题（10 字以内）
 * @param messages 前 6 条消息（3 user + 3 assistant）
 * @param config LLM 配置
 * @returns 生成的标题字符串
 */
export async function generateAutoTitle(
  messages: ChatMessage[],
  config: LLMConfig
): Promise<string> {
  const res = await fetch(`${getBaseUrl()}/chat/auto-title`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: messages.slice(0, 6),
      api_url: config.apiUrl,
      api_key: config.apiKey,
      model: config.model,
    }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '标题生成失败' }));
    throw new Error(error.detail);
  }
  const data = await res.json();
  return data.title as string;
}

// ===== Embedding 配置 =====

export interface EmbeddingConfig {
  api_url: string;
  api_key: string;
  model: string;
  is_configured: boolean;
}

/** 获取 Embedding API 配置 */
export async function getEmbeddingConfig(): Promise<EmbeddingConfig> {
  const res = await fetch(`${getBaseUrl()}/settings/embedding`);
  if (!res.ok) throw new Error('获取 Embedding 配置失败');
  return res.json();
}

/** 保存 Embedding API 配置 */
export async function updateEmbeddingConfig(
  config: Pick<EmbeddingConfig, 'api_url' | 'api_key' | 'model'>
): Promise<{ message: string; is_configured: boolean }> {
  const res = await fetch(`${getBaseUrl()}/settings/embedding`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error('保存 Embedding 配置失败');
  return res.json();
}

/** 清除 Embedding API 配置（回退到使用 LLM API 凭证） */
export async function resetEmbeddingConfig(): Promise<{ message: string }> {
  const res = await fetch(`${getBaseUrl()}/settings/embedding`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('清除 Embedding 配置失败');
  return res.json();
}

/** 测试 Embedding API 连通性 */
export async function testEmbeddingConnection(
  config: Pick<EmbeddingConfig, 'api_url' | 'api_key' | 'model'>
): Promise<{ success: boolean; message: string; dimension?: number }> {
  const res = await fetch(`${getBaseUrl()}/settings/embedding/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error('测试请求失败');
  return res.json();
}

// ===== Role CRUD =====

/** 获取所有角色列表 */
export async function listRoles(): Promise<Role[]> {
  const res = await fetch(`${getBaseUrl()}/settings/roles`);
  if (!res.ok) throw new Error('获取角色列表失败');
  const data = await res.json();
  return data.roles as Role[];
}

/** 创建新角色 */
export async function createRole(payload: {
  name: string;
  icon?: string;
  description?: string;
  system_prompt?: string;
  capabilities?: string[];
}): Promise<Role> {
  const res = await fetch(`${getBaseUrl()}/settings/roles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('创建角色失败');
  const data = await res.json();
  return data.role as Role;
}

/** 更新角色 */
export async function updateRole(
  roleId: string,
  payload: Partial<{
    name: string;
    icon: string;
    description: string;
    system_prompt: string;
    capabilities: string[];
    sort_order: number;
  }>
): Promise<Role> {
  const res = await fetch(`${getBaseUrl()}/settings/roles/${roleId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('更新角色失败');
  const data = await res.json();
  return data.role as Role;
}

/** 删除角色 */
export async function deleteRole(roleId: string): Promise<void> {
  const res = await fetch(`${getBaseUrl()}/settings/roles/${roleId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '删除角色失败');
  }
}
