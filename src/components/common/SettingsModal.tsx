/**
 * 设置面板 Modal
 * 配置多组 LLM 连接参数，并选择当前使用的模型
 */
import { useEffect, useMemo, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import clsx from 'clsx';
import { useAppStore } from '@/stores/appStore';
import { testLLMConnection } from '@/services/api';
import type { LLMConnectionTestResult, LLMProfile } from '@/types';

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

  const updateDraft = (updates: Partial<LLMProfile>, options?: { preserveTestFeedback?: boolean }) => {
    setDraft((current) => ({ ...current, ...updates }));
    setSaved(false);
    if (!options?.preserveTestFeedback) {
      setConnectionResult(null);
      setConnectionError('');
    }
  };

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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
    >
      <div className="w-[860px] max-w-[96vw] max-h-[90vh] overflow-hidden bg-white dark:bg-dark-card rounded-xl shadow-2xl flex flex-col">
        {/* 标题栏 */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-surface-divider dark:border-dark-divider">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <span>⚙️</span> 模型设置
          </h2>
          <button
            onClick={handleClose}
            className="text-text-secondary hover:text-text-primary dark:hover:text-text-dark-primary text-xl leading-none"
          >
            ×
          </button>
        </div>

        {/* 内容区 */}
        <div className="flex flex-1 min-h-0">
          <div className="w-[250px] border-r border-surface-divider dark:border-dark-divider p-4 space-y-3 overflow-y-auto">
            <div className="flex items-center justify-between gap-2">
              <SectionTitle>模型列表</SectionTitle>
              <button
                onClick={handleAddProfile}
                className="px-2 py-1 text-xs bg-primary text-white rounded-md hover:bg-primary-600 transition-colors"
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
                      'w-full text-left p-3 rounded-lg border transition-colors',
                      isSelected
                        ? 'border-primary bg-primary/5'
                        : 'border-surface-divider dark:border-dark-divider hover:bg-gray-50 dark:hover:bg-gray-800/60'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">{profile.name}</div>
                        <div className="text-xs text-text-secondary truncate mt-0.5">{profile.model}</div>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        {isActive && (
                          <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400">
                            当前
                          </span>
                        )}
                        {isUnsaved && (
                          <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400">
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

          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <div className="flex items-center justify-between gap-3">
              <SectionTitle>LLM 连接配置</SectionTitle>
              {!isNewDraft && draft.id !== activeLLMConfigId && (
                <button
                  onClick={() => setActiveLLMConfig(draft.id)}
                  className="px-3 py-1 text-xs rounded-md border border-primary/30 text-primary hover:bg-primary/5 transition-colors"
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

            <div className="rounded-lg border border-surface-divider dark:border-dark-divider p-3 space-y-3 bg-gray-50/60 dark:bg-gray-900/20">
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
                  className="px-3 py-1.5 text-xs rounded-md bg-primary text-white hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
                        'px-2 py-1 rounded-full border',
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
                            'px-2.5 py-1 text-xs rounded-full border transition-colors',
                            draft.model === modelName
                              ? 'border-primary bg-primary/10 text-primary'
                              : 'border-surface-divider dark:border-dark-divider hover:border-primary/40 hover:text-primary'
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
                      inputCls,
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
        </div>

        {/* 底部操作区 */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-t border-surface-divider dark:border-dark-divider">
          <button
            onClick={handleDelete}
            disabled={!isNewDraft && llmConfigs.length <= 1}
            className="px-4 py-1.5 text-sm text-red-500 hover:text-red-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isNewDraft ? '放弃新增' : '删除当前配置'}
          </button>

          <div className="flex items-center gap-3">
          <button
            onClick={handleClose}
            className="px-4 py-1.5 text-sm text-text-secondary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-1.5 bg-primary text-white text-sm rounded-button hover:bg-primary-600 transition-colors min-w-[72px]"
          >
            {saved ? '✅ 已保存' : '保存'}
          </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">{children}</h3>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="block text-sm font-medium">{label}</label>
      {children}
    </div>
  );
}

const inputCls =
  'w-full px-3 py-1.5 text-sm border border-surface-divider dark:border-dark-divider rounded-lg bg-surface-card dark:bg-dark-sidebar focus:outline-none focus:ring-2 focus:ring-primary/40';

