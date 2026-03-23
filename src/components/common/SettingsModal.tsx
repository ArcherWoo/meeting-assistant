/**
 * 设置面板 Modal
 * 配置多组 LLM 连接参数，并选择当前使用的模型
 * 支持 System Prompt 自定义（Copilot / Agent / Knowledge 模式）
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import clsx from 'clsx';
import { useAppStore } from '@/stores/appStore';
import {
  testLLMConnection, getSystemPrompt, updateSystemPrompt, resetSystemPrompt,
  getEmbeddingConfig, updateEmbeddingConfig, resetEmbeddingConfig, testEmbeddingConnection,
} from '@/services/api';
import type { LLMConnectionTestResult, LLMProfile } from '@/types';

type SettingsTab = 'llm' | 'prompts' | 'embedding';

/** 三种对话模式的 System Prompt 状态 */
interface PromptState {
  value: string;
  isCustom: boolean;
  saving: boolean;
  saved: boolean;
  error: string;
}

function createDraftProfile(index: number): LLMProfile {
  return {
    id: uuidv4(),
    name: `模型 ${index}`,
    apiUrl: 'https://api.openai.com/v1',
    apiKey: '',
    model: 'gpt-4o',
    temperature: 0.7,
    maxTokens: 4096,
    stream: true,
  };
}

// 模式列表与前端 AppMode 保持一致：copilot / builder / agent
// placeholder 为各模式内置默认 System Prompt（后端无自定义时使用的值）
const PROMPT_MODES = [
  {
    key: 'copilot',
    label: 'Copilot 模式',
    icon: '💬',
    placeholder:
      '你是一个专业的会议助手。请根据用户的问题，提供清晰、准确、有帮助的回答。' +
      '回答时请保持简洁，优先给出结论，再补充细节。',
  },
  {
    key: 'builder',
    label: 'Skill Builder 模式',
    icon: '🔧',
    placeholder:
      '你是一个 Skill Builder 助手，专门帮助用户创建和优化工作流技能（Skill）。' +
      '请引导用户描述他们的工作场景和重复性任务，帮助他们将这些任务抽象为可执行的 Skill 模板。' +
      '生成的 Skill 应使用标准 Markdown 格式，包含描述、触发条件、执行步骤和输出格式。',
  },
  {
    key: 'agent',
    label: 'Agent 模式',
    icon: '🤖',
    placeholder:
      '你是一个智能 Agent，能够调用各种工具和技能完成复杂任务。' +
      '请分析用户的需求，选择合适的工具，并逐步执行任务。' +
      '执行过程中保持透明，让用户了解每一步的进展。',
  },
] as const;

const defaultPromptState = (): PromptState => ({ value: '', isCustom: false, saving: false, saved: false, error: '' });

