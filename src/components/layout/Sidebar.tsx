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
    const firstMatchingConversation = conversations.find((conversation) => conversation.mode === mode);
    if (firstMatchingConversation) {
      cancelRename();
      setActiveConversation(firstMatchingConversation.id);
    }
  };

  /** 点击已有对话：切换回聊天视图 */
  const handleSelectConversation = (conversationId: string) => {
    cancelRename();
    const conversation = conversations.find((item) => item.id === conversationId);
    if (conversation) {
      setMode(conversation.mode);
    }
    setActiveView('chat');
    setActiveConversation(conversationId);
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
        'flex h-full flex-col border-r border-surface-divider dark:border-dark-divider bg-[#F5F7FA] dark:bg-dark-sidebar transition-all duration-200',
        sidebarCollapsed ? 'w-[72px]' : 'w-[236px]'
      )}
    >
      {/* Logo 区域 */}
      <div className="flex items-center gap-2 border-b border-surface-divider dark:border-dark-divider px-3 py-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-md border border-surface-divider dark:border-dark-divider bg-white text-lg shadow-sm dark:bg-dark-card">🍒</span>
        {!sidebarCollapsed && (
          <div className="min-w-0">
            <span className="block truncate text-sm font-semibold">Meeting Asst</span>
            <span className="block truncate text-[11px] text-text-secondary">Web App</span>
          </div>
        )}
        <button
          onClick={toggleSidebar}
          className="win-icon-button ml-auto h-8 w-8"
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
            'win-button-primary w-full',
            sidebarCollapsed ? 'justify-center px-0 py-2.5' : 'justify-start gap-2 px-3 py-2.5'
          )}
          title="新建对话"
          aria-label="新建对话"
        >
          <span>+</span>
          {!sidebarCollapsed && <span>新建对话</span>}
        </button>
      </div>

      {/* 对话列表 */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-2 py-1.5">
        {conversations.length === 0 && !sidebarCollapsed && (
          <p className="text-xs text-text-secondary text-center mt-8 px-2">
            点击上方按钮开始新对话
          </p>
        )}
        {conversations.map((conv) => (
          <div
            key={conv.id}
            className={clsx(
              'group mb-1 w-full text-sm transition-colors',
              conv.id === activeConversationId
                ? 'rounded-md border border-primary/20 bg-white text-primary shadow-sm dark:bg-dark-card'
                : 'rounded-md border border-transparent text-text-primary dark:text-text-dark-primary hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card'
            )}
          >
            {sidebarCollapsed ? (
              <button
                onClick={() => handleSelectConversation(conv.id)}
                className="flex min-h-[44px] w-full items-center justify-center text-left"
              >
                <span>{MODE_CONFIG[conv.mode].icon}</span>
              </button>
            ) : (
              <div className="flex items-center gap-2 min-w-0 px-3 py-2.5">
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
                      className="flex-1 min-w-0 rounded-md border border-primary/30 bg-white px-2 py-1 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20 dark:bg-dark-card"
                    />
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={submitRename}
                      className="win-icon-button h-7 w-7 text-xs"
                      title="保存名称"
                    >
                      ✔
                    </button>
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={cancelRename}
                      className="win-icon-button h-7 w-7 text-xs"
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
                      <div className="truncate text-sm font-medium" title={conv.title}>{conv.title}</div>
                      {conv.lastMessage && (
                        <div className="mt-0.5 truncate text-[11px] text-text-secondary">
                          {conv.lastMessage}
                        </div>
                      )}
                    </button>

                    <div className="flex flex-shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      <button
                        onClick={() => startRename(conv.id, conv.title)}
                        className="win-icon-button h-7 w-7 text-xs"
                        title="重命名"
                      >
                        ✏️
                      </button>
                      <button
                        onClick={() => deleteConversation(conv.id)}
                        className="win-icon-button h-7 w-7 text-xs"
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
                  'flex min-h-[40px] w-full items-center justify-center rounded-md border text-sm transition-colors',
                    currentMode === mode
                    ? 'border-primary/20 bg-white font-medium text-primary shadow-sm dark:bg-dark-card'
                    : 'border-transparent text-text-secondary hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card'
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
                'flex min-h-[40px] w-full items-center justify-center rounded-md border text-sm transition-colors',
                activeView === 'knowhow'
                  ? 'border-primary/20 bg-white font-medium text-primary shadow-sm dark:bg-dark-card'
                  : 'border-transparent text-text-secondary hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card'
              )}
              title="Know-how 规则"
              aria-label="Know-how 规则"
            >
              <span>📚</span>
            </button>

            <button
              onClick={toggleSettings}
              className="flex min-h-[40px] w-full items-center justify-center rounded-md border border-transparent text-sm text-text-secondary transition-colors hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card"
              title="设置"
              aria-label="设置"
            >
              <span>⚙️</span>
            </button>
          </>
        ) : (
          <>
          <div className="space-y-1">
            {(Object.keys(MODE_CONFIG) as AppMode[]).map((mode) => (
              <button
                key={mode}
                onClick={() => handleSetMode(mode)}
                className={clsx(
                  'flex w-full items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors',
                  currentMode === mode
                    ? 'border-primary/20 bg-white font-medium text-primary shadow-sm dark:bg-dark-card'
                    : 'border-transparent text-text-secondary hover:border-surface-divider hover:bg-white hover:text-text-primary dark:hover:border-dark-divider dark:hover:bg-dark-card dark:hover:text-text-dark-primary'
                )}
                title={MODE_CONFIG[mode].label}
              >
                <span>{MODE_CONFIG[mode].icon}</span>
                <span>{MODE_CONFIG[mode].label}</span>
              </button>
            ))}
          </div>

          {/* Know-how 规则库管理入口 */}
          <button
            onClick={handleToggleKnowhow}
            className={clsx(
              'w-full flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors',
              activeView === 'knowhow'
                ? 'border-primary/20 bg-white font-medium text-primary shadow-sm dark:bg-dark-card'
                : 'border-transparent text-text-secondary hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card'
            )}
          >
            <span>📚</span>
            <span>Know-how 规则库</span>
          </button>

          {/* 设置按钮 */}
          <button
            onClick={toggleSettings}
            className="w-full flex items-center gap-2 rounded-md border border-transparent px-3 py-2 text-sm text-text-secondary transition-colors hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card"
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
