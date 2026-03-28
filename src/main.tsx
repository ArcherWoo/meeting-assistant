/**
 * React 应用入口
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';
import { checkHealth, listRoles } from './services/api';
import { useAppStore } from './stores/appStore';

/** 初始化后端连接 + 加载角色列表 */
async function initBackend(): Promise<void> {
  try {
    const healthy = await checkHealth();
    useAppStore.getState().setBackend({ connected: healthy, port: 5173 });
    if (healthy) {
      const roles = await listRoles();
      if (roles.length > 0) {
        useAppStore.getState().setRoles(roles);
        // 如果当前 roleId 不在列表中，切换到第一个角色
        const current = useAppStore.getState().currentRoleId;
        if (!roles.find((r) => r.id === current)) {
          useAppStore.getState().setCurrentRoleId(roles[0].id);
        }
      }
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
