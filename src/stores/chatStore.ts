/**
 * 聊天状态管理 (Zustand)
 * 管理：后端数据库中的对话/消息 + 前端运行时流式状态
 */
import { create } from 'zustand';

import {
  createConversationRecord,
  createMessageRecord,
  deleteConversationRecord,
  getChatState,
  updateConversationRecord,
  updateMessageRecord,
} from '@/services/api';
import { useAppStore } from '@/stores/appStore';
import type { Attachment, Conversation, Message, MessageMetadata } from '@/types';

export const DEFAULT_CONVERSATION_TITLE = '新对话';

function deriveMessages(
  activeConversationId: string | null,
  messagesByConversation: Record<string, Message[]>,
): Message[] {
  return activeConversationId ? (messagesByConversation[activeConversationId] ?? []) : [];
}

interface MessageUpdateOptions {
  persist?: boolean;
}

interface ChatState {
  conversations: Conversation[];
  activeConversationId: string | null;
  messagesByConversation: Record<string, Message[]>;
  messages: Message[];
  streamingByConversation: Record<string, boolean>;
  streamingContentByConversation: Record<string, string>;
  isStreaming: boolean;
  streamingContent: string;
  pendingAttachments: Attachment[];
  hydrated: boolean;

  bootstrap: () => Promise<void>;
  createConversation: (roleId?: string, surface?: 'chat' | 'agent') => Promise<string>;
  setActiveConversation: (id: string | null) => void;
  renameConversation: (id: string, title: string, isManual?: boolean) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;

  addMessage: (message: Omit<Message, 'id' | 'createdAt'>) => Promise<string>;
  updateMessage: (
    id: string,
    content: string,
    conversationId?: string,
    options?: MessageUpdateOptions,
  ) => Promise<void>;
  updateMessageMetadata: (
    id: string,
    metadata: Partial<MessageMetadata>,
    conversationId?: string,
    options?: MessageUpdateOptions,
  ) => Promise<void>;

  setStreaming: (streaming: boolean, conversationId?: string) => void;
  appendStreamContent: (chunk: string, conversationId?: string) => void;
  resetStreamContent: (conversationId?: string) => void;

  addAttachment: (attachment: Attachment) => void;
  removeAttachment: (id: string) => void;
  clearAttachments: () => void;
}

