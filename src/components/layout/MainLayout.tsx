/**
 * 主布局组件
 * 三栏结构：侧边栏 + 聊天区 + 上下文面板
 */
import { lazy, Suspense, useState, useRef, useEffect, useCallback } from 'react';
import clsx from 'clsx';
import { useAppStore } from '@/stores/appStore';
import ConfirmDialogHost from '../common/ConfirmDialogHost';
import ToastViewport from '../common/ToastViewport';

const Sidebar = lazy(() => import('./Sidebar'));
const ChatArea = lazy(() => import('../chat/ChatArea'));
const ContextPanel = lazy(() => import('./ContextPanel'));
const KnowhowManager = lazy(() => import('../knowhow/KnowhowManager'));
const AdminPanel = lazy(() => import('../auth/AdminPanel'));
const SettingsModal = lazy(() => import('../common/SettingsModal'));

const CONTEXT_MIN_WIDTH = 220;
const CONTEXT_MAX_WIDTH = 560;
const CONTEXT_DEFAULT_WIDTH = 300;

export default function MainLayout() {
  const { contextPanelVisible, activeView } = useAppStore();
  const [contextWidth, setContextWidth] = useState(CONTEXT_DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(CONTEXT_DEFAULT_WIDTH);

  const handleDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragStartX.current = e.clientX;
    dragStartWidth.current = contextWidth;
    setIsDragging(true);
  }, [contextWidth]);

  useEffect(() => {
    if (!isDragging) return;
    const onMouseMove = (e: MouseEvent) => {
      // 向左拖 → 面板变宽（delta 为负），向右拖 → 面板变窄
      const delta = dragStartX.current - e.clientX;
      const newWidth = Math.min(CONTEXT_MAX_WIDTH, Math.max(CONTEXT_MIN_WIDTH, dragStartWidth.current + delta));
      setContextWidth(newWidth);
    };
    const onMouseUp = () => setIsDragging(false);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [isDragging]);

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-surface-sidebar dark:bg-dark">
      {/* 主内容区 */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* 侧边栏 */}
        <Suspense fallback={<SidebarFallback />}>
          <Sidebar />
        </Suspense>

        {/* 主区域 - 聊天区 或 Know-how 管理 */}
        <main className="flex-1 flex flex-col min-w-0 bg-surface dark:bg-dark">
          <Suspense fallback={<PanelFallback />}>
            {activeView === 'admin' ? <AdminPanel /> : activeView === 'knowhow' ? <KnowhowManager /> : <ChatArea />}
          </Suspense>
        </main>

        {/* 右侧面板分隔拖拽手柄 */}
        {contextPanelVisible && (
          <div
            onMouseDown={handleDividerMouseDown}
            className={clsx(
              'w-1 flex-shrink-0 cursor-col-resize hover:bg-primary/40 transition-colors z-10',
              isDragging && 'bg-primary/60'
            )}
            title="拖拽调整面板宽度"
          />
        )}

        {/* 右侧上下文面板 */}
        {contextPanelVisible && (
          <Suspense fallback={<SidePanelFallback width={contextWidth} />}>
            <ContextPanel width={contextWidth} />
          </Suspense>
        )}
      </div>

      {/* 设置 Modal（全局挂载，z-50 覆盖所有层） */}
      <Suspense fallback={null}>
        <SettingsModal />
      </Suspense>
      <ConfirmDialogHost />
      <ToastViewport />
    </div>
  );
}

function PanelFallback() {
  return (
    <div className="flex h-full items-center justify-center bg-surface dark:bg-dark">
      <div className="text-sm text-text-secondary dark:text-text-dark-secondary">
        正在加载页面...
      </div>
    </div>
  );
}

function SidePanelFallback({ width }: { width: number }) {
  return (
    <aside
      className="flex-shrink-0 border-l border-surface-divider dark:border-dark-divider bg-[#F7F8FA] dark:bg-dark"
      style={{ width, minWidth: width, maxWidth: width }}
    />
  );
}

function SidebarFallback() {
  return (
    <aside className="h-full w-[72px] flex-shrink-0 border-r border-surface-divider bg-surface-sidebar dark:border-dark-divider dark:bg-dark-sidebar" />
  );
}
