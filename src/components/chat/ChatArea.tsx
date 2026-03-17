/**
 * 聊天区域组件
 * 包含：顶部工具栏、消息列表（自动滚动）、底部输入区
 * Agent 模式下触发 Skill 匹配 → 执行工作流
 */
import { useState, useRef, useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useChatStore } from '@/stores/chatStore';
import { streamChat } from '@/services/api';
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
  const abortRef = useRef<AbortController | null>(null);
  const activeLLMConfig = llmConfigs.find((config) => config.id === activeLLMConfigId) ?? llmConfigs[0];
  /** Agent 模式：当前正在执行的查询 */
  const [agentQuery, setAgentQuery] = useState<string | null>(null);

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

    setStreaming(true);
    resetStreamContent();
    const controller = new AbortController();
    abortRef.current = controller;

    const assistantMsgId = addMessage({
      conversationId: convId,
      role: 'assistant',
      content: '',
    });

    let fullContent = '';

    await streamChat(
      history,
      activeLLMConfig,
      (chunk) => {
        fullContent += chunk;
        appendStreamContent(chunk);
        updateMessage(assistantMsgId, fullContent);
      },
      () => {
        setStreaming(false);
        resetStreamContent();
        abortRef.current = null;
      },
      (error) => {
        setStreaming(false);
        resetStreamContent();
        updateMessage(assistantMsgId, `⚠️ 错误: ${error}`);
        abortRef.current = null;
      },
      controller.signal
    );
  };

  /** 停止生成 */
  const handleStop = () => {
    abortRef.current?.abort();
    setStreaming(false);
    resetStreamContent();
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
          <WelcomeScreen mode={currentMode} onQuickMessage={handleSend} />
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
function WelcomeScreen({ mode, onQuickMessage }: {
  mode: string;
  onQuickMessage: (msg: string) => void;
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
          onClick={() => onQuickMessage('帮我总结这份材料')}
          className="px-3 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors cursor-pointer"
        >
          💡 &quot;帮我总结这份材料&quot;
        </button>
      </div>
    </div>
  );
}

