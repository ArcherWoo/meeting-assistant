/**
 * API 服务层
 * 封装与 Python FastAPI 后端的所有 HTTP 通信
 * 支持流式 SSE 和普通 REST 请求
 */
import type {
  Role, LLMConfig, LLMConnectionTestResult, LLMProfile, PPTParseResult,
  SkillMeta, SkillMatch,
  KnowhowRule, KnowhowCategory, KnowhowExportData, KnowhowImportResult, KnowhowImportStrategy, KnowledgeStats, IngestResult,
  AgentMatchResult, AgentExecutionEvent, AgentRunCancelResponse, AgentRunRecord,
  ContextMetadata, SkillSuggestionEvent, ChatStatusEvent,
  SystemPromptPreset,
  Conversation, Message,
  User, AuthResponse, Group, AccessGrant,
} from '@/types';

/** 获取后端 API 基础 URL */
function getBaseUrl(): string {
  const configured = (import.meta.env.VITE_API_BASE_URL || '').trim();
  if (configured) {
    return configured.replace(/\/+$/, '');
  }
  return '/api';
}

// ===== 认证辅助 =====

const AUTH_STORAGE_KEY = 'CPSC AI 中台 智枢-auth';

/** 从 localStorage 读取 JWT token */
function getToken(): string | null {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    return data?.state?.token ?? null;
  } catch {
    return null;
  }
}

/** 带 JWT 认证头的 fetch 包装 */
export function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
}

function canReadStreamingBody(response: Response): response is Response & { body: ReadableStream<Uint8Array> } {
  return Boolean(
    response.body
    && typeof (response.body as ReadableStream<Uint8Array>).getReader === 'function'
    && typeof TextDecoder !== 'undefined',
  );
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

export interface ChatStatePayload {
  workspace_id: string;
  conversations: Conversation[];
  messages_by_conversation: Record<string, Message[]>;
}

export async function getChatState(): Promise<ChatStatePayload> {
  const res = await authFetch(`${getBaseUrl()}/chat/state`);
  if (!res.ok) throw new Error('获取会话状态失败');
  return res.json();
}

export async function createConversationRecord(
  roleId: string,
  surface: 'chat' | 'agent' = 'chat',
  title = '新对话'
): Promise<Conversation> {
  const res = await authFetch(`${getBaseUrl()}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role_id: roleId, surface, title }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '创建对话失败' }));
    throw new Error(error.detail || '创建对话失败');
  }
  const data = await res.json();
  return data.conversation as Conversation;
}

export async function updateConversationRecord(
  conversationId: string,
  payload: Partial<{
    title: string;
    surface: 'chat' | 'agent';
    role_id: string;
    is_pinned: boolean;
    is_title_customized: boolean;
  }>
): Promise<Conversation> {
  const res = await authFetch(`${getBaseUrl()}/conversations/${encodeURIComponent(conversationId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '更新对话失败' }));
    throw new Error(error.detail || '更新对话失败');
  }
  const data = await res.json();
  return data.conversation as Conversation;
}

export async function deleteConversationRecord(conversationId: string): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/conversations/${encodeURIComponent(conversationId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除对话失败' }));
    throw new Error(error.detail || '删除对话失败');
  }
}