export const useChatStore = create<ChatState>()((set, get) => ({
  conversations: [],
  activeConversationId: null,
  messagesByConversation: {},
  messages: [],
  streamingByConversation: {},
  streamingContentByConversation: {},
  isStreaming: false,
  streamingContent: '',
  pendingAttachments: [],
  hydrated: false,

  bootstrap: async () => {
    const state = await getChatState();
    set((current) => {
      const nextActiveId = state.conversations.some((conversation) => conversation.id === current.activeConversationId)
        ? current.activeConversationId
        : (state.conversations[0]?.id ?? null);

      return {
        conversations: state.conversations,
        activeConversationId: nextActiveId,
        messagesByConversation: state.messages_by_conversation,
        messages: deriveMessages(nextActiveId, state.messages_by_conversation),
        hydrated: true,
      };
    });
  },

  createConversation: async (roleId, surface) => {
    const appState = useAppStore.getState();
    const resolvedSurface = surface ?? appState.activeSurface;
    const resolvedRoleId = roleId
      ?? (resolvedSurface === 'chat' ? appState.currentChatRoleId : appState.currentAgentRoleId);

    if (!resolvedRoleId) {
      throw new Error('当前 surface 没有可用角色，无法创建对话');
    }

    const conversation = await createConversationRecord(
      resolvedRoleId,
      resolvedSurface,
      DEFAULT_CONVERSATION_TITLE,
    );
    set((state) => ({
      conversations: [conversation, ...state.conversations.filter((item) => item.id !== conversation.id)],
      activeConversationId: conversation.id,
      messagesByConversation: { ...state.messagesByConversation, [conversation.id]: [] },
      messages: [],
    }));
    return conversation.id;
  },

  setActiveConversation: (id) => {
    const { messagesByConversation, streamingByConversation, streamingContentByConversation } = get();
    set({
      activeConversationId: id,
      messages: deriveMessages(id, messagesByConversation),
      isStreaming: id ? (streamingByConversation[id] ?? false) : false,
      streamingContent: id ? (streamingContentByConversation[id] ?? '') : '',
    });
  },

  renameConversation: async (id, title, isManual = true) => {
    const nextTitle = title.trim() || DEFAULT_CONVERSATION_TITLE;
    const updatedConversation = await updateConversationRecord(id, {
      title: nextTitle,
      is_title_customized: isManual,
    });

    set((state) => ({
      conversations: state.conversations.map((conversation) => (
        conversation.id === id ? updatedConversation : conversation
      )),
    }));
  },

  deleteConversation: async (id) => {
    await deleteConversationRecord(id);

    set((state) => {
      const filtered = state.conversations.filter((conversation) => conversation.id !== id);
      const { [id]: _removed, ...restMessages } = state.messagesByConversation;
      const nextActiveId = state.activeConversationId === id
        ? (filtered[0]?.id ?? null)
        : state.activeConversationId;

      return {
        conversations: filtered,
        messagesByConversation: restMessages,
        activeConversationId: nextActiveId,
        messages: deriveMessages(nextActiveId, restMessages),
      };
    });
  },

  addMessage: async (msg) => {
    const { activeConversationId } = get();
    const conversationId = msg.conversationId || activeConversationId;
    if (!conversationId) {
      throw new Error('当前没有可写入的对话');
    }

    const message = await createMessageRecord(conversationId, msg);
    set((state) => {
      const nextMessages = [...(state.messagesByConversation[conversationId] ?? []), message];
      const nextMessagesByConversation = {
        ...state.messagesByConversation,
        [conversationId]: nextMessages,
      };

      return {
        messagesByConversation: nextMessagesByConversation,
        messages: conversationId === state.activeConversationId
          ? nextMessages
          : state.messages,
        conversations: state.conversations.map((conversation) => (
          conversation.id === conversationId
            ? {
                ...conversation,
                lastMessage: message.content.slice(0, 50),
                updatedAt: message.createdAt,
              }
            : conversation
        )),
      };
    });
    return message.id;
  },

  updateMessage: async (id, content, conversationId, options) => {
    const convId = conversationId ?? get().activeConversationId;
    if (!convId) return;

    set((state) => {
      const targetMessages = state.messagesByConversation[convId] ?? [];
      const updatedMessages = targetMessages.map((message) => (
        message.id === id ? { ...message, content } : message
      ));

      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [convId]: updatedMessages,
        },
        messages: convId === state.activeConversationId ? updatedMessages : state.messages,
      };
    });

    if (options?.persist === false) return;
    await updateMessageRecord(id, { content });
  },

  updateMessageMetadata: async (id, metadata, conversationId, options) => {
    const convId = conversationId ?? get().activeConversationId;
    if (!convId) return;

    let nextMetadata: MessageMetadata | undefined;
    set((state) => {
      const targetMessages = state.messagesByConversation[convId] ?? [];
      const updatedMessages = targetMessages.map((message) => {
        if (message.id !== id) return message;
        nextMetadata = {
          ...message.metadata,
          ...metadata,
        };
        return {
          ...message,
          metadata: nextMetadata,
        };
      });

      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [convId]: updatedMessages,
        },
        messages: convId === state.activeConversationId ? updatedMessages : state.messages,
      };
    });

    if (options?.persist === false) return;
    await updateMessageRecord(id, { metadata: nextMetadata ?? metadata });
  },

  setStreaming: (streaming, conversationId) => {
    const convId = conversationId ?? get().activeConversationId ?? '';
    set((state) => {
      const nextStreamingByConversation = {
        ...state.streamingByConversation,
        [convId]: streaming,
      };
      return {
        streamingByConversation: nextStreamingByConversation,
        isStreaming: state.activeConversationId
          ? (nextStreamingByConversation[state.activeConversationId] ?? false)
          : false,
      };
    });
  },

  appendStreamContent: (chunk, conversationId) => {
    const convId = conversationId ?? get().activeConversationId ?? '';
    set((state) => {
      const previous = state.streamingContentByConversation[convId] ?? '';
      const nextStreamingContentByConversation = {
        ...state.streamingContentByConversation,
        [convId]: previous + chunk,
      };

      return {
        streamingContentByConversation: nextStreamingContentByConversation,
        streamingContent: convId === state.activeConversationId
          ? (nextStreamingContentByConversation[convId] ?? '')
          : state.streamingContent,
      };
    });
  },

  resetStreamContent: (conversationId) => {
    const convId = conversationId ?? get().activeConversationId ?? '';
    set((state) => {
      const nextStreamingContentByConversation = {
        ...state.streamingContentByConversation,
        [convId]: '',
      };
      return {
        streamingContentByConversation: nextStreamingContentByConversation,
        streamingContent: convId === state.activeConversationId ? '' : state.streamingContent,
      };
    });
  },

  addAttachment: (attachment) =>
    set((state) => ({ pendingAttachments: [...state.pendingAttachments, attachment] })),
  removeAttachment: (id) =>
    set((state) => ({ pendingAttachments: state.pendingAttachments.filter((attachment) => attachment.id !== id) })),
  clearAttachments: () => set({ pendingAttachments: [] }),
}));
