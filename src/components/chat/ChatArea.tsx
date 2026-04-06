/**
 * 聊天区域组件
 * 包含：顶部工具栏、消息列表（自动滚动）、底部输入区
 * Agent 模式下触发 Skill 匹配 → 执行工作流
 */
import { lazy, Suspense, useState, useRef, useEffect, useCallback, useMemo, type ChangeEvent } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useChatStore, DEFAULT_CONVERSATION_TITLE } from '@/stores/chatStore';
import { streamChat, extractFilesText, generateAutoTitle } from '@/services/api';
import { type Attachment, type ChatStatusEvent, type GenerationPreview, type LLMConfig, type Message, type SkillSuggestionEvent } from '@/types';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import InlineNotice from '@/components/common/InlineNotice';

const AgentExecutionPanel = lazy(() => import('../agent/AgentExecutionPanel'));

interface AgentExecutionRequest {
  query: string;
  conversationId: string;
}

const STOPPED_MESSAGE_FALLBACK = '（已停止生成）';
const ERROR_MESSAGE_FALLBACK = '本次生成失败，请重试。';
const MAX_ATTACHMENT_CHARS_PER_FILE = 18_000;
const MAX_ATTACHMENT_CHARS_TOTAL = 36_000;
const MIN_ATTACHMENT_CHARS_PER_FILE = 1_200;

function compactAttachmentText(text: string, maxChars: number): { text: string; truncated: boolean } {
  const normalized = text.trim();
  if (!normalized || normalized.length <= maxChars) {
    return { text: normalized, truncated: false };
  }

  if (maxChars <= 800) {
    return { text: normalized.slice(0, Math.max(maxChars, 0)), truncated: true };
  }

  const headLength = Math.max(300, Math.floor(maxChars * 0.42));
  const middleLength = Math.max(180, Math.floor(maxChars * 0.18));
  const tailLength = Math.max(260, maxChars - headLength - middleLength);
  const middleStart = Math.max(0, Math.floor((normalized.length - middleLength) / 2));

  return {
    text: [
      normalized.slice(0, headLength).trim(),
      '[中段节选]',
      normalized.slice(middleStart, middleStart + middleLength).trim(),
      '[末段节选]',
      normalized.slice(-tailLength).trim(),
    ].filter(Boolean).join('\n\n'),
    truncated: true,
  };
}

function buildGenerationPreview(content: string, attachments?: Attachment[]): GenerationPreview {
  if (attachments?.length) {
    return {
      title: attachments.length > 1 ? '我先快速梳理这几份材料' : '我先快速梳理这份材料',
      steps: [
        '浏览附件结构，抓取主题、结论和关键数据',
        '提炼风险点、异常点和需要重点关注的部分',
        '先给你总结，再展开细节和建议动作',
      ],
    };
  }

  const compact = content.trim();
  if (compact.length <= 24) {
    return {
      title: '我先理解你的问题',
      steps: [
        '确认你的核心意图',
        '必要时补充上下文检索',
        '直接给你一个尽快可用的回答',
      ],
    };
  }

  return {
    title: '我先整理你的需求',
    steps: [
      '提炼问题重点',
      '结合上下文组织回答',
      '先给结论，再补细节说明',
    ],
  };
}

function buildAttachmentContext(attachments?: Attachment[]): string {
  if (!attachments?.length) return '';

  let remainingBudget = MAX_ATTACHMENT_CHARS_TOTAL;
  return attachments.map((attachment, index) => {
    const originalText = attachment.text ?? '';
    const remainingFiles = Math.max(attachments.length - index, 1);
    const budget = Math.min(
      MAX_ATTACHMENT_CHARS_PER_FILE,
      Math.max(MIN_ATTACHMENT_CHARS_PER_FILE, Math.floor(remainingBudget / remainingFiles)),
    );
    const compacted = compactAttachmentText(originalText, budget);
    remainingBudget = Math.max(0, remainingBudget - compacted.text.length);

    const extraNote = compacted.truncated
      ? `\n\n[为提升响应速度，原文约 ${attachment.charCount ?? originalText.length} 字，已截取前段 / 中段 / 末段关键内容。若需逐段深挖，可继续追问具体章节。]`
      : '';

    return (
      `\n\n---\n📎 附件${attachments.length > 1 ? ` #${index + 1}` : ''}“${attachment.fileName}”内容（${attachment.charCount ?? originalText.length} 字符）：\n\n${compacted.text}${extraNote}`
    );
  }).join('');
}