export async function createMessageRecord(
  conversationId: string,
  payload: Pick<Message, 'role' | 'content'> & Partial<Pick<Message, 'model' | 'tokenInput' | 'tokenOutput' | 'durationMs' | 'metadata' | 'attachments'>>
): Promise<Message> {
  const res = await authFetch(`${getBaseUrl()}/conversations/${encodeURIComponent(conversationId)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      role: payload.role,
      content: payload.content,
      model: payload.model ?? '',
      token_input: payload.tokenInput ?? 0,
      token_output: payload.tokenOutput ?? 0,
      duration_ms: payload.durationMs ?? 0,
      metadata: payload.metadata ?? {},
      attachments: payload.attachments ?? [],
    }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '创建消息失败' }));
    throw new Error(error.detail || '创建消息失败');
  }
  const data = await res.json();
  return data.message as Message;
}

export async function updateMessageRecord(
  messageId: string,
  payload: Partial<Pick<Message, 'content' | 'model' | 'tokenInput' | 'tokenOutput' | 'durationMs' | 'metadata' | 'attachments'>>
): Promise<Message> {
  const res = await authFetch(`${getBaseUrl()}/messages/${encodeURIComponent(messageId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...(payload.content !== undefined ? { content: payload.content } : {}),
      ...(payload.model !== undefined ? { model: payload.model } : {}),
      ...(payload.tokenInput !== undefined ? { token_input: payload.tokenInput } : {}),
      ...(payload.tokenOutput !== undefined ? { token_output: payload.tokenOutput } : {}),
      ...(payload.durationMs !== undefined ? { duration_ms: payload.durationMs } : {}),
      ...(payload.metadata !== undefined ? { metadata: payload.metadata } : {}),
      ...(payload.attachments !== undefined ? { attachments: payload.attachments } : {}),
    }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '更新消息失败' }));
    throw new Error(error.detail || '更新消息失败');
  }
  const data = await res.json();
  return data.message as Message;
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
  conversationId?: string,
  roleId?: string,
  ragQuery?: string,
  attachmentPrepareMs?: number,
  onMetadata?: (metadata: ContextMetadata) => void,
  onSkillSuggestion?: (suggestion: SkillSuggestionEvent) => void,
  onStatus?: (status: ChatStatusEvent) => void,
  onUsage?: (usage: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }) => void,
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
        if (parsed.type === 'status') {
          onStatus?.(parsed as ChatStatusEvent);
          return false;
        }
        if (parsed.usage && typeof parsed.usage === 'object') {
          onUsage?.(parsed.usage as { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number });
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

    const res = await authFetch(`${getBaseUrl()}/chat/completions`, {
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
        llm_profile_id: (config as Partial<LLMProfile>).id ?? '',
        conversation_id: conversationId ?? '',
        role_id: roleId ?? '',
        rag_query: ragQuery ?? '',
        attachment_prepare_ms: Math.max(0, Math.round(attachmentPrepareMs ?? 0)),
      }),
      signal,
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: '请求失败' }));
      onError(error.detail || `HTTP ${res.status}`);
      return;
    }
    if (!canReadStreamingBody(res)) {
      buffer += await res.text();
      if (drainBuffer(true)) {
        return;
      }
      if (!finished) {
        onDone();
      }
      return;
    }

    const reader = res.body.getReader();
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
  const res = await authFetch(`${getBaseUrl()}/chat/test-connection`, {
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

export async function listLLMProfiles(): Promise<{ profiles: LLMProfile[]; activeProfileId: string }> {
  const res = await authFetch(`${getBaseUrl()}/settings/llm-profiles`);
  if (!res.ok) throw new Error('获取模型配置失败');
  const data = await res.json();
  const profiles = Array.isArray(data.profiles) ? data.profiles.map((profile: any) => ({
    id: profile.id,
    name: profile.name,
    apiUrl: profile.api_url ?? '',
    apiKey: profile.api_key ?? '',
    hasApiKey: profile.has_api_key ?? Boolean(profile.api_key),
    model: profile.model ?? 'gpt-4o',
    temperature: profile.temperature ?? 0.7,
    maxTokens: profile.max_tokens ?? 4096,
    stream: profile.stream ?? true,
    availableModels: Array.isArray(profile.available_models) ? profile.available_models : [],
  })) : [];
  return {
    profiles,
    activeProfileId: data.active_profile_id ?? '',
  };
}

export async function createLLMProfile(profile: LLMProfile): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/settings/llm-profiles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      id: profile.id,
      name: profile.name,
      api_url: profile.apiUrl,
      api_key: profile.apiKey,
      model: profile.model,
      temperature: profile.temperature,
      max_tokens: profile.maxTokens,
      stream: profile.stream,
      available_models: profile.availableModels ?? [],
    }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '创建模型配置失败' }));
    throw new Error(error.detail || '创建模型配置失败');
  }
}

export async function updateLLMProfile(profile: LLMProfile): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/settings/llm-profiles/${encodeURIComponent(profile.id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: profile.name,
      api_url: profile.apiUrl,
      api_key: profile.apiKey,
      model: profile.model,
      temperature: profile.temperature,
      max_tokens: profile.maxTokens,
      stream: profile.stream,
      available_models: profile.availableModels ?? [],
    }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '更新模型配置失败' }));
    throw new Error(error.detail || '更新模型配置失败');
  }
}

export async function deleteLLMProfile(profileId: string): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/settings/llm-profiles/${encodeURIComponent(profileId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除模型配置失败' }));
    throw new Error(error.detail || '删除模型配置失败');
  }
}

