/**
 * React 应用入口
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';
import { checkHealth } from './services/api';
import { useAppStore } from './stores/appStore';

/** 初始化后端连接 */
async function initBackend(): Promise<void> {
  try {
    // 健康检查
    const healthy = await checkHealth();
    useAppStore.getState().setBackend({ connected: healthy, port: 5173 });
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
