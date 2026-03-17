/**
 * React 应用入口
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';
import { setBackendPort, checkHealth } from './services/api';
import { useAppStore } from './stores/appStore';

/** 初始化后端连接 */
async function initBackend(): Promise<void> {
  try {
    // Electron 环境：从主进程获取后端端口
    if (window.electronAPI) {
      const port = await window.electronAPI.getBackendPort();
      setBackendPort(port);
      useAppStore.getState().setBackend({ connected: true, port });
    } else {
      // 纯浏览器开发环境：使用默认端口
      setBackendPort(8765);
    }

    // 健康检查
    const healthy = await checkHealth();
    const port = (window as any).__BACKEND_PORT__ || 8765;
    useAppStore.getState().setBackend({ connected: healthy, port });
  } catch (error) {
    console.warn('[Init] Backend connection failed:', error);
    useAppStore.getState().setBackend({ connected: false, port: 0 });
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

