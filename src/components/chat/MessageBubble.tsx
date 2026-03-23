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
  const senderLabel = isUser ? '你' : 'Meeting Assistant';

  return (
    <div
      className={clsx(
        'mb-4 flex items-start gap-3 animate-fade-in',
        isUser ? 'justify-end' : 'justify-start'
      )}
    >
      {/* AI 头像 */}
      {!isUser && (
        <div className="mt-5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-surface-divider dark:border-dark-divider bg-white text-sm shadow-sm dark:bg-dark-card">
          <span className="text-sm">🍒</span>
        </div>
      )}

      {/* 消息内容 */}
      <div className="min-w-0 max-w-[78%]">
        <div className={clsx('mb-1 px-1 text-[11px] text-text-secondary', isUser && 'text-right')}>
          {senderLabel}
        </div>
        <div
          className={clsx(
            'px-4 py-3 text-[13px] leading-6 shadow-sm',
            isUser
              ? 'rounded-xl rounded-tr-sm bg-primary text-white'
              : isError
                ? 'rounded-xl rounded-tl-sm border border-red-200 bg-red-50 text-red-600 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400'
                : 'rounded-xl rounded-tl-sm border border-surface-divider dark:border-dark-divider bg-white dark:bg-dark-card text-text-primary dark:text-text-dark-primary'
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap prose-p:my-2 prose-headings:mb-2 prose-headings:mt-3 prose-ul:my-2 prose-ol:my-2">
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
      </div>

      {/* 用户头像 */}
      {isUser && (
        <div className="mt-5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-primary shadow-sm">
          <span className="text-white text-xs font-medium">U</span>
        </div>
      )}
    </div>
  );
}

