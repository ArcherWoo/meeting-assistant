/**
 * 聊天状态管理 (Zustand + persist)
 * 管理：对话列表、消息（按对话分组）、流式状态、附件
 * 对话和消息通过 localStorage 持久化
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { v4 as uuidv4 } from 'uuid';
import type { Conversation, Message, Attachment, AppMode } from '@/types';

export const DEFAULT_CONVERSATION_TITLE = '新对话';

const normalizeConversations = (conversations: Conversation[] = []) => (
  conversations.map((conversation) => (
    conversation.title === DEFAULT_CONVERSATION_TITLE && conversation.isTitleCustomized
      ? { ...conversation, isTitleCustomized: false }
      : conversation
  ))
);

interface ChatState {
  // 对话列表
  conversations: Conversation[];
  activeConversationId: string | null;

  // 按对话 ID 分组的消息（持久化）
  messagesByConversation: Record<string, Message[]>;

  // 当前对话的消息（派生，便于组件使用）
  messages: Message[];

  // 流式响应状态 — 按 conversationId 隔离（不持久化）
  streamingByConversation: Record<string, boolean>;
  streamingContentByConversation: Record<string, string>;

  // 当前活跃对话的派生便捷属性
  isStreaming: boolean;
  streamingContent: string;

  // 待发送的附件（不持久化）
  pendingAttachments: Attachment[];

  // Actions
  createConversation: (mode: AppMode) => string;
  setActiveConversation: (id: string) => void;
  renameConversation: (id: string, title: string, isManual?: boolean) => void;
  deleteConversation: (id: string) => void;

  addMessage: (message: Omit<Message, 'id' | 'createdAt'>) => string;
  updateMessage: (id: string, content: string, conversationId?: string) => void;

  setStreaming: (streaming: boolean, conversationId?: string) => void;
  appendStreamContent: (chunk: string, conversationId?: string) => void;
  resetStreamContent: (conversationId?: string) => void;

  addAttachment: (attachment: Attachment) => void;
  removeAttachment: (id: string) => void;
  clearAttachments: () => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      conversations: [],
      activeConversationId: null,
      messagesByConversation: {},
      messages: [],
      streamingByConversation: {},
      streamingContentByConversation: {},
      isStreaming: false,
      streamingContent: '',
      pendingAttachments: [],

      createConversation: (mode) => {
        const id = uuidv4();
        const conversation: Conversation = {
          id,
          workspaceId: 'default',
          title: DEFAULT_CONVERSATION_TITLE,
          mode,
          isPinned: false,
          isTitleCustomized: false,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        };
        set((state) => ({
          conversations: [conversation, ...state.conversations],
          activeConversationId: id,
          messagesByConversation: { ...state.messagesByConversation, [id]: [] },
          messages: [], // 新对话，消息为空
        }));
        return id;
      },

      setActiveConversation: (id) => {
        const { messagesByConversation, streamingByConversation, streamingContentByConversation } = get();
        set({
          activeConversationId: id,
          messages: messagesByConversation[id] ?? [],
          // 切换对话时同步该对话的流式状态
          isStreaming: streamingByConversation[id] ?? false,
          streamingContent: streamingContentByConversation[id] ?? '',
        });
      },

      renameConversation: (id, title, isManual = true) => {
        const nextTitle = title.trim() || DEFAULT_CONVERSATION_TITLE;
        set((state) => ({
          conversations: state.conversations.map((conversation) =>
            conversation.id === id
              ? (conversation.title === nextTitle
                  ? conversation
                  : {
                      ...conversation,
                      title: nextTitle,
                      updatedAt: new Date().toISOString(),
                      ...(isManual ? { isTitleCustomized: true } : {}),
                    })
              : conversation
          ),
        }));
      },

      deleteConversation: (id) => {
        set((state) => {
          const filtered = state.conversations.filter((c) => c.id !== id);
          const { [id]: _removed, ...restMessages } = state.messagesByConversation;
          const newActiveId = state.activeConversationId === id
            ? (filtered[0]?.id ?? null)
            : state.activeConversationId;
          return {
            conversations: filtered,
            messagesByConversation: restMessages,
            activeConversationId: newActiveId,
            messages: newActiveId ? (restMessages[newActiveId] ?? []) : [],
          };
        });
      },

      addMessage: (msg) => {
        const id = uuidv4();
        const message: Message = {
          ...msg,
          id,
          createdAt: new Date().toISOString(),
        };
        const { activeConversationId } = get();
        const convId = msg.conversationId || activeConversationId;

        set((state) => {
          const convMessages = [...(state.messagesByConversation[convId ?? ''] ?? []), message];
          const updatedMap = { ...state.messagesByConversation, ...(convId ? { [convId]: convMessages } : {}) };
          // 如果消息属于当前活跃对话，也更新 messages
          const updatedMessages = convId === state.activeConversationId
            ? convMessages
            : state.messages;

          return {
            messagesByConversation: updatedMap,
            messages: updatedMessages,
            conversations: state.conversations.map((c) =>
              c.id === convId
                ? { ...c, lastMessage: msg.content.slice(0, 50), updatedAt: new Date().toISOString() }
                : c
            ),
          };
        });
        return id;
      },

      updateMessage: (id, content, conversationId) => {
        const { activeConversationId } = get();
        // 优先使用调用方明确传入的 conversationId，避免多对话并发时更新错对话
        const convId = conversationId ?? activeConversationId;
        set((state) => {
          const targetMessages = state.messagesByConversation[convId ?? ''] ?? state.messages;
          const updatedMessages = targetMessages.map((m) => (m.id === id ? { ...m, content } : m));
          const updatedMap = convId
            ? { ...state.messagesByConversation, [convId]: updatedMessages }
            : state.messagesByConversation;
          return {
            // 只有当目标对话是当前活跃对话时才更新 messages 派生字段
            messages: convId === state.activeConversationId ? updatedMessages : state.messages,
            messagesByConversation: updatedMap,
          };
        });
      },

      setStreaming: (streaming, conversationId) => {
        const { activeConversationId } = get();
        const convId = conversationId ?? activeConversationId ?? '';
        set((state) => {
          const updated = { ...state.streamingByConversation, [convId]: streaming };
          return {
            streamingByConversation: updated,
            isStreaming: updated[state.activeConversationId ?? ''] ?? false,
          };
        });
      },
      appendStreamContent: (chunk, conversationId) => {
        const { activeConversationId } = get();
        const convId = conversationId ?? activeConversationId ?? '';
        set((state) => {
          const prev = state.streamingContentByConversation[convId] ?? '';
          const updated = { ...state.streamingContentByConversation, [convId]: prev + chunk };
          return {
            streamingContentByConversation: updated,
            streamingContent: convId === state.activeConversationId ? updated[convId] ?? '' : state.streamingContent,
          };
        });
      },
      resetStreamContent: (conversationId) => {
        const { activeConversationId } = get();
        const convId = conversationId ?? activeConversationId ?? '';
        set((state) => {
          const updated = { ...state.streamingContentByConversation, [convId]: '' };
          return {
            streamingContentByConversation: updated,
            streamingContent: convId === state.activeConversationId ? '' : state.streamingContent,
          };
        });
      },

      addAttachment: (attachment) =>
        set((state) => ({ pendingAttachments: [...state.pendingAttachments, attachment] })),
      removeAttachment: (id) =>
        set((state) => ({ pendingAttachments: state.pendingAttachments.filter((a) => a.id !== id) })),
      clearAttachments: () => set({ pendingAttachments: [] }),
    }),
    {
      name: 'meeting-assistant-chat',
      version: 1,
      // 仅持久化对话列表、消息和活跃对话ID，不持久化运行时状态
      partialize: (state) => ({
        conversations: state.conversations,
        activeConversationId: state.activeConversationId,
        messagesByConversation: state.messagesByConversation,
      }),
      // 恢复时重建 messages 派生字段
      merge: (persistedState, currentState) => {
        const persisted = (persistedState ?? {}) as Partial<ChatState>;
        const activeId = persisted.activeConversationId ?? null;
        const msgMap = persisted.messagesByConversation ?? {};
        const conversations = normalizeConversations(persisted.conversations ?? []);
        return {
          ...currentState,
          ...persisted,
          conversations,
          messages: activeId ? (msgMap[activeId] ?? []) : [],
        };
      },
    }
  )
);