function buildHistoryMessage(message: Pick<Message, 'role' | 'content' | 'attachments'>): { role: string; content: string } {
  if (message.role !== 'user') {
    return { role: message.role, content: message.content };
  }
  const attachmentContext = buildAttachmentContext(message.attachments);
  return {
    role: message.role,
    content: attachmentContext ? `${message.content}${attachmentContext}` : message.content,
  };
}

function buildHistoryMessages(messages: Message[]): Array<{ role: string; content: string }> {
  return messages
    .filter((message) => !(message.role === 'assistant' && message.metadata?.generationState === 'error' && message.content.trim() === ERROR_MESSAGE_FALLBACK))
    .map(buildHistoryMessage);
}

export default function ChatArea() {
  const activeSurface = useAppStore((state) => state.activeSurface);
  const currentRoleId = useAppStore((state) => state.currentRoleId);
  const roles = useAppStore((state) => state.roles);
  const llmConfigs = useAppStore((state) => state.llmConfigs);
  const activeLLMConfigId = useAppStore((state) => state.activeLLMConfigId);
  const toggleContextPanel = useAppStore((state) => state.toggleContextPanel);
  const contextPanelVisible = useAppStore((state) => state.contextPanelVisible);
  const backend = useAppStore((state) => state.backend);
  const currentRole = roles.find((r) => r.id === currentRoleId);
  const conversations = useChatStore((state) => state.conversations);
  const activeConversationId = useChatStore((state) => state.activeConversationId);
  const messagesByConversation = useChatStore((state) => state.messagesByConversation);
  const streamingByConversation = useChatStore((state) => state.streamingByConversation);
  const addMessage = useChatStore((state) => state.addMessage);
  const setStreaming = useChatStore((state) => state.setStreaming);
  const updateMessage = useChatStore((state) => state.updateMessage);
  const updateMessageMetadata = useChatStore((state) => state.updateMessageMetadata);
  const createConversation = useChatStore((state) => state.createConversation);
  const setActiveConversation = useChatStore((state) => state.setActiveConversation);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 每个对话独立持有自己的 AbortController，避免多对话并发时互相覆盖
  const abortMapRef = useRef<Record<string, AbortController>>({});
  const pendingStreamContentRef = useRef<Record<string, string>>({});
  const pendingAssistantMessageIdRef = useRef<Record<string, string>>({});
  const flushTimerRef = useRef<Record<string, number>>({});
  const welcomeFileRef = useRef<HTMLInputElement>(null);
  const activeLLMConfig = llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0];
  const hasUsableLLMConfig = Boolean(activeLLMConfig && (activeLLMConfig.hasApiKey ?? activeLLMConfig.apiKey));
  /** Agent 模式：当前正在执行的查询 */
  const [agentExecution, setAgentExecution] = useState<AgentExecutionRequest | null>(null);
  const [welcomeUploading, setWelcomeUploading] = useState(false);
  const [welcomeFeedbackMessage, setWelcomeFeedbackMessage] = useState('');
  /** 预填充到输入框的文本 */
  const [prefillText, setPrefillText] = useState('');
  const clearPrefill = useCallback(() => setPrefillText(''), []);

  const modeConversation = useMemo(() => {
    const activeConversation = conversations.find((conversation) => conversation.id === activeConversationId);
    if (activeConversation?.surface === activeSurface && activeConversation?.roleId === currentRoleId) {
      return activeConversation;
    }
    return conversations.find((conversation) => (
      conversation.surface === activeSurface && conversation.roleId === currentRoleId
    )) ?? null;
  }, [conversations, activeConversationId, activeSurface, currentRoleId]);

  const visibleConversationId = modeConversation?.id ?? null;
  const visibleMessages = visibleConversationId ? (messagesByConversation[visibleConversationId] ?? []) : [];
  const visibleIsStreaming = visibleConversationId ? (streamingByConversation[visibleConversationId] ?? false) : false;
  const streamingMessageId = useMemo(() => {
    if (!visibleIsStreaming) return null;
    for (let index = visibleMessages.length - 1; index >= 0; index -= 1) {
      const message = visibleMessages[index];
      if (message.role === 'assistant') {
        return message.id;
      }
    }
    return null;
  }, [visibleIsStreaming, visibleMessages]);

  useEffect(() => {
    if (visibleConversationId && visibleConversationId !== activeConversationId) {
      setActiveConversation(visibleConversationId);
    }
  }, [visibleConversationId, activeConversationId, setActiveConversation]);

  useEffect(() => {
    if (activeSurface !== 'agent' && agentExecution) {
      setAgentExecution(null);
    }
  }, [activeSurface, agentExecution]);

  const clearPendingStreamState = useCallback((conversationId: string) => {
    const timer = flushTimerRef.current[conversationId];
    if (timer !== undefined) {
      window.clearTimeout(timer);
      delete flushTimerRef.current[conversationId];
    }
    delete pendingStreamContentRef.current[conversationId];
    delete pendingAssistantMessageIdRef.current[conversationId];
  }, []);

  const flushPendingStreamUpdate = useCallback((conversationId: string) => {
    const messageId = pendingAssistantMessageIdRef.current[conversationId];
    const content = pendingStreamContentRef.current[conversationId];
    const timer = flushTimerRef.current[conversationId];
    if (timer !== undefined) {
      window.clearTimeout(timer);
      delete flushTimerRef.current[conversationId];
    }
    if (!messageId || content === undefined) {
      return;
    }
    void updateMessage(messageId, content, conversationId, { persist: false }).catch(() => {});
  }, [updateMessage]);

  const schedulePendingStreamUpdate = useCallback((conversationId: string, messageId: string) => {
    pendingAssistantMessageIdRef.current[conversationId] = messageId;
    if (flushTimerRef.current[conversationId] !== undefined) {
      return;
    }
    flushTimerRef.current[conversationId] = window.setTimeout(() => {
      flushPendingStreamUpdate(conversationId);
    }, 32);
  }, [flushPendingStreamUpdate]);

  useEffect(() => () => {
    Object.values(flushTimerRef.current).forEach((timer) => window.clearTimeout(timer));
  }, []);

  // 消息列表自动滚动到底部；流式阶段使用 auto，避免每个 chunk 触发 smooth 动画
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: visibleIsStreaming ? 'auto' : 'smooth',
      block: 'end',
    });
  }, [visibleMessages, visibleIsStreaming]);

  const handleApplySkillSuggestion = useCallback((
    message: Message,
    suggestion: SkillSuggestionEvent,
  ) => {
    setPrefillText(`请使用“${suggestion.skill_name}”技能帮我处理`);
    void updateMessageMetadata(
      message.id,
      { skillSuggestion: undefined },
      message.conversationId,
    ).catch(() => {});
  }, [updateMessageMetadata]);

  const handleDismissSkillSuggestion = useCallback((message: Message) => {
    void updateMessageMetadata(
      message.id,
      { skillSuggestion: undefined },
      message.conversationId,
    ).catch(() => {});
  }, [updateMessageMetadata]);

  const finalizeAutoTitle = useCallback((conversationId: string, llmConfig: LLMConfig) => {
    window.setTimeout(() => {
      const state = useChatStore.getState();
      const conv = state.conversations.find((item) => item.id === conversationId);
      const convMessages = state.messagesByConversation[conversationId] ?? [];
      const assistantCount = convMessages.filter((item) => item.role === 'assistant').length;

      if (
        conv
        && !conv.isTitleCustomized
        && conv.title === DEFAULT_CONVERSATION_TITLE
        && assistantCount >= 3
      ) {
        generateAutoTitle(
          convMessages.map((item) => ({ role: item.role, content: item.content })),
          llmConfig,
        )
          .then((title) => {
            if (title && title !== DEFAULT_CONVERSATION_TITLE) {
              void useChatStore.getState().renameConversation(conversationId, title, false).catch(() => {});
            }
          })
          .catch(() => {});
      }
    }, 100);
  }, []);

  const startAssistantStream = useCallback((params: {
    conversationId: string;
    assistantMessageId: string;
    history: Array<{ role: string; content: string }>;
    llmConfig: LLMConfig;
    ragQuery: string;
    roleId: string;
    preview: GenerationPreview;
  }) => {
    const {
      conversationId,
      assistantMessageId,
      history,
      llmConfig,
      ragQuery,
      roleId,
      preview,
    } = params;

    setStreaming(true, conversationId);
    clearPendingStreamState(conversationId);
    pendingStreamContentRef.current[conversationId] = '';
    pendingAssistantMessageIdRef.current[conversationId] = assistantMessageId;

    void updateMessage(assistantMessageId, '', conversationId, { persist: false }).catch(() => {});
    void updateMessageMetadata(
      assistantMessageId,
      {
        context: undefined,
        skillSuggestion: undefined,
        generationPhase: 'queued',
        generationStatusText: '已发送，正在准备回答',
        generationPreview: preview,
        generationState: undefined,
        generationError: undefined,
      },
      conversationId,
      { persist: false },
    ).catch(() => {});

    const controller = new AbortController();
    abortMapRef.current[conversationId] = controller;

    let fullContent = '';
    let hasReceivedChunk = false;

    const handleStreamError = (error: string) => {
      setStreaming(false, conversationId);
      flushPendingStreamUpdate(conversationId);
      clearPendingStreamState(conversationId);
      delete abortMapRef.current[conversationId];
      const nextContent = fullContent.trim() ? fullContent : ERROR_MESSAGE_FALLBACK;
      void updateMessage(assistantMessageId, nextContent, conversationId).catch(() => {});
      void updateMessageMetadata(
        assistantMessageId,
        {
          generationPhase: undefined,
          generationStatusText: undefined,
          generationPreview: undefined,
          generationState: 'error',
          generationError: error,
        },
        conversationId,
      ).catch(() => {});
    };

    void streamChat(
      history,
      llmConfig,
      (chunk) => {
        if (!hasReceivedChunk) {
          hasReceivedChunk = true;
          void updateMessageMetadata(
            assistantMessageId,
            {
              generationPhase: 'streaming',
              generationStatusText: '正在生成回答',
              generationPreview: undefined,
            },
            conversationId,
            { persist: false },
          ).catch(() => {});
        }
        fullContent += chunk;
        pendingStreamContentRef.current[conversationId] = fullContent;
        schedulePendingStreamUpdate(conversationId, assistantMessageId);
      },
      () => {
        setStreaming(false, conversationId);
        delete abortMapRef.current[conversationId];
        clearPendingStreamState(conversationId);
        void updateMessage(assistantMessageId, fullContent, conversationId).catch(() => {});
        void updateMessageMetadata(
          assistantMessageId,
          {
            generationPhase: undefined,
            generationStatusText: undefined,
            generationPreview: undefined,
            generationState: undefined,
            generationError: undefined,
          },
          conversationId,
          { persist: false },
        ).catch(() => {});
        finalizeAutoTitle(conversationId, llmConfig);
      },
      handleStreamError,
      controller.signal,
      roleId,
      ragQuery,
      (metadata) => {
        void updateMessageMetadata(assistantMessageId, { context: metadata }, conversationId).catch(() => {});
      },
      (suggestion) => {
        void updateMessageMetadata(assistantMessageId, { skillSuggestion: suggestion }, conversationId).catch(() => {});
      },
      (status: ChatStatusEvent) => {
        void updateMessageMetadata(
          assistantMessageId,
          {
            generationPhase: status.phase,
            generationStatusText: status.detail?.trim() || status.label,
            generationPreview: status.phase === 'streaming' ? undefined : preview,
          },
          conversationId,
          { persist: false },
        ).catch(() => {});
      },
    ).catch((error: unknown) => {
      handleStreamError((error as Error).message || '网络错误');
    });
  }, [
    clearPendingStreamState,
    finalizeAutoTitle,
    flushPendingStreamUpdate,
    schedulePendingStreamUpdate,
    setStreaming,
    updateMessage,
    updateMessageMetadata,
  ]);

  const handleRetryGeneration = useCallback((message: Message) => {
    if (!activeLLMConfig) {
      return;
    }

    const convMessages = messagesByConversation[message.conversationId] ?? [];
    const assistantIndex = convMessages.findIndex((item) => item.id === message.id);
    if (assistantIndex < 0 || assistantIndex !== convMessages.length - 1) {
      return;
    }

    const historyBeforeAssistant = convMessages.slice(0, assistantIndex);
    const lastUserMessage = [...historyBeforeAssistant].reverse().find((item) => item.role === 'user');
    if (!lastUserMessage) {
      return;
    }

    startAssistantStream({
      conversationId: message.conversationId,
      assistantMessageId: message.id,
      history: buildHistoryMessages(historyBeforeAssistant),
      llmConfig: activeLLMConfig,
      ragQuery: lastUserMessage.content,
      roleId: currentRoleId,
      preview: buildGenerationPreview(lastUserMessage.content, lastUserMessage.attachments),
    });
  }, [activeLLMConfig, currentRoleId, messagesByConversation, startAssistantStream]);

  /** 发送消息（支持附件上下文） */
  const handleSend = async (content: string, attachments?: Attachment[]) => {
    // Agent 模式：触发 Skill 匹配 → 执行工作流
    if (activeSurface === 'agent') {
      let convId = visibleConversationId;
      if (!convId) convId = await createConversation(currentRoleId, 'agent');
      await addMessage({ conversationId: convId, role: 'user', content });
      setAgentExecution({ query: content, conversationId: convId });
      return;
    }

    // 正常 LLM 对话
    let convId = visibleConversationId;
    if (!convId) {
      convId = await createConversation(currentRoleId, 'chat');
    } else if (activeConversationId !== convId) {
      setActiveConversation(convId);
    }

    const targetConvId = convId;
    const historyMessages = messagesByConversation[targetConvId] ?? [];
    const messageAttachments = attachments && attachments.length > 0 ? attachments : undefined;

    if (!activeLLMConfig) {
      throw new Error('请选择可用模型配置');
    }

    await addMessage({
      conversationId: targetConvId,
      role: 'user',
      content,
      attachments: messageAttachments,
    });

    const history = [
      ...buildHistoryMessages(historyMessages),
      buildHistoryMessage({ role: 'user', content, attachments: messageAttachments }),
    ];
    const assistantMsgId = await addMessage({
      conversationId: targetConvId,
      role: 'assistant',
      content: '',
    });

    startAssistantStream({
      conversationId: targetConvId,
      assistantMessageId: assistantMsgId,
      history,
      llmConfig: activeLLMConfig,
      ragQuery: content,
      roleId: currentRoleId,
      preview: buildGenerationPreview(content, messageAttachments),
    });
  };

  /** 欢迎屏文件上传：提取文本后直接发送 */
  const handleWelcomeQuickMessage = useCallback(async (message: string) => {
    setWelcomeFeedbackMessage('');
    try {
      await handleSend(message);
    } catch (error: unknown) {
      setWelcomeFeedbackMessage((error as Error).message || '发送失败');
      throw error;
    }
  }, [handleSend]);

  /** 欢迎屏文件上传：提取文本后直接发送 */
  const handleWelcomeFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    e.target.value = '';
    setWelcomeUploading(true);
    setWelcomeFeedbackMessage('');
    try {
      const extracted = await extractFilesText(files);
      const successfulResults = extracted.files;
      const failedMessages = extracted.errors.map((item) => `${item.filename}: ${item.error}`);

      if (failedMessages.length > 0) {
        setWelcomeFeedbackMessage(`以下文件文本提取失败：${failedMessages.join('；')}`);
      }
      if (successfulResults.length === 0) {
        return;
      }

      const attachments: Attachment[] = successfulResults.map((result, index) => ({
        id: globalThis.crypto?.randomUUID?.() ?? `${result.filename}-${index}-${Date.now()}-${Math.random()}`,
        fileName: result.filename,
        fileType: result.file_type,
        fileSize: 0,
        text: result.text,
        charCount: result.char_count,
      }));
      await handleSend(
        successfulResults.length > 1 ? '请综合分析这些文件的内容' : '请分析这份文件的内容',
        attachments,
      );
    } catch (err: any) {
      setWelcomeFeedbackMessage(`文件文本提取失败：${err.message || '未知错误'}`);
    } finally {
      setWelcomeUploading(false);
    }
  };

  /** 停止生成（仅中止当前活跃对话的流，不影响其他对话） */
  const handleStop = () => {
    if (visibleConversationId) {
      const assistantMessageId = pendingAssistantMessageIdRef.current[visibleConversationId] ?? streamingMessageId;
      const partialContent = pendingStreamContentRef.current[visibleConversationId] ?? '';
      flushPendingStreamUpdate(visibleConversationId);
      abortMapRef.current[visibleConversationId]?.abort();
      delete abortMapRef.current[visibleConversationId];
      setStreaming(false, visibleConversationId);
      clearPendingStreamState(visibleConversationId);
      if (assistantMessageId) {
        const nextContent = partialContent.trim() ? partialContent : STOPPED_MESSAGE_FALLBACK;
        void updateMessage(assistantMessageId, nextContent, visibleConversationId).catch(() => {});
        void updateMessageMetadata(
          assistantMessageId,
          {
            generationPhase: undefined,
            generationStatusText: undefined,
            generationPreview: undefined,
            generationState: 'stopped',
            generationError: undefined,
          },
          visibleConversationId,
        ).catch(() => {});
      }
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-surface dark:bg-dark">
      {/* 顶部工具栏 */}
      <div className="win-toolbar h-12 px-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-md border border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-sidebar text-base shadow-sm">
            <span>{currentRole?.icon ?? '💬'}</span>
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-sm font-semibold truncate">{currentRole?.name ?? currentRoleId}</span>
              <span
                className={backend.connected
                  ? 'win-badge border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300'
                  : 'win-badge border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300'}
              >
                <span className={backend.connected ? 'h-1.5 w-1.5 rounded-full bg-emerald-500' : 'h-1.5 w-1.5 rounded-full bg-amber-500'} />
                {backend.connected ? '后端已连接' : '后端未连接'}
              </span>
            </div>
            <p className="text-xs text-text-secondary truncate mt-0.5">
              {activeLLMConfig?.model ? `当前模型：${activeLLMConfig.model}` : '请选择可用模型配置'}
            </p>
          </div>
        </div>
        <button
          onClick={toggleContextPanel}
          className="win-button h-8 px-3 text-xs"
          title={contextPanelVisible ? '隐藏上下文面板' : '显示上下文面板'}
        >
          <span>📋</span>
          <span>{contextPanelVisible ? '隐藏面板' : '上下文面板'}</span>
        </button>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-4 bg-[#F7F8FA] dark:bg-[#101726]">
        <div className="flex h-full w-full flex-col">
          {visibleMessages.length === 0 && !agentExecution ? (
            <>
              {/* 隐藏的文件输入（欢迎屏使用） */}
              <input
                ref={welcomeFileRef}
                type="file"
                multiple
                accept=".ppt,.pptx,.pdf,.doc,.docx,.txt,.md,.csv,.json,.xml,.xls,.xlsx,.png,.jpg,.jpeg,.gif,.bmp,.webp,image/*"
                className="hidden"
                onChange={handleWelcomeFileChange}
              />
              <WelcomeScreen
                mode={currentRoleId}
                surface={activeSurface}
                onQuickMessage={handleWelcomeQuickMessage}
                onUploadFile={() => welcomeFileRef.current?.click()}
                uploading={welcomeUploading}
                feedbackMessage={welcomeFeedbackMessage}
                onDismissFeedback={() => setWelcomeFeedbackMessage('')}
              />
            </>
          ) : (
            <>
              {visibleMessages.map((msg, index) => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isStreaming={msg.id === streamingMessageId}
                  onApplySkillSuggestion={handleApplySkillSuggestion}
                  onDismissSkillSuggestion={handleDismissSkillSuggestion}
                  onRetryGeneration={handleRetryGeneration}
                  canRetryGeneration={
                    !visibleIsStreaming
                    && index === visibleMessages.length - 1
                    && msg.role === 'assistant'
                    && Boolean(msg.metadata?.generationState)
                  }
                />
              ))}
              {/* Agent 模式执行面板 */}
              {activeSurface === 'agent' && agentExecution && (
                <Suspense fallback={<AgentPanelFallback />}>
                  <AgentExecutionPanel
                    query={agentExecution.query}
                    conversationId={agentExecution.conversationId}
                    onComplete={async (payload) => {
                      await addMessage({
                        conversationId: agentExecution.conversationId,
                        role: 'assistant',
                        content: payload.content,
                        metadata: payload.metadata,
                      });
                      setAgentExecution(null);
                    }}
                    onCancel={() => setAgentExecution(null)}
                  />
                </Suspense>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* 输入区域 */}
      <ChatInput
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={visibleIsStreaming}
        disabled={!hasUsableLLMConfig}
        prefillText={prefillText}
        onPrefillConsumed={clearPrefill}
      />
    </div>
  );
}

function AgentPanelFallback() {
  return (
    <div className="my-3 rounded-lg border border-surface-divider bg-white px-4 py-3 text-sm text-text-secondary shadow-sm dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary">
      正在加载 Agent 执行面板...
    </div>
  );
}

/** 欢迎屏幕 - 无对话时显示 */
function WelcomeScreen({ mode, surface, onQuickMessage, onUploadFile, uploading, feedbackMessage, onDismissFeedback }: {
  mode: string;
  surface: 'chat' | 'agent';
  onQuickMessage: (msg: string, attachments?: Attachment[]) => Promise<void> | void;
  onUploadFile: () => void;
  uploading: boolean;
  feedbackMessage: string;
  onDismissFeedback: () => void;
}) {
  return (
    <div className="flex flex-1 items-center justify-center py-8 animate-fade-in">
      <div className="win-panel w-full max-w-2xl px-8 py-9 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl border border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-sidebar text-3xl shadow-sm">🍒</div>
        <h2 className="text-[22px] font-semibold mb-2">Ask Me Anything</h2>
        {feedbackMessage && (
          <InlineNotice
            className="mx-auto mb-4 max-w-xl text-left"
            message={feedbackMessage}
            onClose={onDismissFeedback}
          />
        )}
        <p className="text-text-secondary text-sm max-w-xl mx-auto leading-6">
          {surface === 'agent' && '选择一个任务并输入目标，我会以当前 Agent 角色执行完整流程。'}
          {surface === 'chat' && mode === 'copilot' && '你好！我是你的AI小助手。使用下方 📎 按钮添加附件，或直接提问。'}
          {surface === 'chat' && mode === 'builder' && '在这里，你可以通过对话创建自定义 Skill，将重复工作自动化。'}
          {surface === 'chat' && mode === 'executor' && '你当前在聊天链路下使用执行助手角色，可以先讨论需求，再切到 Agent 执行。'}
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3 text-sm text-text-secondary">
          <button
            onClick={() => {
              void Promise.resolve(onQuickMessage('你好，请介绍一下你能做什么')).catch(() => {});
            }}
            className="win-button h-10 px-4 text-sm"
          >
            👋 &quot;你好&quot;
          </button>
          <button
            onClick={onUploadFile}
            disabled={uploading}
            className="win-button-primary h-10 px-4 text-sm disabled:opacity-50 disabled:cursor-wait"
          >
            {uploading ? '⏳ 提取中...' : '📎 上传文件'}
          </button>
        </div>
      </div>
    </div>
  );
}
