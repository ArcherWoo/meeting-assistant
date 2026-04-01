/**
 * 全局应用状态管理 (Zustand)
 * 管理：角色切换、UI 状态、后端连接、后端下发的 LLM 配置
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Role, LLMProfile, Theme, BackendStatus } from '@/types';

interface PersistedAppState {
  theme?: Theme;
  accentColor?: string;
  currentRoleId?: string;
  currentChatRoleId?: string;
  currentAgentRoleId?: string;
  activeSurface?: 'chat' | 'agent';
}

interface AppState {
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
  rolesLoaded: boolean;
  setRolesLoaded: (loaded: boolean) => void;

  backend: BackendStatus;
  setBackend: (status: BackendStatus) => void;

  llmConfigs: LLMProfile[];
  activeLLMConfigId: string;
  setLLMProfiles: (configs: LLMProfile[], activeId?: string) => void;
  setActiveLLMConfig: (id: string) => void;

  theme: Theme;
  setTheme: (theme: Theme) => void;
  accentColor: string;
  setAccentColor: (color: string) => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  contextPanelVisible: boolean;
  toggleContextPanel: () => void;
  activeView: 'chat' | 'knowhow' | 'admin';
  setActiveView: (view: 'chat' | 'knowhow' | 'admin') => void;
  settingsOpen: boolean;
  toggleSettings: () => void;
}

function normalizeLLMProfiles(configs: LLMProfile[]): LLMProfile[] {
  return configs.map((config, index) => ({
    ...config,
    id: config.id || `llm-${index + 1}`,
    name: config.name?.trim() || `模型 ${index + 1}`,
    apiUrl: config.apiUrl?.trim() || 'https://api.openai.com/v1',
    apiKey: config.apiKey ?? '',
    model: config.model?.trim() || 'gpt-4o',
    temperature: typeof config.temperature === 'number' ? config.temperature : 0.7,
    maxTokens: typeof config.maxTokens === 'number' ? config.maxTokens : 4096,
    stream: typeof config.stream === 'boolean' ? config.stream : true,
    hasApiKey: config.hasApiKey ?? Boolean(config.apiKey),
    availableModels: Array.isArray(config.availableModels) ? config.availableModels : [],
  }));
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
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

      backend: { connected: false, port: 0 },
      setBackend: (status) => set({ backend: status }),

      llmConfigs: [],
      activeLLMConfigId: '',
      setLLMProfiles: (configs, activeId) => set(() => {
        const normalizedConfigs = normalizeLLMProfiles(configs);
        const nextActiveId = normalizedConfigs.some((config) => config.id === activeId)
          ? (activeId ?? '')
          : (normalizedConfigs[0]?.id ?? '');

        return {
          llmConfigs: normalizedConfigs,
          activeLLMConfigId: nextActiveId,
        };
      }),
      setActiveLLMConfig: (id) =>
        set((state) => (
          state.llmConfigs.some((config) => config.id === id)
            ? { activeLLMConfigId: id }
            : {}
        )),

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
      name: '智枢-app',
      version: 5,
      migrate: (persistedState) => {
        const persisted = (persistedState ?? {}) as PersistedAppState;
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
          activeSurface,
          currentChatRoleId,
          currentAgentRoleId,
          currentRoleId: activeSurface === 'chat' ? currentChatRoleId : currentAgentRoleId,
        };
      },
      partialize: (state) => ({
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
