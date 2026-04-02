/**
 * 设置面板 Modal
 * 配置多组 LLM 连接参数，并选择当前使用的模型
 * 支持 System Prompt 自定义（Copilot / Agent / Knowledge 模式）
 */
import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import clsx from 'clsx';
import { useAppStore } from '@/stores/appStore';
import { useAuthStore } from '@/stores/authStore';
import { useConfirm } from '@/hooks/useConfirm';
import { emitAppDataInvalidation } from '@/utils/appInvalidation';
import { getPreferredRoleForSurface } from '@/utils/roles';
import {
  listLLMProfiles, createLLMProfile, updateLLMProfile, deleteLLMProfile, setActiveLLMProfile,
  testLLMConnection,
  getEmbeddingConfig, updateEmbeddingConfig, testEmbeddingConnection,
  createRole, updateRole, deleteRole, listRoles,
  listSystemPromptPresets, createSystemPromptPreset, deleteSystemPromptPreset,
  resetSystemPrompt,
} from '@/services/api';
import type { LLMConnectionTestResult, LLMProfile, Role, SystemPromptPreset } from '@/types';

type SettingsTab = 'models' | 'roles' | 'appearance';

/** 角色图标预设（8个，稳态表单布局） */
const ROLE_EMOJIS = [
  '💬', '🤖',
  '🔍', '🛠️',
  '🎯', '🎭',
  '🌐', '🚀',
];

/** 主题色预设 */
const ACCENT_COLORS = [
  { label: '默认蓝', value: '#2563EB' },
  { label: '靛紫', value: '#7C3AED' },
  { label: '翠绿', value: '#059669' },
  { label: '玫红', value: '#DB2777' },
] as const;

const CHAT_CAPABILITY_OPTIONS = [
  { key: 'rag', label: '自动知识检索', hint: '允许 Chat 在回答前自动检索知识库内容' },
  { key: 'skills', label: '自动 Skill 建议', hint: '允许 Chat 根据当前问题自动推荐合适的 Skill' },
];

void CHAT_CAPABILITY_OPTIONS;

const AGENT_TOOL_OPTIONS = [
  { key: 'get_skill_definition', label: '读取 Skill 定义', hint: '允许 Agent 在运行时读取某个 Skill 的详细定义' },
  { key: 'extract_file_text', label: '读取导入文件', hint: '允许 Agent 在运行时读取已导入文件的文本内容' },
  { key: 'query_knowledge', label: '主动查询知识库', hint: '允许 Agent 在运行时主动查询知识库内容' },
  { key: 'search_knowhow_rules', label: '主动查询规则库', hint: '允许 Agent 在运行时主动查询 Know-how 规则库' },
];

const CHAT_POLICY_OPTIONS = [
  { key: 'auto_knowledge', label: '自动知识检索', hint: '允许 Chat 在回答前自动检索知识库内容' },
  { key: 'auto_knowhow', label: '自动规则检索', hint: '允许 Chat 在回答前自动检索 Know-how 规则库' },
  { key: 'auto_skill_suggestion', label: '自动 Skill 建议', hint: '允许 Chat 根据当前问题自动推荐合适的 Skill' },
];

const AGENT_PREFLIGHT_OPTIONS = [
  { key: 'pre_match_skill', label: '预匹配 Skill', hint: '允许 Agent 在启动前先判断任务是否适合匹配现有 Skill' },
  { key: 'auto_knowledge', label: '执行前自动知识检索', hint: '允许 Agent 在执行前从知识库补充上下文' },
  { key: 'auto_knowhow', label: '执行前自动规则检索', hint: '允许 Agent 在执行前从 Know-how 规则库补充上下文' },
];

function createEmptyRoleDraft(): Partial<Role> {
  return {
    name: '',
    icon: '🤖',
    description: '',
    system_prompt: '',
    agent_prompt: '',
    capabilities: [],
    chat_capabilities: [],
    agent_preflight: [],
    allowed_surfaces: ['chat'],
    agent_allowed_tools: [],
  };
}