export async function setActiveLLMProfile(profileId: string): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/settings/llm-profiles-active`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile_id: profileId }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '切换默认模型失败' }));
    throw new Error(error.detail || '切换默认模型失败');
  }
}

// ===== PPT 解析 =====

export async function parsePPT(file: File): Promise<PPTParseResult> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await authFetch(`${getBaseUrl()}/ppt/parse`, {
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
  const res = await authFetch(`${getBaseUrl()}/skills`);
  if (!res.ok) throw new Error('获取 Skill 列表失败');
  const data = await res.json();
  // 后端返回 { skills: [...], total: N }
  return Array.isArray(data) ? data : (data.skills ?? []);
}

/** 获取单个 Skill 详情 */
export async function getSkill(skillId: string): Promise<SkillMeta> {
  const res = await authFetch(`${getBaseUrl()}/skills/${encodeURIComponent(skillId)}`);
  if (!res.ok) throw new Error('获取 Skill 详情失败');
  return res.json();
}

export async function createKnowhowCategory(
  name: string
): Promise<{ message: string; category: { name: string; rule_count: number } }> {
  const res = await authFetch(`${getBaseUrl()}/knowhow/categories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '创建分类失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 获取 Skill 原始 Markdown 内容 */
export async function getSkillContent(skillId: string): Promise<{ id: string; content: string; source_path: string; is_builtin: boolean }> {
  const res = await authFetch(`${getBaseUrl()}/skills/${encodeURIComponent(skillId)}/content`);
  if (!res.ok) throw new Error('获取 Skill 内容失败');
  return res.json();
}

