/**
 * 应用根组件
 * 负责：主题管理、布局渲染、后端连接状态监控
 */
import { useEffect } from 'react';
import { useAppStore } from './stores/appStore';
import MainLayout from './components/layout/MainLayout';

export default function App() {
  const { theme } = useAppStore();

  // 主题切换：监听系统偏好 + 手动设置
  useEffect(() => {
    const root = document.documentElement;

    if (theme === 'system') {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      const handler = (e: MediaQueryListEvent) => {
        root.classList.toggle('dark', e.matches);
      };
      root.classList.toggle('dark', mq.matches);
      mq.addEventListener('change', handler);
      return () => mq.removeEventListener('change', handler);
    }

    root.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  return <MainLayout />;
}

