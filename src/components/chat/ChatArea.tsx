/**
 * 聊天区域组件
 * 包含：顶部工具栏、消息列表（自动滚动）、底部输入区
 * Agent 模式下触发 Skill 匹配 → 执行工作流
 */
import { useState, useRef, useEffect, useCallback, useMemo, type ChangeEvent } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useChatStore, DEFAULT_CONVERSATION_TITLE } from '@/stores/chatStore';
import { streamChat, extractFilesText, generateAutoTitle } from '@/services/api';
import { MODE_CONFIG, type Message, type SkillSuggestionEvent } from '@/types';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import AgentExecutionPanel from '../agent/AgentExecutionPanel';

export default function ChatArea() {
  const {
    currentMode,
    llmConfigs,
    activeLLMConfigId,
    toggleContextPanel,
    contextPanelVisible,
    backend,
  } = useAppStore();
  const {
    conversations, activeConversationId, messagesByConversation,
    streamingByConversation, streamingContentByConversation,
    addMessage, setStreaming,
    appendStreamContent, resetStreamContent, updateMessage, updateMessageMetadata,
    createConversation, setActiveConversation,
  } = useChatStore();

  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 每个对话独立持有自己的 AbortController，避免多对话并发时互相覆盖
  const abortMapRef = useRef<Record<string, AbortController>>({});
  const welcomeFileRef = useRef<HTMLInputElement>(null);
  const activeLLMConfig = llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0];
  /** Agent 模式：当前正在执行的查询 */
  const [agentQuery, setAgentQuery] = useState<string | null>(null);
  const [welcomeUploading, setWelcomeUploading] = useState(false);
  /** 预填充到输入框的文本 */
  const [prefillText, setPrefillText] = useState('');
  const clearPrefill = useCallback(() => setPrefillText(''), []);

  const modeConversation = useMemo(() => {
    const activeConversation = conversations.find((conversation) => conversation.id === activeConversationId);
    if (activeConversation?.mode === currentMode) {
      return activeConversation;
    }
    return conversations.find((conversation) => conversation.mode === currentMode) ?? null;
  }, [conversations, activeConversationId, currentMode]);

  const visibleConversationId = modeConversation?.id ?? null;
  const visibleMessages = visibleConversationId ? (messagesByConversation[visibleConversationId] ?? []) : [];
  const visibleIsStreaming = visibleConversationId ? (streamingByConversation[visibleConversationId] ?? false) : false;
  const visibleStreamingContent = visibleConversationId ? (streamingContentByConversation[visibleConversationId] ?? '') : '';
  const streamingAssistantMessageId = useMemo(() => {
    if (!visibleIsStreaming) return null;

    for (let index = visibleMessages.length - 1; index >= 0; index -= 1) {
      if (visibleMessages[index].role === 'assistant') {
        return visibleMessages[index].id;
      }
    }

    return null;
  }, [visibleIsStreaming, visibleMessages]);

  useEffect(() => {
    if (visibleConversationId && visibleConversationId !== activeConversationId) {
      setActiveConversation(visibleConversationId);
    }
  }, [visibleConversationId, activeConversationId, setActiveConversation]);

  // 消息列表自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [visibleMessages, visibleStreamingContent]);

  const handleApplySkillSuggestion = useCallback((
    message: Message,
    suggestion: SkillSuggestionEvent,
  ) => {
    setPrefillText(`请使用「${suggestion.skill_name}」技能帮我处理`);
    updateMessageMetadata(message.id, { skillSuggestion: undefined }, message.conversationId);
  }, [updateMessageMetadata]);

  const handleDismissSkillSuggestion = useCallback((message: Message) => {
    updateMessageMetadata(message.id, { skillSuggestion: undefined }, message.conversationId);
  }, [updateMessageMetadata]);

  /** 发送消息（支持附件上下文） */
  const handleSend = async (content: string, attachmentContext?: string) => {
    // Agent 模式：触发 Skill 匹配 → 执行工作流
    if (currentMode === 'agent') {
      let convId = visibleConversationId;
      if (!convId) convId = createConversation(currentMode);
      addMessage({ conversationId: convId, role: 'user', content });
      setAgentQuery(content);
      return;
    }

    // Copilot / Builder 模式：正常 LLM 对话
    let convId = visibleConversationId;
    if (!convId) {
      convId = createConversation(currentMode);
    } else if (activeConversationId !== convId) {
      setActiveConversation(convId);
    }

    const targetConvId = convId;
    const historyMessages = messagesByConversation[targetConvId] ?? [];

    // 用户消息只显示用户输入的文字（不含附件原文）
    addMessage({ conversationId: targetConvId, role: 'user', content });

    if (!activeLLMConfig) return;

    // 发给 LLM 的内容 = 用户消息 + 附件文本上下文
    const llmContent = attachmentContext ? content + attachmentContext : content;

    const history = [
      ...historyMessages.map((m) => ({ role: m.role, content: m.content })),
      { role: 'user', content: llmContent },
    ];

    // 使用当前 convId 隔离流式状态，避免阻塞其他对话
    setStreaming(true, targetConvId);
    resetStreamContent(targetConvId);

    // 每个对话独立创建 AbortController，存入 Map，互不干扰
    const controller = new AbortController();
    abortMapRef.current[targetConvId] = controller;

    const assistantMsgId = addMessage({
      conversationId: targetConvId,
      role: 'assistant',
      content: '',
    });

    let fullContent = '';

    await streamChat(
      history,
      activeLLMConfig,
      (chunk) => {
        fullContent += chunk;
        appendStreamContent(chunk, targetConvId);
        updateMessage(assistantMsgId, fullContent, targetConvId);
      },
      () => {
        setStreaming(false, targetConvId);
        resetStreamContent(targetConvId);
        delete abortMapRef.current[targetConvId];

        // 自动命名：第 3 条 assistant 消息完成后（或之后），且用户未手动命名
        // 使用 setTimeout 确保 store 状态已完全同步
        console.log('[AutoTitle] onDone fired, activeLLMConfig:', !!activeLLMConfig);
        if (activeLLMConfig) {
          setTimeout(() => {
            const state = useChatStore.getState();
            const conv = state.conversations.find((c) => c.id === targetConvId);
            const convMessages = state.messagesByConversation[targetConvId] ?? [];
            const assistantCount = convMessages.filter((m) => m.role === 'assistant').length;

            console.log('[AutoTitle] check:', {
              convId: targetConvId,
              convFound: !!conv,
              title: conv?.title,
              isTitleCustomized: conv?.isTitleCustomized,
              assistantCount,
              defaultTitle: DEFAULT_CONVERSATION_TITLE,
              titleMatchesDefault: conv?.title === DEFAULT_CONVERSATION_TITLE,
            });

            // 条件：未手动命名 + 标题仍为默认 + 至少完成 3 轮
            if (
              conv &&
              !conv.isTitleCustomized &&
              conv.title === DEFAULT_CONVERSATION_TITLE &&
              assistantCount >= 3
            ) {
              console.log('[AutoTitle] triggering generateAutoTitle...');
              generateAutoTitle(
                convMessages.map((m) => ({ role: m.role, content: m.content })),
                activeLLMConfig
              )
                .then((title) => {
                  console.log('[AutoTitle] received title:', JSON.stringify(title));
                  if (title && title !== DEFAULT_CONVERSATION_TITLE) {
                    useChatStore.getState().renameConversation(targetConvId, title, false);
                    console.log('[AutoTitle] renameConversation called, new title:', title);
                    // 验证更新是否生效
                    const updated = useChatStore.getState().conversations.find((c) => c.id === targetConvId);
                    console.log('[AutoTitle] after rename, conv title:', updated?.title);
                  } else {
                    console.log('[AutoTitle] title rejected (empty or default)');
                  }
                })
                .catch((err) => {
                  console.error('[AutoTitle] failed:', err);
                });
            } else {
              console.log('[AutoTitle] conditions not met, skipping');
            }
          }, 100);
        }
      },
      (error) => {
        setStreaming(false, targetConvId);
        resetStreamContent(targetConvId);
        updateMessage(assistantMsgId, `⚠️ 错误: ${error}`, targetConvId);
        delete abortMapRef.current[targetConvId];
      },
      controller.signal,
      currentMode,
      content,
      (metadata) => {
        updateMessageMetadata(assistantMsgId, { context: metadata }, targetConvId);
      },
      (suggestion) => {
        updateMessageMetadata(assistantMsgId, { skillSuggestion: suggestion }, targetConvId);
      },
    );
  };

  /** 欢迎屏文件上传：提取文本后直接发送 */
  const handleWelcomeFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;
    e.target.value = '';
    setWelcomeUploading(true);
    try {
      const extracted = await extractFilesText(files);
      const successfulResults = extracted.files;
      const failedMessages = extracted.errors.map((item) => `${item.filename}: ${item.error}`);

      if (failedMessages.length > 0) {
        alert(`以下文件文本提取失败：\n${failedMessages.join('\n')}`);
      }
      if (successfulResults.length === 0) {
        return;
      }

      const attachmentContext = successfulResults.map((result, index) => (
        `\n\n---\n📎 附件${successfulResults.length > 1 ? ` #${index + 1}` : ''}「${result.filename}」内容（${result.char_count} 字符）：\n\n${result.text}`
      )).join('');
      await handleSend(
        successfulResults.length > 1 ? '请综合分析这些文件的内容' : '请分析这份文件的内容',
        attachmentContext,
      );
    } catch (err: any) {
      alert(`文件文本提取失败：${err.message || '未知错误'}`);
    } finally {
      setWelcomeUploading(false);
    }
  };

  /** 停止生成（仅中止当前活跃对话的流，不影响其他对话） */
  const handleStop = () => {
    if (visibleConversationId) {
      abortMapRef.current[visibleConversationId]?.abort();
      delete abortMapRef.current[visibleConversationId];
      setStreaming(false, visibleConversationId);
      resetStreamContent(visibleConversationId);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-surface dark:bg-dark">
      {/* 顶部工具栏 */}
      <div className="win-toolbar h-12 px-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-md border border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-sidebar text-base shadow-sm">
            <span>{MODE_CONFIG[currentMode].icon}</span>
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-sm font-semibold truncate">{MODE_CONFIG[currentMode].label}</span>
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
        {visibleMessages.length === 0 && !agentQuery ? (
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
              mode={currentMode}
              onQuickMessage={handleSend}
              onUploadFile={() => welcomeFileRef.current?.click()}
              uploading={welcomeUploading}
            />
          </>
        ) : (
          <>
            {visibleMessages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                isStreaming={msg.id === streamingAssistantMessageId}
                onApplySkillSuggestion={handleApplySkillSuggestion}
                onDismissSkillSuggestion={handleDismissSkillSuggestion}
              />
            ))}
            {/* Agent 模式执行面板 */}
            {agentQuery && (
              <AgentExecutionPanel
                query={agentQuery}
                onComplete={(result) => {
                  const convId = activeConversationId || createConversation('agent');
                  addMessage({ conversationId: convId, role: 'assistant', content: result });
                  setAgentQuery(null);
                }}
                onCancel={() => setAgentQuery(null)}
              />
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
        disabled={!activeLLMConfig?.apiKey}
        prefillText={prefillText}
        onPrefillConsumed={clearPrefill}
      />
    </div>
  );
}

/** 欢迎屏幕 - 无对话时显示 */
function WelcomeScreen({ mode, onQuickMessage, onUploadFile, uploading }: {
  mode: string;
  onQuickMessage: (msg: string) => void;
  onUploadFile: () => void;
  uploading: boolean;
}) {
  return (
    <div className="flex flex-1 items-center justify-center py-8 animate-fade-in">
      <div className="win-panel w-full max-w-2xl px-8 py-9 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl border border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-sidebar text-3xl shadow-sm">🍒</div>
        <h2 className="text-[22px] font-semibold mb-2">Meeting Assistant</h2>
        <p className="text-text-secondary text-sm max-w-xl mx-auto leading-6">
          {mode === 'copilot' && '你好！我是你的会议助手。使用下方 📎 按钮添加附件，或直接提问。'}
          {mode === 'builder' && '在这里，你可以通过对话创建自定义 Skill，将重复工作自动化。'}
          {mode === 'agent' && '选择一个 Skill，我将自动执行完整的工作流程。'}
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3 text-sm text-text-secondary">
          <button
            onClick={() => onQuickMessage('你好，请介绍一下你能做什么')}
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