export default function SettingsModal() {
  const {
    settingsOpen,
    toggleSettings,
    llmConfigs,
    activeLLMConfigId,
    setActiveLLMConfig,
    saveLLMConfig,
    removeLLMConfig,
  } = useAppStore();
  const activeProfile = useMemo(
    () => llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0],
    [activeLLMConfigId, llmConfigs]
  );
  const [activeTab, setActiveTab] = useState<SettingsTab>('llm');
  const [selectedId, setSelectedId] = useState(activeProfile?.id ?? '');
  const [draft, setDraft] = useState<LLMProfile>(activeProfile ?? createDraftProfile(1));
  const [isNewDraft, setIsNewDraft] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionResult, setConnectionResult] = useState<LLMConnectionTestResult | null>(null);
  const [connectionError, setConnectionError] = useState('');
  const cachedModels = useMemo(
    () => Array.from(new Set([...(draft.availableModels ?? []), ...(connectionResult?.available_models ?? [])])),
    [connectionResult?.available_models, draft.availableModels]
  );

  // System Prompt 状态（键与前端 AppMode 保持一致：copilot / builder / agent）
  const [prompts, setPrompts] = useState<Record<string, PromptState>>({
    copilot: defaultPromptState(),
    builder: defaultPromptState(),
    agent: defaultPromptState(),
  });

  // Embedding 配置状态
  const [embCfg, setEmbCfg] = useState({ api_url: '', api_key: '', model: 'text-embedding-3-small' });
  const [embSaving, setEmbSaving] = useState(false);
  const [embSaved, setEmbSaved] = useState(false);
  const [embTesting, setEmbTesting] = useState(false);
  const [embTestResult, setEmbTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [embError, setEmbError] = useState('');

  const updateDraft = (updates: Partial<LLMProfile>, options?: { preserveTestFeedback?: boolean }) => {
    setDraft((current) => ({ ...current, ...updates }));
    setSaved(false);
    if (!options?.preserveTestFeedback) {
      setConnectionResult(null);
      setConnectionError('');
    }
  };

  /** 加载所有 System Prompt */
  const loadPrompts = useCallback(async () => {
    const results = await Promise.allSettled(
      PROMPT_MODES.map((m) => getSystemPrompt(m.key))
    );
    const next: Record<string, PromptState> = {};
    PROMPT_MODES.forEach((m, i) => {
      const r = results[i];
      if (r.status === 'fulfilled') {
        next[m.key] = { value: r.value.prompt, isCustom: r.value.is_custom, saving: false, saved: false, error: '' };
      } else {
        next[m.key] = defaultPromptState();
      }
    });
    setPrompts(next);
  }, []);

  useEffect(() => {
    if (!settingsOpen || !activeProfile) return;
    setSelectedId(activeProfile.id);
    setDraft({ ...activeProfile });
    setIsNewDraft(false);
    setSaved(false);
    setTestingConnection(false);
    setConnectionResult(null);
    setConnectionError('');
  }, [activeProfile, settingsOpen]);

  const loadEmbeddingConfig = useCallback(async () => {
    try {
      const cfg = await getEmbeddingConfig();
      setEmbCfg({ api_url: cfg.api_url, api_key: cfg.api_key, model: cfg.model || 'text-embedding-3-small' });
    } catch {
      // 静默失败，保留表单默认值
    }
  }, []);

  useEffect(() => {
    if (settingsOpen) {
      loadPrompts();
      loadEmbeddingConfig();
    }
  }, [settingsOpen, loadPrompts, loadEmbeddingConfig]);

  if (!settingsOpen) return null;

  const draftExistsInStore = llmConfigs.some((config) => config.id === draft.id);
  const profileList = isNewDraft && !draftExistsInStore ? [...llmConfigs, draft] : llmConfigs;

  const handleSelectProfile = (profile: LLMProfile) => {
    setSelectedId(profile.id);
    setDraft({ ...profile });
    setIsNewDraft(false);
    setSaved(false);
    setConnectionResult(null);
    setConnectionError('');
  };

  const handleAddProfile = () => {
    const nextProfile = createDraftProfile(llmConfigs.length + 1);
    setSelectedId(nextProfile.id);
    setDraft(nextProfile);
    setIsNewDraft(true);
    setSaved(false);
    setConnectionResult(null);
    setConnectionError('');
  };

  const handleSave = () => {
    const nextDraft = {
      ...draft,
      name: draft.name.trim() || `模型 ${llmConfigs.length + (isNewDraft ? 1 : 0)}`,
    };

    saveLLMConfig(nextDraft);
    setDraft(nextDraft);
    setSelectedId(nextDraft.id);
    setIsNewDraft(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleDelete = () => {
    if (isNewDraft) {
      if (activeProfile) {
        handleSelectProfile(activeProfile);
      }
      return;
    }

    if (llmConfigs.length <= 1) return;

    const fallbackProfile = llmConfigs.find((config) => config.id !== draft.id);
    removeLLMConfig(draft.id);

    if (fallbackProfile) {
      setSelectedId(fallbackProfile.id);
      setDraft({ ...fallbackProfile });
      setIsNewDraft(false);
      setConnectionResult(null);
      setConnectionError('');
    }
  };

  const handleTestConnection = async () => {
    if (!draft.apiUrl.trim() || !draft.apiKey.trim()) {
      setConnectionResult(null);
      setConnectionError('请先填写 API Base URL 和 API Key');
      return;
    }

    setTestingConnection(true);
    setConnectionError('');
    setConnectionResult(null);

    try {
      const result = await testLLMConnection(draft.apiUrl.trim(), draft.apiKey.trim(), draft.model.trim());
      const nextDraft: LLMProfile = {
        ...draft,
        model: draft.model.trim() || result.model,
        availableModels: result.available_models,
      };

      setDraft(nextDraft);
      setConnectionResult(result);
      if (!isNewDraft && draftExistsInStore) {
        saveLLMConfig(nextDraft);
      }
    } catch (error) {
      setConnectionError((error as Error).message || '连接测试失败');
    } finally {
      setTestingConnection(false);
    }
  };

  /** 保存指定模式的 System Prompt */
  const handleSavePrompt = async (mode: string) => {
    setPrompts((p) => ({ ...p, [mode]: { ...p[mode], saving: true, error: '', saved: false } }));
    try {
      const result = await updateSystemPrompt(mode, prompts[mode].value);
      setPrompts((p) => ({ ...p, [mode]: { ...p[mode], saving: false, saved: true, isCustom: true, value: result.prompt } }));
      setTimeout(() => setPrompts((p) => ({ ...p, [mode]: { ...p[mode], saved: false } })), 2000);
    } catch (err: any) {
      setPrompts((p) => ({ ...p, [mode]: { ...p[mode], saving: false, error: err.message || '保存失败' } }));
    }
  };

  /** 重置指定模式的 System Prompt 为默认值 */
  const handleResetPrompt = async (mode: string) => {
    if (!confirm('确定要重置为默认 System Prompt 吗？')) return;
    setPrompts((p) => ({ ...p, [mode]: { ...p[mode], saving: true, error: '', saved: false } }));
    try {
      const result = await resetSystemPrompt(mode);
      setPrompts((p) => ({ ...p, [mode]: { ...p[mode], saving: false, saved: true, isCustom: false, value: result.prompt } }));
      setTimeout(() => setPrompts((p) => ({ ...p, [mode]: { ...p[mode], saved: false } })), 2000);
    } catch (err: any) {
      setPrompts((p) => ({ ...p, [mode]: { ...p[mode], saving: false, error: err.message || '重置失败' } }));
    }
  };

  const handleClose = () => {
    if (activeProfile) {
      setSelectedId(activeProfile.id);
      setDraft({ ...activeProfile });
    }
    setIsNewDraft(false);
    setSaved(false);
    setTestingConnection(false);
    setConnectionResult(null);
    setConnectionError('');
    toggleSettings();
  };

  return (
    // 遮罩层
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
    >
      <div className="win-modal flex max-h-[90vh] w-[920px] max-w-[96vw] flex-col overflow-hidden">
        {/* 标题栏 */}
        <div className="win-toolbar flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <span>⚙️</span> 设置
            </h2>
            {/* Tab 切换 */}
            <div className="flex items-center gap-1 rounded-lg border border-surface-divider bg-surface p-1 dark:border-dark-divider dark:bg-dark-sidebar">
              <button
                onClick={() => setActiveTab('llm')}
                className={clsx(
                  tabBtnCls,
                  activeTab === 'llm'
                    ? tabBtnActiveCls
                    : tabBtnIdleCls
                )}
              >
                🧠 模型配置
              </button>
              <button
                onClick={() => setActiveTab('prompts')}
                className={clsx(
                  tabBtnCls,
                  activeTab === 'prompts'
                    ? tabBtnActiveCls
                    : tabBtnIdleCls
                )}
              >
                📝 System Prompts
              </button>
              <button
                onClick={() => setActiveTab('embedding')}
                className={clsx(
                  tabBtnCls,
                  activeTab === 'embedding'
                    ? tabBtnActiveCls
                    : tabBtnIdleCls
                )}
              >
                🔍 Embedding
              </button>
            </div>
          </div>
          <button onClick={handleClose} className="win-icon-button h-8 w-8 text-lg leading-none">
            ×
          </button>
        </div>

        {/* System Prompts Tab */}
        {activeTab === 'prompts' && (
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5 bg-[#F7F8FA] dark:bg-dark">
            <p className="text-xs text-text-secondary">
              为每种对话模式配置专属的 System Prompt。留空则使用内置默认提示词。
            </p>
            {PROMPT_MODES.map(({ key, label, icon, placeholder }) => {
              const ps = prompts[key];
              return (
                <div key={key} className="win-panel space-y-3 p-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span>{icon}</span>
                      <span className="text-sm font-medium">{label}</span>
                      {ps.isCustom && (
                        <span className="win-badge border-primary/20 bg-primary/10 text-[10px] text-primary">已自定义</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {ps.isCustom && (
                        <button
                          onClick={() => handleResetPrompt(key)}
                          disabled={ps.saving}
                          className="win-button-subtle h-8 px-2 text-xs disabled:opacity-50"
                        >
                          重置默认
                        </button>
                      )}
                      <button
                        onClick={() => handleSavePrompt(key)}
                        disabled={ps.saving}
                        className="win-button-primary h-8 min-w-[72px] px-3 text-xs"
                      >
                        {ps.saving ? '保存中...' : ps.saved ? '✅ 已保存' : '保存'}
                      </button>
                    </div>
                  </div>
                  <textarea
                    value={ps.value}
                    onChange={(e) => setPrompts((p) => ({ ...p, [key]: { ...p[key], value: e.target.value } }))}
                    rows={5}
                    placeholder={placeholder}
                    className="win-input resize-y text-sm leading-6"
                  />
                  {ps.error && <p className="text-xs text-red-500">{ps.error}</p>}
                </div>
              );
            })}
          </div>
        )}

        {/* Embedding 配置 Tab */}
        {activeTab === 'embedding' && (
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5 bg-[#F7F8FA] dark:bg-dark">
            <p className="text-xs text-text-secondary">
              配置独立的 Embedding API，用于知识库语义检索。留空则自动使用当前 LLM 的 API 凭证（部分 LLM 提供商可能不支持 /embeddings 接口）。
            </p>

            <div className="win-panel space-y-4 p-4">
              <SectionTitle>Embedding API 配置</SectionTitle>

              <Field label="API Base URL">
                <input
                  className={inputCls}
                  placeholder="https://api.openai.com/v1"
                  value={embCfg.api_url}
                  onChange={(e) => { setEmbCfg((c) => ({ ...c, api_url: e.target.value })); setEmbTestResult(null); setEmbError(''); }}
                />
              </Field>

              <Field label="API Key">
                <input
                  type="password"
                  className={inputCls}
                  placeholder="sk-..."
                  value={embCfg.api_key}
                  onChange={(e) => { setEmbCfg((c) => ({ ...c, api_key: e.target.value })); setEmbTestResult(null); setEmbError(''); }}
                />
              </Field>

              <Field label="Embedding 模型">
                <input
                  className={inputCls}
                  placeholder="text-embedding-3-small"
                  value={embCfg.model}
                  onChange={(e) => { setEmbCfg((c) => ({ ...c, model: e.target.value })); setEmbTestResult(null); setEmbError(''); }}
                />
              </Field>

              {embTestResult && (
                <p className={clsx('text-xs', embTestResult.success ? 'text-green-500' : 'text-red-500')}>
                  {embTestResult.success ? '✅' : '❌'} {embTestResult.message}
                </p>
              )}
              {embError && <p className="text-xs text-red-500">{embError}</p>}

              <div className="flex items-center justify-between gap-3 pt-1">
                <button
                  onClick={async () => {
                    if (!confirm('确定要清除独立 Embedding 配置吗？清除后将回退到使用 LLM API 凭证。')) return;
                    try {
                      await resetEmbeddingConfig();
                      setEmbCfg({ api_url: '', api_key: '', model: 'text-embedding-3-small' });
                      setEmbTestResult(null);
                      setEmbError('');
                    } catch (e: any) {
                      setEmbError(e.message || '清除失败');
                    }
                  }}
                  className="win-button-subtle h-8 px-2 text-xs"
                >
                  清除配置
                </button>

                <div className="flex items-center gap-2">
                  <button
                    disabled={embTesting || !embCfg.api_url || !embCfg.api_key}
                    onClick={async () => {
                      setEmbTesting(true); setEmbTestResult(null); setEmbError('');
                      try {
                        const result = await testEmbeddingConnection(embCfg);
                        setEmbTestResult(result);
                      } catch (e: any) {
                        setEmbError(e.message || '测试失败');
                      } finally {
                        setEmbTesting(false);
                      }
                    }}
                    className="win-button h-8 px-3 text-xs disabled:opacity-40"
                  >
                    {embTesting ? '测试中...' : '测试连接'}
                  </button>

                  <button
                    disabled={embSaving}
                    onClick={async () => {
                      setEmbSaving(true); setEmbError('');
                      try {
                        await updateEmbeddingConfig(embCfg);
                        setEmbSaved(true);
                        setTimeout(() => setEmbSaved(false), 2000);
                      } catch (e: any) {
                        setEmbError(e.message || '保存失败');
                      } finally {
                        setEmbSaving(false);
                      }
                    }}
                    className="win-button-primary h-8 min-w-[72px] px-4 text-xs"
                  >
                    {embSaving ? '保存中...' : embSaved ? '✅ 已保存' : '保存'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* LLM 配置 Tab */}
        {activeTab === 'llm' && <div className="flex flex-1 min-h-0">
          <div className="w-[260px] border-r border-surface-divider dark:border-dark-divider bg-[#F7F8FA] p-4 space-y-3 overflow-y-auto dark:bg-dark">
            <div className="flex items-center justify-between gap-2">
              <SectionTitle>模型列表</SectionTitle>
              <button
                onClick={handleAddProfile}
                className="win-button-primary h-8 px-3 text-xs"
              >
                + 新增
              </button>
            </div>

            <div className="space-y-2">
              {profileList.map((profile) => {
                const isSelected = selectedId === profile.id;
                const isActive = activeLLMConfigId === profile.id;
                const isUnsaved = isNewDraft && draft.id === profile.id && !draftExistsInStore;

                return (
                  <button
                    key={profile.id}
                    onClick={() => handleSelectProfile(profile)}
                    className={clsx(
                      'w-full text-left rounded-lg border p-3 shadow-sm transition-colors',
                      isSelected
                        ? 'border-primary/30 bg-white dark:bg-dark-card'
                        : 'border-surface-divider bg-white hover:border-primary/20 dark:border-dark-divider dark:bg-dark-card dark:hover:border-primary/20'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">{profile.name}</div>
                        <div className="text-xs text-text-secondary truncate mt-0.5">{profile.model}</div>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        {isActive && (
                          <span className="win-badge border-green-200 bg-green-50 text-[10px] text-green-600 dark:border-green-800 dark:bg-green-900/20 dark:text-green-400">
                            当前
                          </span>
                        )}
                        {isUnsaved && (
                          <span className="win-badge border-amber-200 bg-amber-50 text-[10px] text-amber-600 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-400">
                            未保存
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 bg-[#F7F8FA] dark:bg-dark">
            <div className="flex items-center justify-between gap-3">
              <SectionTitle>LLM 连接配置</SectionTitle>
              {!isNewDraft && draft.id !== activeLLMConfigId && (
                <button
                  onClick={() => setActiveLLMConfig(draft.id)}
                  className="win-button h-8 px-3 text-xs text-primary"
                >
                  设为当前使用
                </button>
              )}
            </div>

            <Field label="配置名称">
              <input
                type="text"
                value={draft.name}
                onChange={(e) => updateDraft({ name: e.target.value })}
                placeholder="例如：OpenAI GPT-4o / DeepSeek Chat"
                className={inputCls}
              />
            </Field>

            <Field label="API Base URL">
              <input
                type="text"
                value={draft.apiUrl}
                onChange={(e) => updateDraft({ apiUrl: e.target.value })}
                placeholder="https://api.openai.com/v1"
                className={inputCls}
              />
            </Field>

            <Field label="API Key">
              <input
                type="password"
                value={draft.apiKey}
                onChange={(e) => updateDraft({ apiKey: e.target.value })}
                placeholder="sk-..."
                className={inputCls}
              />
            </Field>

            <div className="win-panel-muted space-y-3 p-3">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div>
                  <p className="text-sm font-medium">连通性测试</p>
                  <p className="text-xs text-text-secondary mt-1">
                    输入 URL 和 API Key 后，测试接口并返回当前可用模型列表
                  </p>
                </div>
                <button
                  onClick={handleTestConnection}
                  disabled={testingConnection || !draft.apiUrl.trim() || !draft.apiKey.trim()}
                  className="win-button-primary h-8 px-3 text-xs"
                >
                  {testingConnection ? '测试中...' : '测试连通性'}
                </button>
              </div>

              {connectionError && (
                <div className="text-xs text-red-500 bg-red-50 dark:bg-red-900/20 rounded-md px-3 py-2">
                  {connectionError}
                </div>
              )}

              {connectionResult && (
                <div className="space-y-3">
                  <div className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 rounded-md px-3 py-2">
                    {connectionResult.message}
                    {connectionResult.fallback && '（当前服务未返回 /models 列表，已用填写的模型做兜底验证）'}
                    {isNewDraft && '（当前为新配置草稿，模型列表会在点击保存后持久化）'}
                  </div>

                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="text-text-secondary">当前填写模型：</span>
                    <span
                      className={clsx(
                        'win-badge px-2 py-1',
                        connectionResult.selected_model_available
                          ? 'border-green-200 text-green-600 dark:border-green-800 dark:text-green-400'
                          : 'border-amber-200 text-amber-600 dark:border-amber-800 dark:text-amber-400'
                      )}
                    >
                      {connectionResult.model || '未填写'}
                      {connectionResult.selected_model_available ? ' · 可用' : ' · 不在返回列表中'}
                    </span>
                  </div>

                  <div className="space-y-2">
                    <p className="text-xs text-text-secondary">
                      可用模型（点击可填入下方“模型”输入框）
                    </p>
                    <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto scrollbar-thin pr-1">
                      {connectionResult.available_models.map((modelName) => (
                        <button
                          key={modelName}
                          onClick={() => updateDraft({ model: modelName }, { preserveTestFeedback: true })}
                          className={clsx(
                            'win-chip px-2.5 py-1 text-xs',
                            draft.model === modelName
                              ? 'border-primary bg-primary/10 text-primary'
                              : 'hover:border-primary/40 hover:text-primary'
                          )}
                        >
                          {modelName}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>

            <Field label="模型 (Model)">
              <div className="space-y-2">
                <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_220px] gap-2">
                  <input
                    type="text"
                    list={`model-suggestions-${draft.id}`}
                    value={draft.model}
                    onChange={(e) => updateDraft({ model: e.target.value }, { preserveTestFeedback: true })}
                    placeholder="gpt-4o"
                    className={inputCls}
                  />

                  <select
                    value={cachedModels.includes(draft.model) ? draft.model : ''}
                    onChange={(e) => updateDraft({ model: e.target.value }, { preserveTestFeedback: true })}
                    disabled={cachedModels.length === 0}
                    className={clsx(
                      selectCls,
                      cachedModels.length === 0 && 'opacity-60 cursor-not-allowed'
                    )}
                  >
                    <option value="">{cachedModels.length === 0 ? '暂无缓存模型' : '从已缓存模型中选择'}</option>
                    {cachedModels.map((modelName) => (
                      <option key={modelName} value={modelName}>
                        {modelName}
                      </option>
                    ))}
                  </select>
                </div>

                <datalist id={`model-suggestions-${draft.id}`}>
                  {cachedModels.map((modelName) => (
                    <option key={modelName} value={modelName} />
                  ))}
                </datalist>

                <p className="text-xs text-text-secondary">
                  可直接输入自定义模型名；测试连通性后，也可从右侧下拉框或输入建议中快速选择
                </p>
              </div>
            </Field>

            <Field label={`Temperature: ${draft.temperature}`}>
              <input
                type="range"
                min={0} max={2} step={0.05}
                value={draft.temperature}
                onChange={(e) => updateDraft({ temperature: parseFloat(e.target.value) })}
                className="w-full accent-primary"
              />
            </Field>

            <Field label={`最大输出 Token: ${draft.maxTokens}`}>
              <input
                type="range"
                min={256} max={8192} step={256}
                value={draft.maxTokens}
                onChange={(e) => updateDraft({ maxTokens: parseInt(e.target.value, 10) })}
                className="w-full accent-primary"
              />
            </Field>

            <Field label="流式输出 (Stream)">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={draft.stream}
                  onChange={(e) => updateDraft({ stream: e.target.checked })}
                  className="w-4 h-4 accent-primary"
                />
                <span className="text-sm text-text-secondary">
                  {draft.stream ? '已启用' : '已禁用'}
                </span>
              </label>
            </Field>
          </div>
        </div>}

        {/* 底部操作区 — LLM Tab 专属 */}
        {activeTab === 'llm' && (
        <div className="win-toolbar flex items-center justify-between gap-3 px-4 py-3">
          <button
            onClick={handleDelete}
            disabled={!isNewDraft && llmConfigs.length <= 1}
            className="win-button-subtle h-8 px-3 text-sm text-red-500 hover:text-red-600 disabled:opacity-40"
          >
            {isNewDraft ? '放弃新增' : '删除当前配置'}
          </button>

          <div className="flex items-center gap-3">
          <button
            onClick={handleClose}
            className="win-button h-8 px-4 text-sm"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            className="win-button-primary h-8 min-w-[84px] px-4 text-sm"
          >
            {saved ? '✅ 已保存' : '保存'}
          </button>
          </div>
        </div>
        )}
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">{children}</h3>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium">{label}</label>
      {children}
    </div>
  );
}

const inputCls =
  'win-input';

const selectCls =
  'win-select';

const tabBtnCls =
  'rounded-md px-3 py-1.5 text-xs transition-colors';

const tabBtnActiveCls =
  'bg-white text-text-primary shadow-sm dark:bg-dark-card dark:text-text-dark-primary';

const tabBtnIdleCls =
  'text-text-secondary hover:bg-white hover:text-text-primary dark:hover:bg-dark-card dark:hover:text-text-dark-primary';

