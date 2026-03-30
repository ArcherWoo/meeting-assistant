/**
 * 全局应用状态管理 (Zustand)
 * 管理：角色切换、UI 状态、后端连接、多模型配置
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { v4 as uuidv4 } from 'uuid';
import type { Role, LLMConfig, LLMProfile, Theme, BackendStatus } from '@/types';

interface PersistedAppState {
  theme?: Theme;
  accentColor?: string;
  llmConfig?: LLMConfig;
  llmConfigs?: Partial<LLMProfile>[];
  activeLLMConfigId?: string;
  currentRoleId?: string;
  currentChatRoleId?: string;
  currentAgentRoleId?: string;
  activeSurface?: 'chat' | 'agent';
}

const createLLMProfile = (overrides: Partial<LLMProfile> = {}): LLMProfile => ({
  id: uuidv4(),
  name: '默认模型',
  apiUrl: 'https://api.openai.com/v1',
  apiKey: '',
  model: 'gpt-4o',
  temperature: 0.7,
  maxTokens: 4096,
  stream: true,
  ...overrides,
});

const normalizeLLMProfiles = (
  profiles?: Partial<LLMProfile>[],
  legacyConfig?: LLMConfig
): LLMProfile[] => {
  if (Array.isArray(profiles) && profiles.length > 0) {
    return profiles.map((profile, index) => createLLMProfile({
      ...profile,
      id: profile.id || uuidv4(),
      name: profile.name?.trim() || `模型 ${index + 1}`,
    }));
  }

  if (legacyConfig) {
    return [createLLMProfile({ name: '默认模型', ...legacyConfig })];
  }

  return [createLLMProfile()];
};

const initialLLMConfigs = normalizeLLMProfiles();

interface AppState {
  // 角色系统
  roles: Role[];
  activeSurface: 'chat' | 'agent';
  currentChatRoleId: string;
  currentAgentRoleId: string;
  currentRoleId: string;
  setRoles: (roles: Role[]) => void;
  setActiveSurface: (surface: 'chat' | 'agent') => void;
  setCurrentChatRoleId: (id: string) => void;
  setCurrentAgentRoleId: (id: string) => void;
  setCurrentRoleId: (id: string) => void;
  /** 角色列表初始加载是否完成（成功或失败均置为 true） */
  rolesLoaded: boolean;
  setRolesLoaded: (loaded: boolean) => void;

  // 后端连接状态
  backend: BackendStatus;
  setBackend: (status: BackendStatus) => void;

  // LLM 配置（持久化到 localStorage）
  llmConfigs: LLMProfile[];
  activeLLMConfigId: string;
  setActiveLLMConfig: (id: string) => void;
  saveLLMConfig: (config: LLMProfile) => void;
  removeLLMConfig: (id: string) => void;

  // UI 状态
  theme: Theme;
  setTheme: (theme: Theme) => void;
  accentColor: string;
  setAccentColor: (color: string) => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  contextPanelVisible: boolean;
  toggleContextPanel: () => void;
  /** 主区域视图切换：chat（聊天区）或 knowhow（规则管理） */
  activeView: 'chat' | 'knowhow' | 'admin';
  setActiveView: (view: 'chat' | 'knowhow' | 'admin') => void;
  /** 设置面板开关 */
  settingsOpen: boolean;
  toggleSettings: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // 角色系统
      roles: [],
      activeSurface: 'chat',
      currentChatRoleId: 'copilot',
      currentAgentRoleId: 'executor',
      currentRoleId: 'copilot',
      setRoles: (roles) => set({ roles }),
      setActiveSurface: (surface) => set((state) => ({
        activeSurface: surface,
        currentRoleId: surface === 'chat' ? state.currentChatRoleId : state.currentAgentRoleId,
      })),
      setCurrentChatRoleId: (id) => set((state) => ({
        currentChatRoleId: id,
        currentRoleId: state.activeSurface === 'chat' ? id : state.currentRoleId,
      })),
      setCurrentAgentRoleId: (id) => set((state) => ({
        currentAgentRoleId: id,
        currentRoleId: state.activeSurface === 'agent' ? id : state.currentRoleId,
      })),
      setCurrentRoleId: (id) => set((state) => (
        state.activeSurface === 'chat'
          ? { currentChatRoleId: id, currentRoleId: id }
          : { currentAgentRoleId: id, currentRoleId: id }
      )),
      rolesLoaded: false,
      setRolesLoaded: (loaded) => set({ rolesLoaded: loaded }),

      // 后端初始未连接
      backend: { connected: false, port: 0 },
      setBackend: (status) => set({ backend: status }),

      // LLM 默认配置
      llmConfigs: initialLLMConfigs,
      activeLLMConfigId: initialLLMConfigs[0].id,
      setActiveLLMConfig: (id) =>
        set((state) => (
          state.llmConfigs.some((config) => config.id === id)
            ? { activeLLMConfigId: id }
            : {}
        )),
      saveLLMConfig: (config) =>
        set((state) => {
          const normalizedConfig = {
            ...config,
            name: config.name.trim() || `模型 ${state.llmConfigs.length + 1}`,
          };
          const exists = state.llmConfigs.some((item) => item.id === normalizedConfig.id);

          return {
            llmConfigs: exists
              ? state.llmConfigs.map((item) => (item.id === normalizedConfig.id ? normalizedConfig : item))
              : [...state.llmConfigs, normalizedConfig],
            activeLLMConfigId: state.activeLLMConfigId || normalizedConfig.id,
          };
        }),
      removeLLMConfig: (id) =>
        set((state) => {
          if (state.llmConfigs.length <= 1) return {};

          const nextConfigs = state.llmConfigs.filter((config) => config.id !== id);
          return {
            llmConfigs: nextConfigs,
            activeLLMConfigId:
              state.activeLLMConfigId === id ? nextConfigs[0].id : state.activeLLMConfigId,
          };
        }),

      // UI 默认状态
      theme: 'system',
      setTheme: (theme) => set({ theme }),
      accentColor: '#2563EB',
      setAccentColor: (color) => set({ accentColor: color }),
      sidebarCollapsed: false,
      toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
      contextPanelVisible: false,
      toggleContextPanel: () =>
        set((state) => ({ contextPanelVisible: !state.contextPanelVisible })),
      activeView: 'chat',
      setActiveView: (view) => set({ activeView: view }),
      settingsOpen: false,
      toggleSettings: () => set((state) => ({ settingsOpen: !state.settingsOpen })),
    }),
    {
      name: 'meeting-assistant-app',
      version: 4,
      migrate: (persistedState) => {
        const persisted = (persistedState ?? {}) as PersistedAppState;
        const llmConfigs = normalizeLLMProfiles(persisted.llmConfigs, persisted.llmConfig);
        const activeLLMConfigId = llmConfigs.some((config) => config.id === persisted.activeLLMConfigId)
          ? (persisted.activeLLMConfigId as string)
          : llmConfigs[0].id;
        const normalizedCurrentRoleId = persisted.currentRoleId === 'agent'
          ? 'executor'
          : (persisted.currentRoleId ?? 'copilot');
        const activeSurface = persisted.activeSurface
          ?? (normalizedCurrentRoleId === 'executor' ? 'agent' : 'chat');
        const currentChatRoleId = persisted.currentChatRoleId
          ?? (activeSurface === 'chat' ? normalizedCurrentRoleId : 'copilot');
        const currentAgentRoleId = persisted.currentAgentRoleId
          ?? (activeSurface === 'agent' ? normalizedCurrentRoleId : 'executor');

        return {
          ...persisted,
          theme: persisted.theme ?? 'system',
          accentColor: persisted.accentColor ?? '#2563EB',
          llmConfigs,
          activeLLMConfigId,
          activeSurface,
          currentChatRoleId,
          currentAgentRoleId,
          currentRoleId: activeSurface === 'chat' ? currentChatRoleId : currentAgentRoleId,
        };
      },
      // 仅持久化 LLM 配置和主题，不持久化运行时状态
      partialize: (state) => ({
        llmConfigs: state.llmConfigs,
        activeLLMConfigId: state.activeLLMConfigId,
        theme: state.theme,
        accentColor: state.accentColor,
        activeSurface: state.activeSurface,
        currentRoleId: state.currentRoleId,
        currentChatRoleId: state.currentChatRoleId,
        currentAgentRoleId: state.currentAgentRoleId,
      }),
    }
  )
);
