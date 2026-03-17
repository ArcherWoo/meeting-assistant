/**
 * 消息气泡组件
 * 用户消息右对齐，AI 消息左对齐
 * AI 消息支持 Markdown 渲染
 */
import clsx from 'clsx';
import type { Message } from '@/types';

interface Props {
  message: Message;
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user';
  const isError = message.content.startsWith('⚠️');

  return (
    <div
      className={clsx(
        'flex mb-4 animate-fade-in',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {/* AI 头像 */}
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-primary-100 dark:bg-primary-900/40 flex items-center justify-center flex-shrink-0 mr-2 mt-1">
          <span className="text-sm">🍒</span>
        </div>
      )}

      {/* 消息内容 */}
      <div
        className={clsx(
          'max-w-[75%] px-4 py-2.5 rounded-card text-sm leading-relaxed',
          isUser
            ? 'bg-primary text-white rounded-br-sm'
            : isError
              ? 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-bl-sm'
              : 'bg-surface-card dark:bg-dark-card shadow-light rounded-bl-sm'
        )}
      >
        {isUser ? (
          // 用户消息：纯文本
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          // AI 消息：Markdown 渲染（Phase 1 简化版，后续集成 react-markdown）
          <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap">
            {message.content || (
              <span className="inline-flex items-center gap-1 text-text-secondary">
                <span className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse" />
                <span className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse [animation-delay:300ms]" />
              </span>
            )}
          </div>
        )}
      </div>

      {/* 用户头像 */}
      {isUser && (
        <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center flex-shrink-0 ml-2 mt-1">
          <span className="text-white text-xs font-medium">U</span>
        </div>
      )}
    </div>
  );
}

