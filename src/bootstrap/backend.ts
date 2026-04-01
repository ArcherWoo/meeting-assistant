import { checkHealth, listLLMProfiles, listRoles } from '@/services/api';
import { useAppStore } from '@/stores/appStore';
import { useChatStore } from '@/stores/chatStore';
import { getPreferredRoleForSurface } from '@/utils/roles';

interface InitBackendOptions {
  loadProtectedData?: boolean;
}

/**
 * 初始化后端连接状态，并在已登录时拉取受保护的角色/会话数据。
 * 健康检查和鉴权数据加载分开处理，避免未登录时把 401 误判成“后端未连接”。
 */
export async function initBackend(options: InitBackendOptions = {}): Promise<void> {
  const { loadProtectedData = false } = options;
  const appStore = useAppStore.getState();

  if (loadProtectedData) {
    appStore.setRolesLoaded(false);
  }

  let healthy = false;
  try {
    healthy = await checkHealth();
  } catch (error) {
    console.warn('[Init] Backend health check failed:', error);
  }

  appStore.setBackend({ connected: healthy, port: healthy ? 5173 : 0 });
  if (!healthy) {
    if (loadProtectedData) {
      appStore.setRolesLoaded(true);
    }
    return;
  }

  if (!loadProtectedData) {
    return;
  }

  try {
    const roles = await listRoles();
    const { profiles, activeProfileId } = await listLLMProfiles();
    useAppStore.getState().setLLMProfiles(profiles, activeProfileId);
    if (roles.length > 0) {
      const nextAppState = useAppStore.getState();
      nextAppState.setRoles(roles);
      const chatRole = getPreferredRoleForSurface(roles, 'chat', nextAppState.currentChatRoleId) ?? roles[0];
      const agentRole = getPreferredRoleForSurface(roles, 'agent', nextAppState.currentAgentRoleId);

      nextAppState.setCurrentChatRoleId(chatRole.id);
      nextAppState.setCurrentAgentRoleId((agentRole ?? chatRole).id);

      if (nextAppState.activeSurface === 'agent' && !agentRole) {
        nextAppState.setActiveSurface('chat');
      } else {
        nextAppState.setActiveSurface(nextAppState.activeSurface);
      }
    }
    await useChatStore.getState().bootstrap();
  } catch (error) {
    console.warn('[Init] Authenticated bootstrap failed:', error);
  } finally {
    useAppStore.getState().setRolesLoaded(true);
  }
}
