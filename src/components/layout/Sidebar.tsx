/**
 * 侧边栏组件
 * 包含：Logo、新建对话、对话列表、角色切换、设置入口
 */
import { useState, useRef, useCallback, useEffect, type KeyboardEvent } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useAuthStore } from '@/stores/authStore';
import { useChatStore } from '@/stores/chatStore';
import clsx from 'clsx';
import { filterRolesBySurface, getPreferredRoleForSurface } from '@/utils/roles';

const SIDEBAR_COLLAPSED_WIDTH = 72;
const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 450;
const SIDEBAR_DEFAULT_WIDTH = 236;

export default function Sidebar() {
  const { user, logout, isAdmin } = useAuthStore();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [expandedWidth, setExpandedWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartX = useRef(0);
  const dragStartWidth = useRef(SIDEBAR_DEFAULT_WIDTH);
  const {
    roles, activeSurface, setActiveSurface,
    currentChatRoleId, currentAgentRoleId,
    setCurrentChatRoleId, setCurrentAgentRoleId,
    rolesLoaded,
    sidebarCollapsed, toggleSidebar,
    activeView, setActiveView, toggleSettings,
  } = useAppStore();

  const {
    conversations, activeConversationId, createConversation,
    setActiveConversation, renameConversation, deleteConversation,
  } = useChatStore();

  /** 根据 role id 查找图标，找不到时回退到 💬 */
  const getRoleIcon = (roleId: string) =>
    roles.find((r) => r.id === roleId)?.icon ?? '💬';
  const currentSurfaceRoleId = activeSurface === 'chat' ? currentChatRoleId : currentAgentRoleId;
  const surfaceRoles = filterRolesBySurface(roles, activeSurface);

  useEffect(() => {
    const preferredRole = getPreferredRoleForSurface(roles, activeSurface, currentSurfaceRoleId);
    if (!preferredRole) {
      if (activeSurface === 'agent') {
        setActiveSurface('chat');
      }
      return;
    }

    if (activeSurface === 'chat' && preferredRole.id !== currentChatRoleId) {
      setCurrentChatRoleId(preferredRole.id);
    }
    if (activeSurface === 'agent' && preferredRole.id !== currentAgentRoleId) {
      setCurrentAgentRoleId(preferredRole.id);
    }
  }, [activeSurface, currentAgentRoleId, currentChatRoleId, currentSurfaceRoleId, roles, setActiveSurface, setCurrentAgentRoleId, setCurrentChatRoleId]);

  const startRename = (id: string, title: string) => {
    setEditingId(id);
    setEditingTitle(title);
  };

  const cancelRename = () => {
    setEditingId(null);
    setEditingTitle('');
  };

  const submitRename = async () => {
    if (!editingId) return;
    try {
      await renameConversation(editingId, editingTitle);
      cancelRename();
    } catch (error) {
      alert((error as Error).message || '重命名失败');
    }
  };

  /** 新建对话：保持当前 surface / role，不强制切回 chat */
  const handleNewChat = async () => {
    setActiveView('chat');
    const preferredRole = getPreferredRoleForSurface(roles, activeSurface, currentSurfaceRoleId);
    if (!preferredRole) {
      alert(`当前 ${activeSurface} 模式下没有可用角色`);
      return;
    }

    try {
      const id = await createConversation(preferredRole.id, activeSurface);
      if (!sidebarCollapsed) {
        startRename(id, '新对话');
      }
    } catch (error) {
      alert((error as Error).message || '创建对话失败');
    }
  };

  /** 切换角色：同时切换回聊天视图 */
  const handleSetRole = (roleId: string) => {
    setActiveView('chat');
    if (activeSurface === 'chat') {
      setCurrentChatRoleId(roleId);
    } else {
      setCurrentAgentRoleId(roleId);
    }
    const firstMatch = conversations.find((c) => c.surface === activeSurface && c.roleId === roleId);
    if (firstMatch) {
      cancelRename();
      setActiveConversation(firstMatch.id);
    }
  };

  /** 点击已有对话：切换回聊天视图 */
  const handleSelectConversation = (conversationId: string) => {
    cancelRename();
    const conversation = conversations.find((item) => item.id === conversationId);
    if (conversation) {
      setActiveSurface(conversation.surface);
      if (conversation.surface === 'chat') {
        setCurrentChatRoleId(conversation.roleId);
      } else {
        setCurrentAgentRoleId(conversation.roleId);
      }
    }
    setActiveView('chat');
    setActiveConversation(conversationId);
  };

  const handleSelectSurface = (surface: 'chat' | 'agent') => {
    cancelRename();
    setActiveView('chat');
    const preferredRole = getPreferredRoleForSurface(
      roles,
      surface,
      surface === 'chat' ? currentChatRoleId : currentAgentRoleId,
    );
    if (!preferredRole) {
      return;
    }
    if (surface === 'chat') {
      setCurrentChatRoleId(preferredRole.id);
    } else {
      setCurrentAgentRoleId(preferredRole.id);
    }
    setActiveSurface(surface);
    const targetRoleId = preferredRole.id;
    const firstMatch = conversations.find((c) => c.surface === surface && c.roleId === targetRoleId);
    setActiveConversation(firstMatch?.id ?? null);
  };

  const handleRenameKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') void submitRename();
    if (e.key === 'Escape') cancelRename();
  };

  /** Know-how 规则页开关 */
  const handleToggleKnowhow = () => {
    setActiveView(activeView === 'knowhow' ? 'chat' : 'knowhow');
  };

  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    if (sidebarCollapsed) return;
    e.preventDefault();
    dragStartX.current = e.clientX;
    dragStartWidth.current = expandedWidth;
    setIsDragging(true);
  }, [sidebarCollapsed, expandedWidth]);

  useEffect(() => {
    if (!isDragging) return;
    const onMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - dragStartX.current;
      const newWidth = Math.min(SIDEBAR_MAX_WIDTH, Math.max(SIDEBAR_MIN_WIDTH, dragStartWidth.current + delta));
      setExpandedWidth(newWidth);
    };
    const onMouseUp = () => setIsDragging(false);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [isDragging]);

  const currentWidth = sidebarCollapsed ? SIDEBAR_COLLAPSED_WIDTH : expandedWidth;

  return (
    <aside
      className={clsx(
        'relative flex h-full flex-col border-r border-surface-divider dark:border-dark-divider bg-surface-sidebar dark:bg-dark-sidebar',
        !isDragging && 'transition-[width] duration-200'
      )}
      style={{ width: currentWidth, minWidth: currentWidth, maxWidth: currentWidth }}
    >
      {/* Logo 区域 */}
      <div className="flex items-center gap-2 border-b border-surface-divider dark:border-dark-divider px-3 py-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-md border border-surface-divider dark:border-dark-divider bg-white text-lg shadow-sm dark:bg-dark-card">🍒</span>
        {!sidebarCollapsed && (
          <div className="min-w-0">
            <span className="block truncate text-sm font-semibold">CPSC AI 中台--智枢</span>
            <span className="block truncate text-[11px] text-text-secondary">Powered By CPSCI</span>
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
          onClick={() => void handleNewChat()}
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
        {conversations.filter((conv) => conv.surface === activeSurface).length === 0 && !sidebarCollapsed && (
          <p className="text-xs text-text-secondary text-center mt-8 px-2">
            点击上方按钮开始新对话
          </p>
        )}
        {conversations.filter((conv) => conv.surface === activeSurface).map((conv) => (
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
                <span>{getRoleIcon(conv.roleId)}</span>
              </button>
            ) : (
              <div className="flex items-center gap-2 min-w-0 px-3 py-2.5">
                <span className="flex-shrink-0">{getRoleIcon(conv.roleId)}</span>

                {editingId === conv.id ? (
                  <div className="flex items-center gap-1 flex-1 min-w-0">
                    <input
                      autoFocus
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onKeyDown={handleRenameKeyDown}
                      onClick={(e) => e.stopPropagation()}
                      onBlur={() => void submitRename()}
                      className="flex-1 min-w-0 rounded-md border border-primary/30 bg-white px-2 py-1 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20 dark:bg-dark-card"
                    />
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => void submitRename()}
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
                        onClick={() => {
                          void deleteConversation(conv.id).catch((error) => {
                            alert((error as Error).message || '删除对话失败');
                          });
                        }}
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

      {/* 底部：角色切换 + 设置 */}
      <div className={clsx(
        'border-t border-surface-divider dark:border-dark-divider',
        sidebarCollapsed ? 'p-2 space-y-2' : 'p-3 space-y-2'
      )}>
        {sidebarCollapsed ? (
          <>
            <div className="flex flex-col gap-1">
              {[
                { key: 'chat', label: '聊天', icon: '💬' },
                { key: 'agent', label: 'Agent', icon: '🤖' },
              ].map((item) => (
                <button
                  key={item.key}
                  onClick={() => handleSelectSurface(item.key as 'chat' | 'agent')}
                  className={clsx(
                    'flex min-h-[40px] w-full items-center justify-center rounded-md border text-sm transition-colors',
                    activeSurface === item.key
                      ? 'border-primary/20 bg-white font-medium text-primary shadow-sm dark:bg-dark-card'
                      : 'border-transparent text-text-secondary hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card'
                  )}
                  title={item.label}
                  aria-label={item.label}
                >
                  <span>{item.icon}</span>
                </button>
              ))}
              {!rolesLoaded && roles.length === 0 ? (
                [0, 1, 2].map((i) => (
                  <div key={i} className="min-h-[40px] w-full rounded-md border border-transparent bg-surface-divider/40 animate-pulse dark:bg-dark-divider/40" />
                ))
              ) : (
                surfaceRoles.map((role) => (
                  <button
                    key={role.id}
                    onClick={() => handleSetRole(role.id)}
                    className={clsx(
                    'flex min-h-[40px] w-full items-center justify-center rounded-md border text-sm transition-colors',
                      currentSurfaceRoleId === role.id
                      ? 'border-primary/20 bg-white font-medium text-primary shadow-sm dark:bg-dark-card'
                      : 'border-transparent text-text-secondary hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card'
                    )}
                    title={role.name}
                    aria-label={role.name}
                  >
                    <span>{role.icon}</span>
                  </button>
                ))
              )}
            </div>

            <hr className="border-t border-dashed border-gray-200 dark:border-gray-700 my-1" />

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

            {isAdmin() && (
              <button
                onClick={() => setActiveView(activeView === 'admin' ? 'chat' : 'admin')}
                className="flex min-h-[40px] w-full items-center justify-center rounded-md border border-transparent text-sm text-text-secondary transition-colors hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card"
                title="用户管理"
                aria-label="用户管理"
              >
                <span>👥</span>
              </button>
            )}

            <button
              onClick={logout}
              className="flex min-h-[40px] w-full items-center justify-center rounded-md border border-transparent text-sm text-text-secondary transition-colors hover:border-surface-divider hover:text-red-500"
              title="登出"
              aria-label="登出"
            >
              <span>🚪</span>
            </button>
          </>
        ) : (
          <>
          <div className="flex gap-1 rounded-md border border-surface-divider bg-surface p-1 dark:border-dark-divider dark:bg-dark-sidebar">
            {[
              { key: 'chat', label: '聊天', icon: '💬' },
              { key: 'agent', label: 'Agent', icon: '🤖' },
            ].map((item) => (
              <button
                key={item.key}
                onClick={() => handleSelectSurface(item.key as 'chat' | 'agent')}
                className={clsx(
                  'flex-1 rounded-md px-3 py-2 text-sm transition-colors',
                  activeSurface === item.key
                    ? 'bg-white text-primary shadow-sm dark:bg-dark-card'
                    : 'text-text-secondary hover:bg-white hover:text-text-primary dark:hover:bg-dark-card dark:hover:text-text-dark-primary'
                )}
              >
                <span className="mr-1">{item.icon}</span>
                <span>{item.label}</span>
              </button>
            ))}
          </div>
          <div className="space-y-1">
            {!rolesLoaded && roles.length === 0 ? (
              [0, 1, 2].map((i) => (
                <div key={i} className="h-9 w-full rounded-md border border-transparent bg-surface-divider/40 animate-pulse dark:bg-dark-divider/40" />
              ))
            ) : (
              surfaceRoles.map((role) => (
                <button
                  key={role.id}
                  onClick={() => handleSetRole(role.id)}
                  className={clsx(
                    'flex w-full items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors',
                    currentSurfaceRoleId === role.id
                      ? 'border-primary/20 bg-white font-medium text-primary shadow-sm dark:bg-dark-card'
                      : 'border-transparent text-text-secondary hover:border-surface-divider hover:bg-white hover:text-text-primary dark:hover:border-dark-divider dark:hover:bg-dark-card dark:hover:text-text-dark-primary'
                  )}
                  title={role.name}
                >
                  <span>{role.icon}</span>
                  <span>{role.name}</span>
                </button>
              ))
            )}
          </div>

          <hr className="border-t border-dashed border-gray-200 dark:border-gray-700 my-1" />

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

          {/* 管理员入口 */}
          {isAdmin() && (
            <button
              onClick={() => setActiveView(activeView === 'admin' ? 'chat' : 'admin')}
              className="w-full flex items-center gap-2 rounded-md border border-transparent px-3 py-2 text-sm text-text-secondary transition-colors hover:border-surface-divider hover:bg-white dark:hover:border-dark-divider dark:hover:bg-dark-card"
            >
              <span>👥</span>
              <span>用户管理</span>
            </button>
          )}

          {/* 用户信息 & 登出 */}
          <div className="flex items-center gap-2 rounded-md border border-surface-divider bg-surface px-3 py-2 dark:border-dark-divider dark:bg-dark-sidebar">
            <span className="flex-1 truncate text-xs text-text-secondary" title={user?.username}>
              {user?.display_name ?? user?.username}
            </span>
            <button
              onClick={logout}
              className="text-xs text-text-secondary hover:text-red-500 transition-colors"
              title="登出"
            >
              登出
            </button>
          </div>
          </>
        )}
      </div>

      {/* 可拖拽调宽手柄 */}
      {!sidebarCollapsed && (
        <div
          onMouseDown={handleResizeMouseDown}
          className={clsx(
            'absolute right-0 top-0 h-full w-1 cursor-col-resize group z-10',
            'hover:bg-primary/40 transition-colors',
            isDragging && 'bg-primary/60'
          )}
          title="拖拽调整宽度"
        />
      )}
    </aside>
  );
}