/** 保存新 Skill（后端返回 {id, name, message, source_path}） */
export async function saveSkill(content: string, filename?: string): Promise<{ id: string; name: string; message: string }> {
  const res = await authFetch(`${getBaseUrl()}/skills`, {
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
  const res = await authFetch(`${getBaseUrl()}/skills/${encodeURIComponent(skillId)}`, {
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
  const res = await authFetch(`${getBaseUrl()}/skills/${encodeURIComponent(skillId)}`, {
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
  roleId: string
): Promise<{ role_id: string; prompt: string; default_prompt?: string; is_custom: boolean; resolved_prompt?: string }> {
  const res = await authFetch(`${getBaseUrl()}/settings/system-prompt/${encodeURIComponent(roleId)}`);
  if (!res.ok) throw new Error('获取 System Prompt 失败');
  return res.json();
}

/** 保存指定模式的 System Prompt */
export async function updateSystemPrompt(
  roleId: string,
  prompt: string
): Promise<{ role_id: string; prompt: string; default_prompt?: string; resolved_prompt?: string; message: string }> {
  const res = await authFetch(`${getBaseUrl()}/settings/system-prompt/${encodeURIComponent(roleId)}`, {
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
  roleId: string
): Promise<{ role_id: string; prompt: string; default_prompt?: string; resolved_prompt?: string; message: string }> {
  const res = await authFetch(`${getBaseUrl()}/settings/system-prompt/${encodeURIComponent(roleId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '重置 System Prompt 失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function listSystemPromptPresets(): Promise<SystemPromptPreset[]> {
  const res = await authFetch(`${getBaseUrl()}/settings/system-prompt-presets`);
  if (!res.ok) throw new Error('获取 System Prompt 预设失败');
  const data = await res.json();
  return Array.isArray(data) ? data : (data.presets ?? []);
}

export async function createSystemPromptPreset(
  name: string,
  roleId: string,
  prompt: string
): Promise<{ preset: SystemPromptPreset; message: string }> {
  const res = await authFetch(`${getBaseUrl()}/settings/system-prompt-presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, role_id: roleId, prompt }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '保存预设失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function deleteSystemPromptPreset(presetId: string): Promise<{ id: string; message: string }> {
  const res = await authFetch(`${getBaseUrl()}/settings/system-prompt-presets/${encodeURIComponent(presetId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除预设失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

export async function matchSkill(query: string): Promise<SkillMatch[]> {
  const res = await authFetch(`${getBaseUrl()}/skills/match`, {
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
  const res = await authFetch(`${getBaseUrl()}/knowhow${query ? `?${query}` : ''}`);
  if (!res.ok) throw new Error('获取规则列表失败');
  const data = await res.json();
  return Array.isArray(data) ? data : (data.rules ?? []);
}

/** 创建 Know-how 规则（后端返回 {id, message}） */
export async function createKnowhowRule(
  rule: Pick<KnowhowRule, 'category' | 'rule_text' | 'weight' | 'source'> & {
    share_to_group?: boolean;
  }
): Promise<{ id: string; message: string }> {
  const res = await authFetch(`${getBaseUrl()}/knowhow`, {
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
  updates: Partial<Pick<KnowhowRule, 'category' | 'rule_text' | 'weight' | 'is_active' | 'share_to_group'>>
): Promise<KnowhowRule> {
  const res = await authFetch(`${getBaseUrl()}/knowhow/${encodeURIComponent(ruleId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error('更新规则失败');
  return res.json();
}

/** 删除 Know-how 规则 */
export async function deleteKnowhowRule(ruleId: string): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/knowhow/${encodeURIComponent(ruleId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('删除规则失败');
}

/** 获取 Know-how 分类列表（含每个分类的规则数） */
export async function listKnowhowCategories(): Promise<KnowhowCategory[]> {
  const res = await authFetch(`${getBaseUrl()}/knowhow/categories`);
  if (!res.ok) throw new Error('获取分类列表失败');
  const data = await res.json();
  return data.categories ?? [];
}

/** 重命名分类（批量更新该分类下所有规则的 category） */
export async function renameKnowhowCategory(
  oldName: string,
  newName: string
): Promise<{ message: string; affected_rules: number }> {
  const res = await authFetch(`${getBaseUrl()}/knowhow/categories/${encodeURIComponent(oldName)}`, {
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
  const res = await authFetch(url, { method: 'DELETE' });
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
  const res = await authFetch(`${getBaseUrl()}/knowhow/stats`);
  if (!res.ok) throw new Error('获取规则统计失败');
  return res.json();
}

/** 导出当前 Know-how 规则库 */
export async function exportKnowhowRules(): Promise<KnowhowExportData> {
  const res = await authFetch(`${getBaseUrl()}/knowhow/export`);
  if (!res.ok) throw new Error('导出规则库失败');
  return res.json();
}

/** 导入 Know-how 规则库 */
export async function importKnowhowRules(
  payload: unknown,
  strategy: KnowhowImportStrategy = 'append'
): Promise<KnowhowImportResult> {
  const res = await authFetch(`${getBaseUrl()}/knowhow/import?strategy=${encodeURIComponent(strategy)}`, {
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
export async function uploadFiles(files: File[], isEncrypted: boolean = true): Promise<BatchIngestResult> {
  if (files.length === 0) {
    return { results: [], errors: [], total: 0, success_count: 0, failed_count: 0 };
  }
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  formData.append('is_encrypted', String(isEncrypted));
  const res = await authFetch(`${getBaseUrl()}/knowledge/ingest`, {
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
export async function uploadFile(file: File, isEncrypted: boolean = true): Promise<IngestResult> {
  const result = await uploadFiles([file], isEncrypted);
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
  formData.append('fast_mode', 'true');
  const res = await authFetch(`${getBaseUrl()}/knowledge/extract-text`, {
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
  const res = await authFetch(`${getBaseUrl()}/knowledge/imports`);
  if (!res.ok) throw new Error('获取导入列表失败');
  return res.json();
}

/** 删除知识库导入记录 */
export async function deleteKnowledgeImport(importId: string): Promise<{ deleted: boolean; filename: string }> {
  const res = await authFetch(`${getBaseUrl()}/knowledge/imports/${encodeURIComponent(importId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '删除失败' }));
    throw new Error(error.detail);
  }
  return res.json();
}

/** 知识库混合检索 */
export async function downloadAgentArtifact(downloadUrl: string, filename: string): Promise<void> {
  const res = await authFetch(downloadUrl);
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '下载文件失败' }));
    throw new Error(error.detail || '下载文件失败');
  }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}

export async function queryKnowledge(
  query: string,
  filters?: { category?: string; min_amount?: number; max_amount?: number }
): Promise<{ results: Record<string, unknown>[]; analysis?: string }> {
  const res = await authFetch(`${getBaseUrl()}/knowledge/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, ...filters }),
  });
  if (!res.ok) throw new Error('知识库检索失败');
  return res.json();
}

/** 获取知识库统计信息 */
export async function getKnowledgeStats(): Promise<KnowledgeStats> {
  const res = await authFetch(`${getBaseUrl()}/knowledge/stats`);
  if (!res.ok) throw new Error('获取知识库统计失败');
  return res.json();
}

// ===== Phase 2: Agent 执行接口 =====

/** Agent 模式 - 匹配 Skill */
export async function agentMatch(
  query: string,
  roleId?: string
): Promise<AgentMatchResult> {
  const res = await authFetch(`${getBaseUrl()}/agent/match`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, role_id: roleId }),
  });
  if (!res.ok) throw new Error('Agent 匹配失败');
  return res.json();
}

/** Agent 模式 - 执行 Skill（SSE 流式） */
export async function agentExecute(
  roleId: string,
  query: string,
  skillId: string | undefined,
  params: Record<string, unknown>,
  config: Pick<LLMConfig, 'apiUrl' | 'apiKey' | 'model'>,
  onEvent: (event: AgentExecutionEvent) => void,
  onError: (error: string) => void,
  signal?: AbortSignal,
  options?: {
    conversationId?: string;
    runId?: string;
    continueFromRunId?: string;
    continueMode?: 'continue' | 'retry';
    continueNotes?: string;
    llmProfileId?: string;
    clientContext?: Record<string, unknown>;
  }
): Promise<void> {
  try {
    const res = await authFetch(`${getBaseUrl()}/agent/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        role_id: roleId,
        query,
        skill_id: skillId,
        params,
        conversation_id: options?.conversationId,
        run_id: options?.runId,
        continue_from_run_id: options?.continueFromRunId,
        continue_mode: options?.continueMode,
        continue_notes: options?.continueNotes,
        llm_profile_id: options?.llmProfileId,
        client_context: options?.clientContext ?? {},
        api_url: config.apiUrl,
        api_key: config.apiKey,
        model: config.model,
      }),
      signal,
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Agent 执行失败' }));
      onError(error.detail || `HTTP ${res.status}`);
      return;
    }
    let buffer = '';

    if (!canReadStreamingBody(res)) {
      buffer += await res.text();
      const lines = buffer.split('\n');
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6).trim();
        if (!data) continue;

        try {
          const event = JSON.parse(data) as AgentExecutionEvent;
          onEvent(event);
        } catch {
          // 忽略无法解析的事件行
        }
      }
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

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

export async function cancelAgentRun(runId: string): Promise<AgentRunCancelResponse> {
  const res = await authFetch(`${getBaseUrl()}/agent/runs/${encodeURIComponent(runId)}/cancel`, {
    method: 'POST',
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '取消 Agent 执行失败' }));
    throw new Error(error.detail || '取消 Agent 执行失败');
  }
  return res.json();
}

// ===== 对话自动命名 =====

/**
 * 根据前 3 轮对话消息，调用 LLM 生成语义化中文标题（10 字以内）
 * @param messages 前 6 条消息（3 user + 3 assistant）
 * @param config LLM 配置
 * @returns 生成的标题字符串
 */
export async function getAgentRun(runId: string): Promise<AgentRunRecord> {
  const res = await authFetch(`${getBaseUrl()}/agent/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: '获取 Agent 执行记录失败' }));
    throw new Error(error.detail || '获取 Agent 执行记录失败');
  }
  const data = await res.json();
  return data.run as AgentRunRecord;
}

export async function generateAutoTitle(
  messages: ChatMessage[],
  config: LLMConfig
): Promise<string> {
  const res = await authFetch(`${getBaseUrl()}/chat/auto-title`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      messages: messages.slice(0, 6),
      api_url: config.apiUrl,
      api_key: config.apiKey,
      llm_profile_id: (config as Partial<LLMProfile>).id ?? '',
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
  const res = await authFetch(`${getBaseUrl()}/settings/embedding`);
  if (!res.ok) throw new Error('获取 Embedding 配置失败');
  return res.json();
}

/** 保存 Embedding API 配置 */
export async function updateEmbeddingConfig(
  config: Pick<EmbeddingConfig, 'api_url' | 'api_key' | 'model'>
): Promise<{ message: string; is_configured: boolean }> {
  const res = await authFetch(`${getBaseUrl()}/settings/embedding`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error('保存 Embedding 配置失败');
  return res.json();
}

/** 清除 Embedding API 配置（回退到使用 LLM API 凭证） */
export async function resetEmbeddingConfig(): Promise<{ message: string }> {
  const res = await authFetch(`${getBaseUrl()}/settings/embedding`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('清除 Embedding 配置失败');
  return res.json();
}

/** 测试 Embedding API 连通性 */
export async function testEmbeddingConnection(
  config: Pick<EmbeddingConfig, 'api_url' | 'api_key' | 'model'>
): Promise<{ success: boolean; message: string; dimension?: number }> {
  const res = await authFetch(`${getBaseUrl()}/settings/embedding/test`, {
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
  const res = await authFetch(`${getBaseUrl()}/settings/roles`);
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
  agent_prompt?: string;
  capabilities?: string[];
  chat_capabilities?: string[];
  agent_preflight?: string[];
  allowed_surfaces?: Array<'chat' | 'agent'>;
  agent_allowed_tools?: string[];
}): Promise<Role> {
  const res = await authFetch(`${getBaseUrl()}/settings/roles`, {
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
    agent_prompt: string;
    capabilities: string[];
    chat_capabilities: string[];
    agent_preflight: string[];
    allowed_surfaces: Array<'chat' | 'agent'>;
    agent_allowed_tools: string[];
    sort_order: number;
  }>
): Promise<Role> {
  const res = await authFetch(`${getBaseUrl()}/settings/roles/${roleId}`, {
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
  const res = await authFetch(`${getBaseUrl()}/settings/roles/${roleId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '删除角色失败');
  }
}

// ===== 认证 & 用户管理 =====

export async function login(username: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${getBaseUrl()}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '登录失败');
  }
  return res.json();
}

export async function getMe(): Promise<User> {
  const res = await authFetch(`${getBaseUrl()}/auth/me`);
  if (!res.ok) throw new Error('获取用户信息失败');
  return res.json();
}

export async function registerUser(data: {
  username: string; display_name: string; password: string;
  system_role?: string; group_id?: string; can_manage_group_knowhow?: boolean;
}): Promise<User> {
  const res = await authFetch(`${getBaseUrl()}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '注册用户失败');
  }
  return res.json();
}

export async function listUsers(): Promise<User[]> {
  const res = await authFetch(`${getBaseUrl()}/auth/users`);
  if (!res.ok) throw new Error('获取用户列表失败');
  return res.json();
}

export async function updateUser(userId: string, data: Record<string, unknown>): Promise<User> {
  const res = await authFetch(`${getBaseUrl()}/auth/users/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '更新用户失败');
  }
  return res.json();
}

export async function deleteUser(userId: string): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/auth/users/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '删除用户失败');
  }
}

export async function listGroups(): Promise<Group[]> {
  const res = await authFetch(`${getBaseUrl()}/auth/groups`);
  if (!res.ok) throw new Error('获取用户组列表失败');
  return res.json();
}

export async function createGroup(name: string, description = ''): Promise<Group> {
  const res = await authFetch(`${getBaseUrl()}/auth/groups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '创建用户组失败');
  }
  return res.json();
}

export async function updateGroup(
  groupId: string,
  data: Partial<Pick<Group, 'name' | 'description'>>
): Promise<Group> {
  const res = await authFetch(`${getBaseUrl()}/auth/groups/${encodeURIComponent(groupId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '更新用户组失败');
  }
  return res.json();
}

export async function deleteGroup(groupId: string): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/auth/groups/${encodeURIComponent(groupId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '删除用户组失败');
  }
}

export async function listGrants(resourceType?: string, resourceId?: string): Promise<AccessGrant[]> {
  const params = new URLSearchParams();
  if (resourceType) params.set('resource_type', resourceType);
  if (resourceId) params.set('resource_id', resourceId);
  const query = params.toString();
  const res = await authFetch(`${getBaseUrl()}/auth/grants${query ? `?${query}` : ''}`);
  if (!res.ok) throw new Error('获取授权列表失败');
  return res.json();
}

export async function setGrant(data: {
  resource_type: string; resource_id: string;
  grant_type: string; grantee_id?: string;
}): Promise<AccessGrant> {
  const res = await authFetch(`${getBaseUrl()}/auth/grants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '设置授权失败');
  }
  return res.json();
}

export async function removeGrant(grantId: string): Promise<void> {
  const res = await authFetch(`${getBaseUrl()}/auth/grants/${encodeURIComponent(grantId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || '删除授权失败');
  }
}
