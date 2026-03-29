/**
 * React 应用入口
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';
import { checkHealth, listRoles } from './services/api';
import { useAppStore } from './stores/appStore';
import { useChatStore } from './stores/chatStore';
import { getPreferredRoleForSurface } from './utils/roles';

/** 初始化后端连接 + 加载角色列表 */
async function initBackend(): Promise<void> {
  try {
    const healthy = await checkHealth();
    useAppStore.getState().setBackend({ connected: healthy, port: 5173 });
    if (healthy) {
      const roles = await listRoles();
      if (roles.length > 0) {
        const appState = useAppStore.getState();
        appState.setRoles(roles);
        const chatRole = getPreferredRoleForSurface(roles, 'chat', appState.currentChatRoleId) ?? roles[0];
        const agentRole = getPreferredRoleForSurface(roles, 'agent', appState.currentAgentRoleId);

        appState.setCurrentChatRoleId(chatRole.id);
        appState.setCurrentAgentRoleId((agentRole ?? chatRole).id);

        if (appState.activeSurface === 'agent' && !agentRole) {
          appState.setActiveSurface('chat');
        } else {
          appState.setActiveSurface(appState.activeSurface);
        }
      }
      await useChatStore.getState().bootstrap();
    }
  } catch (error) {
    console.warn('[Init] Backend connection failed:', error);
    useAppStore.getState().setBackend({ connected: false, port: 0 });
  } finally {
    // 无论成功或失败，标记加载完成，让 UI 离开等待态
    useAppStore.getState().setRolesLoaded(true);
  }
}

// 初始化后端连接
initBackend();

// 渲染 React 应用
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
