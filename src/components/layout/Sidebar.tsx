/**
 * 侧边栏组件
 * 包含：Logo、新建对话、对话列表、模式切换、设置入口
 */
import { useState, type KeyboardEvent } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useChatStore } from '@/stores/chatStore';
import { MODE_CONFIG, type AppMode } from '@/types';
import clsx from 'clsx';

export default function Sidebar() {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const {
    currentMode, setMode, sidebarCollapsed, toggleSidebar,
    activeView, setActiveView, toggleSettings,
  } = useAppStore();
  const {
    conversations, activeConversationId, createConversation,
    setActiveConversation, renameConversation, deleteConversation,
  } = useChatStore();

  const startRename = (id: string, title: string) => {
    setEditingId(id);
    setEditingTitle(title);
  };

  const cancelRename = () => {
    setEditingId(null);
    setEditingTitle('');
  };

  const submitRename = () => {
    if (!editingId) return;
    renameConversation(editingId, editingTitle);
    cancelRename();
  };

  /** 新建对话：同时切换回聊天视图 */
  const handleNewChat = () => {
    setActiveView('chat');
    const id = createConversation(currentMode);
    if (!sidebarCollapsed) {
      startRename(id, '新对话');
    }
  };

  /** 切换模式：同时切换回聊天视图 */
  const handleSetMode = (mode: AppMode) => {
    setMode(mode);
    setActiveView('chat');
  };

  /** 点击已有对话：切换回聊天视图 */
  const handleSelectConversation = (id: string) => {
    cancelRename();
    setActiveView('chat');
    setActiveConversation(id);
  };

  const handleRenameKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') submitRename();
    if (e.key === 'Escape') cancelRename();
  };

  /** Know-how 规则页开关 */
  const handleToggleKnowhow = () => {
    setActiveView(activeView === 'knowhow' ? 'chat' : 'knowhow');
  };

  return (
    <aside
      className={clsx(
        'flex flex-col h-full bg-surface-sidebar dark:bg-dark-sidebar border-r border-surface-divider dark:border-dark-divider transition-all duration-200',
        sidebarCollapsed ? 'w-16' : 'w-[220px]'
      )}
    >
      {/* Logo 区域 */}
      <div className="flex items-center gap-2 px-4 py-3 titlebar-no-drag">
        <span className="text-xl">🍒</span>
        {!sidebarCollapsed && (
          <span className="font-semibold text-sm truncate">Meeting Asst</span>
        )}
        <button
          onClick={toggleSidebar}
          className="ml-auto text-text-secondary hover:text-text-primary dark:hover:text-text-dark-primary transition-colors p-1 rounded"
          title={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {sidebarCollapsed ? '→' : '←'}
        </button>
      </div>

      {/* 新建对话按钮 */}
      <div className={clsx(sidebarCollapsed ? 'px-2 mb-2' : 'px-3 mb-2')}>
        <button
          onClick={handleNewChat}
          className={clsx(
            'w-full flex items-center rounded-button bg-primary text-white text-sm font-medium hover:bg-primary-600 transition-colors',
            sidebarCollapsed ? 'justify-center px-0 py-2.5' : 'gap-2 px-3 py-2'
          )}
          title="新建对话"
          aria-label="新建对话"
        >
          <span>+</span>
          {!sidebarCollapsed && <span>新建对话</span>}
        </button>
      </div>

      {/* 对话列表 */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2">
        {conversations.length === 0 && !sidebarCollapsed && (
          <p className="text-xs text-text-secondary text-center mt-8 px-2">
            点击上方按钮开始新对话
          </p>
        )}
        {conversations.map((conv) => (
          <div
            key={conv.id}
            className={clsx(
              'w-full rounded-lg mb-0.5 text-sm transition-colors group',
              conv.id === activeConversationId
                ? 'bg-primary-50 dark:bg-primary-900/30 text-primary'
                : 'hover:bg-gray-100 dark:hover:bg-gray-800 text-text-primary dark:text-text-dark-primary'
            )}
          >
            {sidebarCollapsed ? (
              <button
                onClick={() => handleSelectConversation(conv.id)}
                className="w-full text-left px-3 py-2"
              >
                <span>{MODE_CONFIG[conv.mode].icon}</span>
              </button>
            ) : (
              <div className="flex items-center gap-2 min-w-0 px-3 py-2">
                <span className="flex-shrink-0">{MODE_CONFIG[conv.mode].icon}</span>

                {editingId === conv.id ? (
                  <div className="flex items-center gap-1 flex-1 min-w-0">
                    <input
                      autoFocus
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onKeyDown={handleRenameKeyDown}
                      onClick={(e) => e.stopPropagation()}
                      onBlur={submitRename}
                      className="flex-1 min-w-0 px-2 py-1 text-sm rounded-md border border-primary/30 bg-white dark:bg-dark-card focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={submitRename}
                      className="text-xs text-primary hover:text-primary-600 transition-colors"
                      title="保存名称"
                    >
                      ✔
                    </button>
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={cancelRename}
                      className="text-xs text-text-secondary hover:text-text-primary transition-colors"
                      title="取消重命名"
                    >
                      ✕
                    </button>
                  </div>
                ) : (
                  <>
                    <button
                      onClick={() => handleSelectConversation(conv.id)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="truncate text-sm" title={conv.title}>{conv.title}</div>
                      {conv.lastMessage && (
                        <div className="truncate text-xs text-text-secondary mt-0.5">
                          {conv.lastMessage}
                        </div>
                      )}
                    </button>

                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                      <button
                        onClick={() => startRename(conv.id, conv.title)}
                        className="text-text-secondary hover:text-primary transition-colors"
                        title="重命名"
                      >
                        ✏️
                      </button>
                      <button
                        onClick={() => deleteConversation(conv.id)}
                        className="text-text-secondary hover:text-red-500 transition-colors"
                        title="删除对话"
                      >
                        ×
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 底部：模式切换 + 设置 */}
      <div className={clsx(
        'border-t border-surface-divider dark:border-dark-divider',
        sidebarCollapsed ? 'p-2 space-y-2' : 'p-3 space-y-2'
      )}>
        {sidebarCollapsed ? (
          <>
            <div className="flex flex-col gap-1">
              {(Object.keys(MODE_CONFIG) as AppMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => handleSetMode(mode)}
                  className={clsx(
                    'w-full flex items-center justify-center py-2 rounded-lg text-sm transition-colors',
                    currentMode === mode
                      ? 'bg-white dark:bg-dark-card shadow-light text-primary font-medium'
                      : 'text-text-secondary hover:bg-gray-100 dark:hover:bg-gray-800'
                  )}
                  title={MODE_CONFIG[mode].label}
                  aria-label={MODE_CONFIG[mode].label}
                >
                  <span>{MODE_CONFIG[mode].icon}</span>
                </button>
              ))}
            </div>

            <button
              onClick={handleToggleKnowhow}
              className={clsx(
                'w-full flex items-center justify-center py-2 rounded-lg text-sm transition-colors',
                activeView === 'knowhow'
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-text-secondary hover:bg-gray-100 dark:hover:bg-gray-800'
              )}
              title="Know-how 规则"
              aria-label="Know-how 规则"
            >
              <span>📚</span>
            </button>

            <button
              onClick={toggleSettings}
              className="w-full flex items-center justify-center py-2 rounded-lg text-sm text-text-secondary hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
              title="设置"
              aria-label="设置"
            >
              <span>⚙️</span>
            </button>
          </>
        ) : (
          <>
          {/* 模式切换 Segmented Control */}
          <div className="flex bg-gray-100 dark:bg-gray-800 rounded-button p-0.5">
            {(Object.keys(MODE_CONFIG) as AppMode[]).map((mode) => (
              <button
                key={mode}
                onClick={() => handleSetMode(mode)}
                className={clsx(
                  'flex-1 text-center py-1.5 rounded-md text-xs transition-all',
                  currentMode === mode
                    ? 'bg-white dark:bg-dark-card shadow-light font-medium'
                    : 'text-text-secondary hover:text-text-primary dark:hover:text-text-dark-primary'
                )}
                title={MODE_CONFIG[mode].label}
              >
                {MODE_CONFIG[mode].icon}
              </button>
            ))}
          </div>

          {/* Know-how 规则库管理入口 */}
          <button
            onClick={handleToggleKnowhow}
            className={clsx(
              'w-full flex items-center gap-2 px-3 py-1.5 rounded-button text-sm transition-colors',
              activeView === 'knowhow'
                ? 'bg-primary/10 text-primary font-medium'
                : 'text-text-secondary hover:bg-gray-100 dark:hover:bg-gray-800'
            )}
          >
            <span>📚</span>
            <span>Know-how 规则库</span>
          </button>

          {/* 设置按钮 */}
          <button
            onClick={toggleSettings}
            className="w-full flex items-center gap-2 px-3 py-1.5 rounded-button text-sm text-text-secondary hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <span>⚙️</span>
            <span>设置</span>
          </button>
          </>
        )}
      </div>
    </aside>
  );
}

