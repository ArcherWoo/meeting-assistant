/**
 * 主布局组件
 * 三栏结构：侧边栏 + 聊天区 + 上下文面板
 * macOS 标题栏拖拽区域在顶部
 */
import { useAppStore } from '@/stores/appStore';
import Sidebar from './Sidebar';
import ChatArea from '../chat/ChatArea';
import ContextPanel from './ContextPanel';
import KnowhowManager from '../knowhow/KnowhowManager';
import SettingsModal from '../common/SettingsModal';

export default function MainLayout() {
  const { contextPanelVisible, backend, activeView } = useAppStore();

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* macOS 标题栏拖拽区域 */}
      <div className="titlebar-drag h-8 flex-shrink-0 flex items-center justify-center bg-surface-sidebar dark:bg-dark-sidebar">
        {!backend.connected && (
          <span className="titlebar-no-drag text-xs text-text-secondary flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
            后端未连接
          </span>
        )}
      </div>

      {/* 主内容区 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 侧边栏 */}
        <Sidebar />

        {/* 主区域 - 聊天区 或 Know-how 管理 */}
        <main className="flex-1 flex flex-col min-w-0">
          {activeView === 'knowhow' ? <KnowhowManager /> : <ChatArea />}
        </main>

        {/* 右侧上下文面板 */}
        {contextPanelVisible && <ContextPanel />}
      </div>

      {/* 设置 Modal（全局挂载，z-50 覆盖所有层） */}
      <SettingsModal />
    </div>
  );
}

