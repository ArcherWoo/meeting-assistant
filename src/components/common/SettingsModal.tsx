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
  testLLMConnection,
  getEmbeddingConfig, updateEmbeddingConfig, testEmbeddingConnection,
  createRole, updateRole, deleteRole, listRoles,
} from '@/services/api';
import type { LLMConnectionTestResult, LLMProfile, Role } from '@/types';
import PromptManager from './PromptManager';

type SettingsTab = 'models' | 'prompts' | 'roles' | 'appearance';

/** 主题色预设 */
const ACCENT_COLORS = [
  { label: '默认蓝', value: '#2563EB' },
  { label: '靛紫', value: '#7C3AED' },
  { label: '翠绿', value: '#059669' },
  { label: '玫红', value: '#DB2777' },
] as const;

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
    theme,
    setTheme,
    accentColor,
    setAccentColor,
    roles,
    setRoles,
    currentRoleId,
    setCurrentRoleId,
  } = useAppStore();
  const activeProfile = useMemo(
    () => llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0],
    [activeLLMConfigId, llmConfigs]
  );
  const [activeTab, setActiveTab] = useState<SettingsTab>('models');
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

  // Roles tab state
  const [selectedRoleId, setSelectedRoleId] = useState<string>('');
  const [roleDraft, setRoleDraft] = useState<Partial<Role>>({});
  const [roleIsNew, setRoleIsNew] = useState(false);
  const [roleSaving, setRoleSaving] = useState(false);
  const [roleSaved, setRoleSaved] = useState(false);
  const [roleError, setRoleError] = useState('');

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
      loadEmbeddingConfig();
    }
  }, [settingsOpen, loadEmbeddingConfig]);

  // Auto-select first role when switching to roles tab
  useEffect(() => {
    if (activeTab === 'roles' && !roleIsNew && roles.length > 0) {
      const found = roles.find((r) => r.id === selectedRoleId);
      if (!found) {
        setSelectedRoleId(roles[0].id);
        setRoleDraft({ ...roles[0] });
      }
    }
  }, [activeTab, roles, selectedRoleId, roleIsNew]);

  const handleSelectRole = (role: Role) => {
    setSelectedRoleId(role.id);
    setRoleDraft({ ...role });
    setRoleIsNew(false);
    setRoleSaved(false);
    setRoleError('');
  };

  const handleNewRole = () => {
    setSelectedRoleId('__new__');
    setRoleDraft({ name: '', icon: '🤖', description: '', system_prompt: '', capabilities: [] });
    setRoleIsNew(true);
    setRoleSaved(false);
    setRoleError('');
  };

  const handleSaveRole = async () => {
    if (!roleDraft.name?.trim()) {
      setRoleError('角色名称不能为空');
      return;
    }
    setRoleSaving(true);
    setRoleError('');
    try {
      let savedRole: Role;
      if (roleIsNew) {
        savedRole = await createRole({
          name: roleDraft.name.trim(),
          icon: roleDraft.icon || '🤖',
          description: roleDraft.description || '',
          system_prompt: roleDraft.system_prompt || '',
          capabilities: roleDraft.capabilities || [],
        });
      } else {
        savedRole = await updateRole(selectedRoleId, {
          name: roleDraft.name.trim(),
          icon: roleDraft.icon,
          description: roleDraft.description,
          system_prompt: roleDraft.system_prompt,
          capabilities: roleDraft.capabilities,
        });
      }
      const updatedRoles = await listRoles();
      setRoles(updatedRoles);
      setSelectedRoleId(savedRole.id);
      setRoleDraft({ ...savedRole });
      setRoleIsNew(false);
      setRoleSaved(true);
      setTimeout(() => setRoleSaved(false), 2000);
    } catch (e) {
      setRoleError((e as Error).message || '保存失败');
    } finally {
      setRoleSaving(false);
    }
  };

  const handleDeleteRole = async () => {
    if (roleIsNew) {
      if (roles.length > 0) handleSelectRole(roles[0]);
      return;
    }
    setRoleSaving(true);
    setRoleError('');
    try {
      await deleteRole(selectedRoleId);
      const updatedRoles = await listRoles();
      setRoles(updatedRoles);
      if (currentRoleId === selectedRoleId && updatedRoles.length > 0) {
        setCurrentRoleId(updatedRoles[0].id);
      }
      if (updatedRoles.length > 0) {
        setSelectedRoleId(updatedRoles[0].id);
        setRoleDraft({ ...updatedRoles[0] });
        setRoleIsNew(false);
      } else {
        setSelectedRoleId('');
        setRoleDraft({});
      }
    } catch (e) {
      setRoleError((e as Error).message || '删除失败');
    } finally {
      setRoleSaving(false);
    }
  };

  const toggleCapability = (cap: string) => {
    const caps = roleDraft.capabilities ?? [];
    setRoleDraft((d) => ({
      ...d,
      capabilities: caps.includes(cap) ? caps.filter((c) => c !== cap) : [...caps, cap],
    }));
    setRoleSaved(false);
  };

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
    setRoleIsNew(false);
    setRoleSaved(false);
    setRoleError('');
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
                onClick={() => setActiveTab('models')}
                className={clsx(
                  tabBtnCls,
                  activeTab === 'models'
                    ? tabBtnActiveCls
                    : tabBtnIdleCls
                )}
              >
                🧩 模型管理
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
                onClick={() => setActiveTab('roles')}
                className={clsx(
                  tabBtnCls,
                  activeTab === 'roles'
                    ? tabBtnActiveCls
                    : tabBtnIdleCls
                )}
              >
                🎭 角色管理
              </button>
              <button
                onClick={() => setActiveTab('appearance')}
                className={clsx(
                  tabBtnCls,
                  activeTab === 'appearance'
                    ? tabBtnActiveCls
                    : tabBtnIdleCls
                )}
              >
                🎨 外观
              </button>
            </div>
          </div>
          <button onClick={handleClose} className="win-icon-button h-8 w-8 text-lg leading-none">
            ×
          </button>
        </div>

        {/* 外观 Tab */}
        {activeTab === 'appearance' && (
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5 bg-[#F7F8FA] dark:bg-dark">
            <div className="win-panel space-y-4 p-4">
              <SectionTitle>主题模式</SectionTitle>
              <div className="flex gap-2">
                {([
                  { value: 'light', label: '☀️ 浅色' },
                  { value: 'dark',  label: '🌙 深色' },
                  { value: 'system', label: '💻 跟随系统' },
                ] as const).map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setTheme(opt.value)}
                    className={clsx(
                      'flex-1 rounded-lg border px-3 py-2 text-sm transition-colors',
                      theme === opt.value
                        ? 'border-primary/40 bg-white font-medium text-primary shadow-sm dark:bg-dark-card'
                        : 'border-surface-divider bg-white text-text-secondary hover:border-primary/20 hover:text-text-primary dark:border-dark-divider dark:bg-dark-card dark:hover:border-primary/20'
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="win-panel space-y-4 p-4">
              <SectionTitle>主题色</SectionTitle>
              <div className="flex gap-3 flex-wrap">
                {ACCENT_COLORS.map((color) => (
                  <button
                    key={color.value}
                    onClick={() => setAccentColor(color.value)}
                    title={color.label}
                    className={clsx(
                      'flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors',
                      accentColor === color.value
                        ? 'border-primary/40 bg-white shadow-sm dark:bg-dark-card font-medium'
                        : 'border-surface-divider bg-white text-text-secondary hover:border-gray-300 dark:border-dark-divider dark:bg-dark-card'
                    )}
                  >
                    <span
                      className="inline-block h-4 w-4 rounded-full border border-black/10 flex-shrink-0"
                      style={{ backgroundColor: color.value }}
                    />
                    <span>{color.label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* System Prompts Tab — 保持常驻挂载，避免切换 Tab 时重新 fetch */}
        <div className={clsx('flex-1 overflow-y-auto px-4 py-4 space-y-5 bg-[#F7F8FA] dark:bg-dark', activeTab !== 'prompts' && 'hidden')}>
          <PromptManager />
        </div>

        {/* 角色管理 Tab */}
        {activeTab === 'roles' && (
          <div className="flex flex-col flex-1 min-h-0">
            <div className="flex flex-1 min-h-0 border-b border-surface-divider dark:border-dark-divider">
              {/* 左侧：角色列表 */}
              <div className="w-[200px] flex-shrink-0 border-r border-surface-divider dark:border-dark-divider bg-[#F7F8FA] p-4 space-y-3 overflow-y-auto dark:bg-dark">
                <div className="flex items-center justify-between gap-2">
                  <SectionTitle>角色列表</SectionTitle>
                  <button onClick={handleNewRole} className="win-button-primary h-7 px-2.5 text-xs">
                    + 新增
                  </button>
                </div>
                <div className="space-y-1">
                  {roles.map((role) => (
                    <button
                      key={role.id}
                      onClick={() => handleSelectRole(role)}
                      className={clsx(
                        'w-full text-left rounded-lg border p-2.5 text-sm transition-colors',
                        selectedRoleId === role.id && !roleIsNew
                          ? 'border-primary/30 bg-white dark:bg-dark-card'
                          : 'border-surface-divider bg-white hover:border-primary/20 dark:border-dark-divider dark:bg-dark-card dark:hover:border-primary/20'
                      )}
                    >
                      <div className="flex items-center justify-between gap-1 min-w-0">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="flex-shrink-0">{role.icon}</span>
                          <span className="truncate text-xs font-medium">{role.name}</span>
                        </div>
                        {role.is_builtin && (
                          <span className="win-badge flex-shrink-0 text-[9px] border-blue-200 bg-blue-50 text-blue-600 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-400">
                            内置
                          </span>
                        )}
                      </div>
                    </button>
                  ))}
                  {roleIsNew && (
                    <button
                      className="w-full text-left rounded-lg border border-primary/30 bg-white p-2.5 text-sm dark:bg-dark-card"
                    >
                      <div className="flex items-center justify-between gap-1 min-w-0">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span>{roleDraft.icon || '🤖'}</span>
                          <span className="truncate text-xs font-medium">{roleDraft.name || '新角色'}</span>
                        </div>
                        <span className="win-badge flex-shrink-0 text-[9px] border-amber-200 bg-amber-50 text-amber-600 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-400">
                          未保存
                        </span>
                      </div>
                    </button>
                  )}
                </div>
              </div>

              {/* 右侧：角色编辑表单 */}
              <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 bg-[#F7F8FA] dark:bg-dark">
                {(selectedRoleId || roleIsNew) ? (
                  <>
                    <SectionTitle>{roleIsNew ? '新建角色' : '编辑角色'}</SectionTitle>
                    <div className="grid grid-cols-[1fr_120px] gap-3">
                      <Field label="角色名称">
                        <input
                          type="text"
                          value={roleDraft.name ?? ''}
                          onChange={(e) => { setRoleDraft((d) => ({ ...d, name: e.target.value })); setRoleSaved(false); }}
                          placeholder="例如：客服助手"
                          className={inputCls}
                        />
                      </Field>
                      <Field label="图标（Emoji）">
                        <input
                          type="text"
                          value={roleDraft.icon ?? ''}
                          onChange={(e) => { setRoleDraft((d) => ({ ...d, icon: e.target.value })); setRoleSaved(false); }}
                          placeholder="🤖"
                          className={inputCls}
                        />
                      </Field>
                    </div>
                    <Field label="描述">
                      <input
                        type="text"
                        value={roleDraft.description ?? ''}
                        onChange={(e) => { setRoleDraft((d) => ({ ...d, description: e.target.value })); setRoleSaved(false); }}
                        placeholder="简短描述此角色的用途"
                        className={inputCls}
                      />
                    </Field>
                    <Field label="System Prompt">
                      <textarea
                        value={roleDraft.system_prompt ?? ''}
                        onChange={(e) => { setRoleDraft((d) => ({ ...d, system_prompt: e.target.value })); setRoleSaved(false); }}
                        placeholder="输入此角色的系统提示词..."
                        rows={8}
                        className="win-input w-full resize-none"
                      />
                    </Field>
                    <Field label="能力">
                      <div className="flex gap-4">
                        {[
                          { key: 'rag', label: '📚 RAG 知识检索' },
                          { key: 'skills', label: '🔧 技能匹配' },
                        ].map(({ key, label }) => (
                          <label key={key} className="flex items-center gap-2 cursor-pointer text-sm">
                            <input
                              type="checkbox"
                              checked={(roleDraft.capabilities ?? []).includes(key)}
                              onChange={() => toggleCapability(key)}
                              className="w-4 h-4 accent-primary"
                            />
                            <span>{label}</span>
                          </label>
                        ))}
                      </div>
                    </Field>
                    {roleError && (
                      <p className="text-xs text-red-500 bg-red-50 dark:bg-red-900/20 rounded-md px-3 py-2">
                        {roleError}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-text-secondary mt-8 text-center">从左侧选择一个角色进行编辑，或点击"新增"创建新角色</p>
                )}
              </div>
            </div>

            {/* 底部操作栏 */}
            <div className="win-toolbar flex items-center justify-between gap-3 px-4 py-3">
              <button
                onClick={handleDeleteRole}
                disabled={!!(roleSaving || (!roleIsNew && (!selectedRoleId || (roles.find((r) => r.id === selectedRoleId)?.is_builtin ?? true))))}
                className="win-button-subtle h-8 px-3 text-sm text-red-500 hover:text-red-600 disabled:opacity-40"
              >
                {roleIsNew ? '放弃新增' : '删除角色'}
              </button>
              <div className="flex items-center gap-3">
                <button onClick={handleClose} className="win-button h-8 px-4 text-sm">取消</button>
                <button
                  onClick={handleSaveRole}
                  disabled={roleSaving || (!roleIsNew && !selectedRoleId)}
                  className="win-button-primary h-8 min-w-[84px] px-4 text-sm"
                >
                  {roleSaving ? '保存中...' : roleSaved ? '✅ 已保存' : '保存'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 模型管理 Tab */}
        {activeTab === 'models' && <div className="flex flex-col flex-1 min-h-0">
          {/* LLM 配置区 */}
          <div className="flex flex-1 min-h-0 border-b border-surface-divider dark:border-dark-divider">
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
          </div>
          {/* Embedding API 配置区 */}
          <div className="flex-shrink-0 max-h-[220px] overflow-y-auto px-4 py-3 space-y-3 bg-[#F7F8FA] dark:bg-dark">
            <SectionTitle>Embedding API 配置</SectionTitle>
            <Field label="API Base URL">
              <input
                value={embCfg.api_url}
                onChange={(e) => setEmbCfg((c) => ({ ...c, api_url: e.target.value }))}
                placeholder="https://api.openai.com/v1"
                className={inputCls}
              />
            </Field>
            <Field label="API Key">
              <input
                type="password"
                value={embCfg.api_key}
                onChange={(e) => setEmbCfg((c) => ({ ...c, api_key: e.target.value }))}
                placeholder="sk-..."
                className={inputCls}
              />
            </Field>
            <Field label="Embedding 模型">
              <input
                value={embCfg.model}
                onChange={(e) => setEmbCfg((c) => ({ ...c, model: e.target.value }))}
                placeholder="text-embedding-3-small"
                className={inputCls}
              />
            </Field>
            {embTestResult && (
              <p className={clsx('text-xs', embTestResult.success ? 'text-green-600' : 'text-red-500')}>
                {embTestResult.message}
              </p>
            )}
            {embError && <p className="text-xs text-red-500">{embError}</p>}
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={async () => {
                  setEmbTesting(true); setEmbError(''); setEmbTestResult(null);
                  try { const r = await testEmbeddingConnection(embCfg); setEmbTestResult(r); }
                  catch (e: any) { setEmbError((e as Error).message || '测试失败'); }
                  finally { setEmbTesting(false); }
                }}
                disabled={embTesting}
                className="win-button h-8 px-3 text-xs"
              >
                {embTesting ? '测试中...' : '测试连接'}
              </button>
              <button
                onClick={async () => {
                  setEmbSaving(true); setEmbError(''); setEmbSaved(false);
                  try { await updateEmbeddingConfig(embCfg); setEmbSaved(true); setTimeout(() => setEmbSaved(false), 2000); }
                  catch (e: any) { setEmbError((e as Error).message || '保存失败'); }
                  finally { setEmbSaving(false); }
                }}
                disabled={embSaving}
                className="win-button-primary h-8 px-3 text-xs"
              >
                {embSaving ? '保存中...' : embSaved ? '✅ 已保存' : '保存配置'}
              </button>
            </div>
          </div>
        </div>}

        {/* 底部操作区 — 模型管理 Tab 专属 */}
        {activeTab === 'models' && (
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
