/**
 * 主布局组件
 * 三栏结构：侧边栏 + 聊天区 + 上下文面板
 */
import { useAppStore } from '@/stores/appStore';
import Sidebar from './Sidebar';
import ChatArea from '../chat/ChatArea';
import ContextPanel from './ContextPanel';
import KnowhowManager from '../knowhow/KnowhowManager';
import SettingsModal from '../common/SettingsModal';

export default function MainLayout() {
  const { contextPanelVisible, activeView } = useAppStore();

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-[#EFF2F6] dark:bg-dark">
      {/* 主内容区 */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* 侧边栏 */}
        <Sidebar />

        {/* 主区域 - 聊天区 或 Know-how 管理 */}
        <main className="flex-1 flex flex-col min-w-0 bg-surface dark:bg-dark">
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
