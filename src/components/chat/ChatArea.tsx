/**
 * 聊天区域组件
 * 包含：顶部工具栏、消息列表（自动滚动）、底部输入区
 * Agent 模式下触发 Skill 匹配 → 执行工作流
 */
import { useState, useRef, useEffect, type ChangeEvent } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useChatStore, DEFAULT_CONVERSATION_TITLE } from '@/stores/chatStore';
import { streamChat, extractFileText, generateAutoTitle } from '@/services/api';
import { MODE_CONFIG } from '@/types';
import MessageBubble from './MessageBubble';
import ChatInput from './ChatInput';
import AgentExecutionPanel from '../agent/AgentExecutionPanel';

export default function ChatArea() {
  const { currentMode, llmConfigs, activeLLMConfigId, toggleContextPanel } = useAppStore();
  const {
    messages, activeConversationId, isStreaming,
    streamingContent, addMessage, setStreaming,
    appendStreamContent, resetStreamContent, updateMessage,
    createConversation,
  } = useChatStore();

  const messagesEndRef = useRef<HTMLDivElement>(null);
  // 每个对话独立持有自己的 AbortController，避免多对话并发时互相覆盖
  const abortMapRef = useRef<Record<string, AbortController>>({});
  const welcomeFileRef = useRef<HTMLInputElement>(null);
  const activeLLMConfig = llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0];
  /** Agent 模式：当前正在执行的查询 */
  const [agentQuery, setAgentQuery] = useState<string | null>(null);
  const [welcomeUploading, setWelcomeUploading] = useState(false);

  // 消息列表自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  /** 发送消息（支持附件上下文） */
  const handleSend = async (content: string, attachmentContext?: string) => {
    // Agent 模式：触发 Skill 匹配 → 执行工作流
    if (currentMode === 'agent') {
      let convId = activeConversationId;
      if (!convId) convId = createConversation(currentMode);
      addMessage({ conversationId: convId, role: 'user', content });
      setAgentQuery(content);
      return;
    }

    // Copilot / Builder 模式：正常 LLM 对话
    let convId = activeConversationId;
    if (!convId) {
      convId = createConversation(currentMode);
    }

    // 用户消息只显示用户输入的文字（不含附件原文）
    addMessage({ conversationId: convId, role: 'user', content });

    if (!activeLLMConfig) return;

    // 发给 LLM 的内容 = 用户消息 + 附件文本上下文
    const llmContent = attachmentContext ? content + attachmentContext : content;

    const history = [
      ...messages.map((m) => ({ role: m.role, content: m.content })),
      { role: 'user', content: llmContent },
    ];

    // 使用当前 convId 隔离流式状态，避免阻塞其他对话
    const targetConvId = convId;
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
        // 传入 targetConvId，确保更新写入正确对话的消息列表
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
      currentMode
    );
  };

  /** 欢迎屏文件上传：提取文本后直接发送 */
  const handleWelcomeFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setWelcomeUploading(true);
    try {
      const result = await extractFileText(file);
      const attachmentContext = `\n\n---\n📎 附件「${result.filename}」内容（${result.char_count} 字符）：\n\n${result.text}`;
      await handleSend('请分析这份文件的内容', attachmentContext);
    } catch (err: any) {
      alert(`文件文本提取失败：${err.message || '未知错误'}`);
    } finally {
      setWelcomeUploading(false);
    }
  };

  /** 停止生成（仅中止当前活跃对话的流，不影响其他对话） */
  const handleStop = () => {
    if (activeConversationId) {
      abortMapRef.current[activeConversationId]?.abort();
      delete abortMapRef.current[activeConversationId];
      setStreaming(false, activeConversationId);
      resetStreamContent(activeConversationId);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 顶部工具栏 */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-surface-divider dark:border-dark-divider bg-surface-card dark:bg-dark-card">
        <div className="flex items-center gap-2">
          <span>{MODE_CONFIG[currentMode].icon}</span>
          <span className="text-sm font-medium">{MODE_CONFIG[currentMode].label}</span>
        </div>
        <button
          onClick={toggleContextPanel}
          className="text-text-secondary hover:text-text-primary dark:hover:text-text-dark-primary text-sm transition-colors"
          title="切换上下文面板"
        >
          📋
        </button>
      </div>

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-4">
        {messages.length === 0 && !agentQuery ? (
          <>
            {/* 隐藏的文件输入（欢迎屏使用） */}
            <input
              ref={welcomeFileRef}
              type="file"
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
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
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

      {/* 输入区域 */}
      <ChatInput
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        disabled={!activeLLMConfig?.apiKey}
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
    <div className="flex flex-col items-center justify-center h-full text-center animate-fade-in">
      <div className="text-5xl mb-4">🍒</div>
      <h2 className="text-xl font-semibold mb-2">Meeting Assistant</h2>
      <p className="text-text-secondary text-sm max-w-md">
        {mode === 'copilot' && '你好！我是你的会议助手。使用下方 📎 按钮添加附件，或直接提问。'}
        {mode === 'builder' && '在这里，你可以通过对话创建自定义 Skill，将重复工作自动化。'}
        {mode === 'agent' && '选择一个 Skill，我将自动执行完整的工作流程。'}
      </p>
      <div className="mt-6 flex gap-3 text-sm text-text-secondary">
        <button
          onClick={() => onQuickMessage('你好，请介绍一下你能做什么')}
          className="px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors cursor-pointer"
        >
          👋 &quot;你好&quot;
        </button>
        <button
          onClick={onUploadFile}
          disabled={uploading}
          className="px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-wait"
        >
          {uploading ? '⏳ 提取中...' : '📎 上传文件'}
        </button>
      </div>
    </div>
  );
}