function normalizeRoleDraft(role?: Partial<Role> | null): Partial<Role> {
  const base = createEmptyRoleDraft();
  return {
    ...base,
    ...role,
    name: role?.name ?? base.name,
    icon: role?.icon || base.icon,
    description: role?.description ?? base.description,
    system_prompt: role?.system_prompt ?? base.system_prompt,
    agent_prompt: role?.agent_prompt ?? base.agent_prompt,
    capabilities: Array.isArray(role?.capabilities) ? role.capabilities : base.capabilities,
    chat_capabilities: Array.isArray(role?.chat_capabilities) ? role.chat_capabilities : base.chat_capabilities,
    agent_preflight: Array.isArray(role?.agent_preflight) ? role.agent_preflight : base.agent_preflight,
    allowed_surfaces: Array.isArray(role?.allowed_surfaces) && role.allowed_surfaces.length > 0 ? role.allowed_surfaces : base.allowed_surfaces,
    agent_allowed_tools: Array.isArray(role?.agent_allowed_tools) ? role.agent_allowed_tools : base.agent_allowed_tools,
  };
}

function formatPresetTime(value: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
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

export default function SettingsModal() {
  const confirm = useConfirm();
  const {
    settingsOpen,
    toggleSettings,
    llmConfigs,
    activeLLMConfigId,
    setLLMProfiles,
    theme,
    setTheme,
    accentColor,
    setAccentColor,
    roles,
    setRoles,
    currentChatRoleId,
    currentAgentRoleId,
    setCurrentChatRoleId,
    setCurrentAgentRoleId,
  } = useAppStore();
  const userIsAdmin = useAuthStore((state) => state.user?.system_role === 'admin');
  const activeProfile = useMemo(
    () => llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0],
    [activeLLMConfigId, llmConfigs]
  );
  const [activeTab, setActiveTab] = useState<SettingsTab>(userIsAdmin ? 'models' : 'appearance');
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
  const [roleDraft, setRoleDraft] = useState<Partial<Role>>(createEmptyRoleDraft());
  const [roleIsNew, setRoleIsNew] = useState(false);
  const [roleSaving, setRoleSaving] = useState(false);
  const [roleSaved, setRoleSaved] = useState(false);
  const [roleError, setRoleError] = useState('');
  const [emojiPickerOpen, setEmojiPickerOpen] = useState(false);

  // Preset 状态（与角色绑定）
  const [presets, setPresets] = useState<SystemPromptPreset[]>([]);
  const [presetName, setPresetName] = useState('');
  const [presetBusy, setPresetBusy] = useState(false);
  const [presetDeleteId, setPresetDeleteId] = useState<string | null>(null);
  const [presetNotice, setPresetNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [promptResetting, setPromptResetting] = useState(false);

  const syncSurfaceRoleSelections = useCallback((nextRoles: Role[], preferred?: { chat?: string | null; agent?: string | null }) => {
    const nextChat = getPreferredRoleForSurface(nextRoles, 'chat', preferred?.chat ?? currentChatRoleId);
    const nextAgent = getPreferredRoleForSurface(nextRoles, 'agent', preferred?.agent ?? currentAgentRoleId);
    if ((nextChat?.id ?? '') !== currentChatRoleId) setCurrentChatRoleId(nextChat?.id ?? '');
    if ((nextAgent?.id ?? '') !== currentAgentRoleId) setCurrentAgentRoleId(nextAgent?.id ?? '');
  }, [currentAgentRoleId, currentChatRoleId, setCurrentAgentRoleId, setCurrentChatRoleId]);

  const toggleRoleArrayField = useCallback((field: 'capabilities' | 'chat_capabilities' | 'agent_preflight' | 'agent_allowed_tools', value: string) => {
    setRoleDraft((draftState) => {
      const currentValues = Array.isArray(draftState[field]) ? [...(draftState[field] as string[])] : [];
      return {
        ...draftState,
        [field]: currentValues.includes(value)
          ? currentValues.filter((item) => item !== value)
          : [...currentValues, value],
      };
    });
    setRoleSaved(false);
  }, []);

  const toggleSurface = useCallback((surface: 'chat' | 'agent') => {
    setRoleDraft((draftState) => {
      const currentValues: Array<'chat' | 'agent'> = Array.isArray(draftState.allowed_surfaces) && draftState.allowed_surfaces.length > 0
        ? [...draftState.allowed_surfaces]
        : ['chat'];
      if (currentValues.includes(surface)) {
        const nextValues = currentValues.filter((item) => item !== surface);
        return {
          ...draftState,
          allowed_surfaces: nextValues.length > 0 ? nextValues : currentValues,
        };
      }
      return { ...draftState, allowed_surfaces: [...currentValues, surface] };
    });
    setRoleSaved(false);
  }, []);

  // Embedding 配置状态
  const [embCfg, setEmbCfg] = useState({ api_url: '', api_key: '', model: 'text-embedding-3-small' });
  const [embSaving, setEmbSaving] = useState(false);
  const [embSaved, setEmbSaved] = useState(false);
  const [embTesting, setEmbTesting] = useState(false);
  const [embTestResult, setEmbTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [embError, setEmbError] = useState('');

  // Modal 宽度调整
  const [modalWidth, setModalWidth] = useState(920);
  const modalDragEdge = useRef<'left' | 'right' | null>(null);
  const modalDragStartX = useRef(0);
  const modalDragStartWidth = useRef(920);
  const [modalDragging, setModalDragging] = useState(false);
  /**
   * Guards the backdrop onClick against accidental closure after a drag.
   * Set synchronously on mousedown; cleared in a setTimeout so the
   * browser's click event (which fires after mouseup as a separate macrotask)
   * still sees it as true before we clear it.
   */
  const justDraggedRef = useRef(false);

  const handleModalEdgeMouseDown = useCallback((e: React.MouseEvent, edge: 'left' | 'right') => {
    e.preventDefault();
    e.stopPropagation();
    justDraggedRef.current = true;
    modalDragEdge.current = edge;
    modalDragStartX.current = e.clientX;
    modalDragStartWidth.current = modalWidth;
    setModalDragging(true);
  }, [modalWidth]);

  useEffect(() => {
    if (!modalDragging) return;
    const onMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - modalDragStartX.current;
      const widthDelta = modalDragEdge.current === 'right' ? delta : -delta;
      const newWidth = Math.min(Math.round(window.innerWidth * 0.96), Math.max(640, modalDragStartWidth.current + widthDelta));
      setModalWidth(newWidth);
    };
    const onMouseUp = () => {
      setModalDragging(false);
      modalDragEdge.current = null;
      // Defer the reset so the backdrop's click event (same event-loop turn as
      // mouseup but fired as a separate task) still finds justDraggedRef = true.
      setTimeout(() => { justDraggedRef.current = false; }, 0);
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => { window.removeEventListener('mousemove', onMouseMove); window.removeEventListener('mouseup', onMouseUp); };
  }, [modalDragging]);

  const updateDraft = (updates: Partial<LLMProfile>, options?: { preserveTestFeedback?: boolean }) => {
    setDraft((current) => ({ ...current, ...updates }));
    setSaved(false);
    if (!options?.preserveTestFeedback) {
      setConnectionResult(null);
      setConnectionError('');
    }
  };

  const refreshLLMProfiles = useCallback(async () => {
    const { profiles, activeProfileId } = await listLLMProfiles();
    setLLMProfiles(profiles, activeProfileId);
    return { profiles, activeProfileId };
  }, [setLLMProfiles]);

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

  useEffect(() => {
    if (!settingsOpen) return;
    void refreshLLMProfiles().catch(() => {});
  }, [settingsOpen, refreshLLMProfiles]);

  useEffect(() => {
    if (settingsOpen && !userIsAdmin && activeTab === 'models') {
      setActiveTab('appearance');
    }
  }, [activeTab, settingsOpen, userIsAdmin]);

  const loadEmbeddingConfig = useCallback(async () => {
    try {
      const cfg = await getEmbeddingConfig();
      setEmbCfg({ api_url: cfg.api_url, api_key: cfg.api_key, model: cfg.model || 'text-embedding-3-small' });
    } catch {
      // 静默失败，保留表单默认值
    }
  }, []);

  useEffect(() => {
    if (settingsOpen && userIsAdmin) {
      loadEmbeddingConfig();
    }
  }, [settingsOpen, loadEmbeddingConfig, userIsAdmin]);

  // Auto-select first role when switching to roles tab
  useEffect(() => {
    if (activeTab === 'roles' && !roleIsNew && roles.length > 0) {
      const found = roles.find((r) => r.id === selectedRoleId);
      if (!found) {
        setSelectedRoleId(roles[0].id);
        setRoleDraft(normalizeRoleDraft(roles[0]));
      }
    }
  }, [activeTab, roles, selectedRoleId, roleIsNew]);

  const handleSelectRole = (role: Role) => {
    setSelectedRoleId(role.id);
    setRoleDraft(normalizeRoleDraft(role));
    setRoleIsNew(false);
    setRoleSaved(false);
    setRoleError('');
    setEmojiPickerOpen(false);
    setPresetName('');
    setPresetNotice(null);
  };

  const handleNewRole = () => {
    setSelectedRoleId('__new__');
    setRoleDraft(createEmptyRoleDraft());
    setRoleIsNew(true);
    setRoleSaved(false);
    setRoleError('');
    setEmojiPickerOpen(false);
    setPresets([]);
    setPresetName('');
    setPresetNotice(null);
  };

  const handleSaveRole = async () => {
    if (!roleDraft.name?.trim()) {
      setRoleError('角色名称不能为空');
      return;
    }
    if (!(roleDraft.allowed_surfaces ?? []).length) {
      setRoleError('请至少启用一个 surface');
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
          agent_prompt: roleDraft.agent_prompt || '',
          chat_capabilities: roleDraft.chat_capabilities || [],
          agent_preflight: roleDraft.agent_preflight || [],
          allowed_surfaces: roleDraft.allowed_surfaces || ['chat'],
          agent_allowed_tools: roleDraft.agent_allowed_tools || [],
        });
      } else {
        savedRole = await updateRole(selectedRoleId, {
          name: roleDraft.name.trim(),
          icon: roleDraft.icon,
          description: roleDraft.description,
          system_prompt: roleDraft.system_prompt,
          agent_prompt: roleDraft.agent_prompt,
          chat_capabilities: roleDraft.chat_capabilities,
          agent_preflight: roleDraft.agent_preflight,
          allowed_surfaces: roleDraft.allowed_surfaces,
          agent_allowed_tools: roleDraft.agent_allowed_tools,
        });
      }
      const updatedRoles = await listRoles();
      setRoles(updatedRoles);
      emitAppDataInvalidation(['roles']);
      syncSurfaceRoleSelections(updatedRoles, {
        chat: currentChatRoleId === selectedRoleId ? savedRole.id : currentChatRoleId,
        agent: currentAgentRoleId === selectedRoleId ? savedRole.id : currentAgentRoleId,
      });
      setSelectedRoleId(savedRole.id);
      setRoleDraft(normalizeRoleDraft(savedRole));
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
      emitAppDataInvalidation(['roles']);
      syncSurfaceRoleSelections(updatedRoles);
      if (updatedRoles.length > 0) {
        setSelectedRoleId(updatedRoles[0].id);
        setRoleDraft(normalizeRoleDraft(updatedRoles[0]));
        setRoleIsNew(false);
      } else {
        setSelectedRoleId('');
        setRoleDraft(createEmptyRoleDraft());
      }
    } catch (e) {
      setRoleError((e as Error).message || '删除失败');
    } finally {
      setRoleSaving(false);
    }
  };

  const toggleChatCapability = (capability: string) => {
    toggleRoleArrayField('chat_capabilities', capability);
  };

  const toggleAgentPreflight = (capability: string) => {
    toggleRoleArrayField('agent_preflight', capability);
  };

  // 加载当前角色的预设列表
  const loadPresets = useCallback(async (roleId: string) => {
    if (!roleId || roleId === '__new__') { setPresets([]); return; }
    try {
      const all = await listSystemPromptPresets();
      setPresets(all.filter((p) => p.role_id === roleId));
    } catch {
      setPresets([]);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'roles' && selectedRoleId && selectedRoleId !== '__new__') {
      void loadPresets(selectedRoleId);
    }
  }, [activeTab, selectedRoleId, loadPresets]);

  const handleSavePreset = async () => {
    if (!presetName.trim()) { setPresetNotice({ ok: false, text: '请输入预设名称' }); return; }
    if (!(roleDraft.system_prompt ?? '').trim()) { setPresetNotice({ ok: false, text: '系统提示词不能为空' }); return; }
    setPresetBusy(true);
    setPresetNotice(null);
    try {
      const result = await createSystemPromptPreset(presetName.trim(), selectedRoleId, roleDraft.system_prompt ?? '');
      setPresets((prev) => [result.preset, ...prev]);
      setPresetName('');
      setPresetNotice({ ok: true, text: result.message });
    } catch (e) {
      setPresetNotice({ ok: false, text: (e as Error).message || '保存预设失败' });
    } finally {
      setPresetBusy(false);
    }
  };

  const handleImportPreset = (preset: SystemPromptPreset) => {
    setRoleDraft((d) => ({ ...d, system_prompt: preset.prompt }));
    setRoleSaved(false);
    setPresetNotice({ ok: true, text: `已导入「${preset.name}」，点击保存生效` });
  };

  const handleDeletePreset = async (preset: SystemPromptPreset) => {
    const confirmed = await confirm({
      title: `删除预设「${preset.name}」？`,
      description: '删除后将无法再从预设库直接导入该提示词。',
      confirmLabel: '确认删除',
      tone: 'danger',
    });
    if (!confirmed) return;
    setPresetDeleteId(preset.id);
    try {
      await deleteSystemPromptPreset(preset.id);
      setPresets((prev) => prev.filter((p) => p.id !== preset.id));
      setPresetNotice({ ok: true, text: '?????' });
    } catch (e) {
      setPresetNotice({ ok: false, text: (e as Error).message || '????' });
    } finally {
      setPresetDeleteId(null);
    }
  };

  const handleResetPrompt = async () => {
    if (!selectedRoleId || selectedRoleId === '__new__') return;
    const confirmed = await confirm({
      title: '恢复默认系统提示词？',
      description: '当前角色已编辑的系统提示词将被默认值覆盖。',
      confirmLabel: '恢复默认',
      tone: 'danger',
    });
    if (!confirmed) return;
    setPromptResetting(true);
    try {
      const result = await resetSystemPrompt(selectedRoleId);
      const defaultPrompt = result.default_prompt ?? result.resolved_prompt ?? result.prompt ?? '';
      setRoleDraft((d) => ({ ...d, system_prompt: defaultPrompt }));
      setRoleSaved(false);
    } catch {
      // ????
    } finally {
      setPromptResetting(false);
    }
  };

  const agentSurfaceEnabled = (roleDraft.allowed_surfaces ?? []).includes('agent');

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

  const handleSave = async () => {
    const nextDraft = {
      ...draft,
      name: draft.name.trim() || `模型 ${llmConfigs.length + (isNewDraft ? 1 : 0)}`,
      hasApiKey: draft.hasApiKey ?? Boolean(draft.apiKey),
    };
    try {
      if (isNewDraft) {
        await createLLMProfile(nextDraft);
      } else {
        await updateLLMProfile(nextDraft);
      }
      const { profiles, activeProfileId } = await refreshLLMProfiles();
      emitAppDataInvalidation(['llmProfiles']);
      const persistedProfile = profiles.find((profile) => profile.id === nextDraft.id)
        ?? profiles.find((profile) => profile.id === activeProfileId)
        ?? nextDraft;
      setDraft({ ...persistedProfile });
      setSelectedId(persistedProfile.id);
      setIsNewDraft(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (error) {
      setConnectionError((error as Error).message || '保存失败');
    }
  };

  const handleDelete = async () => {
    if (isNewDraft) {
      if (activeProfile) {
        handleSelectProfile(activeProfile);
      }
      return;
    }

    if (llmConfigs.length <= 1) return;

    try {
      await deleteLLMProfile(draft.id);
      const { profiles, activeProfileId } = await refreshLLMProfiles();
      emitAppDataInvalidation(['llmProfiles']);
      const fallbackProfile = profiles.find((config) => config.id === activeProfileId)
        ?? profiles.find((config) => config.id !== draft.id);

      if (fallbackProfile) {
        setSelectedId(fallbackProfile.id);
        setDraft({ ...fallbackProfile });
      }
      setIsNewDraft(false);
      setConnectionResult(null);
      setConnectionError('');
    } catch (error) {
      setConnectionError((error as Error).message || '删除失败');
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
    } catch (error) {
      setConnectionError((error as Error).message || '连接测试失败');
    } finally {
      setTestingConnection(false);
    }
  };

  const handleActivateProfile = async (profileId: string) => {
    try {
      await setActiveLLMProfile(profileId);
      const { profiles, activeProfileId } = await refreshLLMProfiles();
      emitAppDataInvalidation(['llmProfiles']);
      const nextProfile = profiles.find((profile) => profile.id === profileId)
        ?? profiles.find((profile) => profile.id === activeProfileId);
      if (nextProfile) {
        setDraft({ ...nextProfile });
        setSelectedId(nextProfile.id);
      }
    } catch (error) {
      setConnectionError((error as Error).message || '切换默认模型失败');
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

  return (/*
    // 遮罩层
    */<div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget && !justDraggedRef.current) handleClose(); }}
    >
      <div
        className="win-modal relative flex max-h-[90vh] flex-col overflow-hidden"
        style={{ width: modalWidth, maxWidth: '96vw', minWidth: 640 }}
      >
        {/* 左侧拖拽手柄 */}
        <div
          onMouseDown={(e) => handleModalEdgeMouseDown(e, 'left')}
          className={clsx('absolute left-0 top-0 h-full w-1.5 cursor-col-resize z-10 hover:bg-primary/40 transition-colors', modalDragging && modalDragEdge.current === 'left' && 'bg-primary/60')}
        />
        {/* 右侧拖拽手柄 */}
        <div
          onMouseDown={(e) => handleModalEdgeMouseDown(e, 'right')}
          className={clsx('absolute right-0 top-0 h-full w-1.5 cursor-col-resize z-10 hover:bg-primary/40 transition-colors', modalDragging && modalDragEdge.current === 'right' && 'bg-primary/60')}
        />
        {/* 标题栏 */}
        <div className="win-toolbar flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <span>⚙️</span> 设置
            </h2>
            {/* Tab 切换 */}
            <div className="flex items-center gap-1 rounded-lg border border-surface-divider bg-surface p-1 dark:border-dark-divider dark:bg-dark-sidebar">
              {userIsAdmin && (
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
              )}
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

        {/* 角色管理 Tab */}
        {activeTab === 'roles' && (
          <div className="flex flex-col flex-1 min-h-0">
            <div className="flex flex-1 min-h-0 border-b border-surface-divider dark:border-dark-divider">
              {/* 左侧：角色列表 */}
              <div className="w-[240px] flex-shrink-0 border-r border-surface-divider dark:border-dark-divider bg-[#F7F8FA] p-4 space-y-3 overflow-y-auto dark:bg-dark">
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
                        {role.is_builtin === 1 && (
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
                    <div className="grid grid-cols-[1fr_160px] gap-4">
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
                        <div className="relative">
                          <button
                            type="button"
                            onClick={() => setEmojiPickerOpen((o) => !o)}
                            className="win-input flex w-full items-center justify-between gap-3 px-3"
                          >
                            <span className="text-2xl leading-none">{roleDraft.icon || '🤖'}</span>
                            <span className="text-xs text-text-secondary">▾</span>
                          </button>
                          {emojiPickerOpen && (
                            <div className="absolute left-0 top-full z-20 mt-1.5 w-full rounded-md border border-surface-divider bg-white p-2 shadow-md dark:border-dark-divider dark:bg-dark-card">
                              <div className="grid grid-cols-2 gap-2">
                                {ROLE_EMOJIS.map((emoji) => (
                                  <button
                                    key={emoji}
                                    type="button"
                                    onClick={() => {
                                      setRoleDraft((d) => ({ ...d, icon: emoji }));
                                      setRoleSaved(false);
                                      setEmojiPickerOpen(false);
                                    }}
                                    className={clsx(
                                      'flex h-10 w-full items-center justify-center rounded-md border text-[22px] shadow-sm transition-colors',
                                      'border-surface-divider bg-surface-sidebar/35 hover:border-primary/30 hover:bg-surface-sidebar dark:border-dark-divider dark:bg-dark-sidebar/50 dark:hover:bg-dark-sidebar',
                                      roleDraft.icon === emoji && 'border-primary/50 bg-primary/10 text-text-primary ring-1 ring-inset ring-primary/25 dark:text-text-dark-primary'
                                    )}
                                  >
                                    {emoji}
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
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
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="block text-sm font-medium">System Prompt</label>
                        {!roleIsNew && selectedRoleId && (
                          <button
                            type="button"
                            onClick={() => void handleResetPrompt()}
                            disabled={promptResetting}
                            className="win-button h-6 px-2 text-[11px] text-text-secondary hover:text-text-primary"
                          >
                            {promptResetting ? '恢复中...' : '恢复默认'}
                          </button>
                        )}
                      </div>
                      <textarea
                        value={roleDraft.system_prompt ?? ''}
                        onChange={(e) => { setRoleDraft((d) => ({ ...d, system_prompt: e.target.value })); setRoleSaved(false); }}
                        placeholder="输入此角色的系统提示词..."
                        rows={8}
                        className="win-input w-full resize-none"
                      />
                    </div>

                    {/* 提示词预设面板（新建角色时隐藏） */}
                    {!roleIsNew && selectedRoleId && (
                      <div className="rounded-lg border border-surface-divider bg-white px-4 py-3 space-y-3 dark:border-dark-divider dark:bg-dark-card">
                        <p className="text-xs font-medium text-text-secondary">💾 提示词预设</p>

                        {/* 保存当前为预设 */}
                        <div className="flex gap-2">
                          <input
                            type="text"
                            value={presetName}
                            onChange={(e) => setPresetName(e.target.value)}
                            placeholder="给这个预设起个名字"
                            className="win-input flex-1 text-sm"
                          />
                          <button
                            type="button"
                            onClick={() => void handleSavePreset()}
                            disabled={presetBusy}
                            className="win-button-primary h-8 px-3 text-xs flex-shrink-0"
                          >
                            {presetBusy ? '保存中...' : '保存为预设'}
                          </button>
                        </div>

                        {/* 操作反馈 */}
                        {presetNotice && (
                          <p className={clsx('text-xs', presetNotice.ok ? 'text-green-600 dark:text-green-400' : 'text-red-500')}>
                            {presetNotice.text}
                          </p>
                        )}

                        {/* 预设列表 */}
                        {presets.length === 0 ? (
                          <p className="text-xs text-text-secondary border border-dashed border-surface-divider rounded-md px-3 py-3 dark:border-dark-divider">
                            还没有保存过预设
                          </p>
                        ) : (
                          <div className="space-y-2">
                            {presets.map((preset) => (
                              <div key={preset.id} className="flex items-center justify-between gap-2 rounded-md border border-surface-divider bg-[#F7F8FA] px-3 py-2 dark:border-dark-divider dark:bg-dark">
                                <div className="min-w-0 flex-1">
                                  <p className="text-xs font-medium truncate">{preset.name}</p>
                                  <p className="text-[10px] text-text-secondary mt-0.5">
                                    {formatPresetTime(preset.updated_at || preset.created_at) || '刚刚'}
                                  </p>
                                </div>
                                <div className="flex items-center gap-1 flex-shrink-0">
                                  <button
                                    type="button"
                                    onClick={() => handleImportPreset(preset)}
                                    disabled={presetDeleteId === preset.id}
                                    className="win-button h-7 px-2 text-[11px]"
                                  >
                                    导入
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => void handleDeletePreset(preset)}
                                    disabled={presetDeleteId === preset.id}
                                    className="win-button h-7 px-2 text-[11px] text-red-500 hover:text-red-600"
                                  >
                                    {presetDeleteId === preset.id ? '…' : '删除'}
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    <Field label="Chat 模式">
                      <div className="rounded-lg border border-surface-divider bg-white px-4 py-4 space-y-3 dark:border-dark-divider dark:bg-dark-card">
                        <label className="flex items-start gap-3 rounded-lg border border-surface-divider bg-[#F7F8FA] px-3 py-3 text-sm dark:border-dark-divider dark:bg-dark">
                          <input
                            type="checkbox"
                            checked={(roleDraft.allowed_surfaces ?? []).includes('chat')}
                            onChange={() => toggleSurface('chat')}
                            className="mt-0.5 h-4 w-4 accent-primary"
                          />
                          <span className="min-w-0">
                            <span className="block font-medium text-text-primary">可用于 Chat</span>
                            <span className="mt-1 block text-xs text-text-secondary">作为普通对话角色使用，只影响 Chat surface。</span>
                          </span>
                        </label>
                        <div className="rounded-md border border-dashed border-surface-divider px-3 py-3 text-xs leading-5 text-text-secondary dark:border-dark-divider">
                          下面这些开关只控制 Chat 的自动增强，不等于 Agent 的执行前能力或运行时工具权限。
                        </div>
                        <div className="space-y-2">
                          <p className="text-xs font-medium uppercase tracking-[0.12em] text-text-secondary">自动增强</p>
                          {CHAT_POLICY_OPTIONS.map((capability) => (
                            <label key={capability.key} className="flex items-start gap-3 rounded-lg border border-surface-divider bg-[#F7F8FA] px-3 py-3 text-sm dark:border-dark-divider dark:bg-dark">
                              <input
                                type="checkbox"
                                checked={(roleDraft.chat_capabilities ?? []).includes(capability.key)}
                                onChange={() => toggleChatCapability(capability.key)}
                                className="mt-0.5 h-4 w-4 accent-primary"
                              />
                              <span className="min-w-0">
                                <span className="block font-medium text-text-primary">{capability.label}</span>
                                <span className="mt-1 block text-xs text-text-secondary">{capability.hint}</span>
                              </span>
                            </label>
                          ))}
                        </div>
                      </div>
                    </Field>
                    <Field label="Agent 模式">
                      <div className="rounded-lg border border-surface-divider bg-white px-4 py-4 space-y-3 dark:border-dark-divider dark:bg-dark-card">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium text-text-primary">Agent 策略</p>
                            <p className="mt-1 text-xs text-text-secondary">Agent 可以在不启用任何运行时工具的情况下执行；工具开关只控制运行中是否允许调用专用工具。</p>
                          </div>
                          <span className={clsx('win-badge text-[10px]', agentSurfaceEnabled ? 'border-green-200 bg-green-50 text-green-600 dark:border-green-800 dark:bg-green-900/20 dark:text-green-400' : 'border-amber-200 bg-amber-50 text-amber-600 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300')}>
                            {agentSurfaceEnabled ? 'Agent 已启用' : 'Agent 未启用'}
                          </span>
                        </div>
                        <label className="flex items-start gap-3 rounded-lg border border-surface-divider bg-[#F7F8FA] px-3 py-3 text-sm dark:border-dark-divider dark:bg-dark">
                          <input
                            type="checkbox"
                            checked={(roleDraft.allowed_surfaces ?? []).includes('agent')}
                            onChange={() => toggleSurface('agent')}
                            className="mt-0.5 h-4 w-4 accent-primary"
                          />
                          <span className="min-w-0">
                            <span className="block font-medium text-text-primary">可用于 Agent</span>
                            <span className="mt-1 block text-xs text-text-secondary">作为任务执行型 Agent 使用，单独拥有 Agent 专用 Prompt 和运行时工具权限。</span>
                          </span>
                        </label>
                        <Field label="执行前能力">
                          <div className="space-y-2">
                            {AGENT_PREFLIGHT_OPTIONS.map((capability) => (
                              <label key={capability.key} className="flex items-start gap-3 rounded-lg border border-surface-divider bg-[#F7F8FA] px-3 py-3 text-sm dark:border-dark-divider dark:bg-dark">
                                <input
                                  type="checkbox"
                                  checked={(roleDraft.agent_preflight ?? []).includes(capability.key)}
                                  onChange={() => toggleAgentPreflight(capability.key)}
                                  disabled={!agentSurfaceEnabled}
                                  className="mt-0.5 h-4 w-4 accent-primary"
                                />
                                <span className="min-w-0">
                                  <span className="block font-medium text-text-primary">{capability.label}</span>
                                  <span className="mt-1 block text-xs text-text-secondary">{capability.hint}</span>
                                </span>
                              </label>
                            ))}
                          </div>
                        </Field>
                        {agentSurfaceEnabled ? (
                          <>
                            <div className="rounded-md border border-dashed border-surface-divider px-3 py-3 text-xs leading-5 text-text-secondary dark:border-dark-divider">
                              本阶段先整理信息架构。这里展示的是 Agent 运行时工具；执行前匹配与执行前检索会在下一阶段单独拆分为预处理能力。
                            </div>
                            <Field label="Agent 专用 Prompt">
                              <textarea
                                value={roleDraft.agent_prompt ?? ''}
                                onChange={(e) => { setRoleDraft((d) => ({ ...d, agent_prompt: e.target.value })); setRoleSaved(false); }}
                                placeholder="补充仅在 Agent surface 下生效的执行策略、边界或格式要求"
                                rows={5}
                                className="win-input w-full resize-none"
                              />
                            </Field>
                            <Field label="运行时工具">
                              <div className="space-y-2">
                                {AGENT_TOOL_OPTIONS.map((tool) => (
                                  <label key={tool.key} className="flex items-start gap-3 rounded-lg border border-surface-divider bg-[#F7F8FA] px-3 py-3 text-sm dark:border-dark-divider dark:bg-dark">
                                    <input
                                      type="checkbox"
                                      checked={(roleDraft.agent_allowed_tools ?? []).includes(tool.key)}
                                      onChange={() => toggleRoleArrayField('agent_allowed_tools', tool.key)}
                                      className="mt-0.5 h-4 w-4 accent-primary"
                                    />
                                    <span className="min-w-0">
                                      <span className="block font-medium text-text-primary">{tool.label}</span>
                                      <span className="mt-1 block text-xs text-text-secondary">{tool.hint}</span>
                                    </span>
                                  </label>
                                ))}
                              </div>
                            </Field>
                          </>
                        ) : (
                          <p className="rounded-md border border-dashed border-surface-divider px-3 py-3 text-xs text-text-secondary dark:border-dark-divider">
                            先启用 Agent 模式，再配置 Agent 专用 Prompt 和运行时工具。
                          </p>
                        )}
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
                disabled={!!(roleSaving || (!roleIsNew && !selectedRoleId))}
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
                  onClick={() => { void handleActivateProfile(draft.id); }}
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
              <div className="space-y-2">
                <input
                  type="password"
                  value={draft.apiKey}
                  onChange={(e) => updateDraft({ apiKey: e.target.value })}
                  placeholder={draft.hasApiKey && !isNewDraft ? '留空表示保留当前 Key' : 'sk-...'}
                  className={inputCls}
                />
                {draft.hasApiKey && !isNewDraft && (
                  <p className="text-xs text-text-secondary">
                    已保存的 Key 不会回显；留空表示保持当前 Key，输入新值会覆盖原配置。
                  </p>
                )}
              </div>
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
