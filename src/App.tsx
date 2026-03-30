/**
 * 应用根组件
 * 负责：主题管理、布局渲染、后端连接状态监控
 */
import { useEffect } from 'react';
import { useAppStore } from './stores/appStore';
import { useAuthStore } from './stores/authStore';
import MainLayout from './components/layout/MainLayout';
import LoginPage from './components/auth/LoginPage';

/** 将 #rrggbb 转为 "r g b" 空格分隔格式，供 CSS rgb() 使用 */
function hexToRgbParts(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `${r} ${g} ${b}`;
}

/** 按比例压暗颜色（用于悬停态 primary-600） */
function darkenHexParts(hex: string, factor = 0.82): string {
  const r = Math.round(parseInt(hex.slice(1, 3), 16) * factor);
  const g = Math.round(parseInt(hex.slice(3, 5), 16) * factor);
  const b = Math.round(parseInt(hex.slice(5, 7), 16) * factor);
  return `${r} ${g} ${b}`;
}

export default function App() {
  const { theme, accentColor } = useAppStore();
  const { user, initialized, init } = useAuthStore();

  // 初始化认证状态
  useEffect(() => {
    void init();
  }, [init]);

  // 主题色 CSS 变量注入
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--color-primary-rgb', hexToRgbParts(accentColor));
    root.style.setProperty('--color-primary-dark-rgb', darkenHexParts(accentColor));
  }, [accentColor]);

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

  // 未初始化时显示加载状态
  if (!initialized) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-sidebar dark:bg-dark">
        <span className="text-text-secondary">Loading...</span>
      </div>
    );
  }

  // 未登录时显示登录页
  if (!user) {
    return <LoginPage />;
  }

  return <MainLayout />;
}
