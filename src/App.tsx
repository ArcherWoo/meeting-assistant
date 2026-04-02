/**
 * 应用根组件
 * 负责：主题管理、布局渲染、后端连接状态监控
 */
import { lazy, Suspense, useEffect, useRef } from 'react';
import { useAppStore } from './stores/appStore';
import { useAuthStore } from './stores/authStore';
import { initBackend } from './bootstrap/backend';

const MainLayout = lazy(() => import('./components/layout/MainLayout'));
const LoginPage = lazy(() => import('./components/auth/LoginPage'));

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
  const lastBackendInitKeyRef = useRef<string | null>(null);

  // 初始化认证状态
  useEffect(() => {
    void init();
  }, [init]);

  // 认证状态完成后初始化后端；登录后会自动重新拉取角色/会话数据。
  useEffect(() => {
    if (!initialized) {
      return;
    }

    const initKey = user?.id ? `user:${user.id}` : 'guest';
    if (lastBackendInitKeyRef.current === initKey) {
      return;
    }
    lastBackendInitKeyRef.current = initKey;

    void initBackend({ loadProtectedData: Boolean(user) });
  }, [initialized, user?.id]);

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
    return (
      <Suspense fallback={<AppShellFallback />}>
        <LoginPage />
      </Suspense>
    );
  }

  return (
    <Suspense fallback={<AppShellFallback />}>
      <MainLayout />
    </Suspense>
  );
}

function AppShellFallback() {
  return (
    <div className="flex h-screen items-center justify-center bg-surface-sidebar dark:bg-dark">
      <span className="text-text-secondary">Loading...</span>
    </div>
  );
}
