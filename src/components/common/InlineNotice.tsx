import clsx from 'clsx';
import type { ReactNode } from 'react';

type NoticeTone = 'warning' | 'error' | 'info';

const toneClassMap = {
  warning: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300',
  error: 'border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300',
  info: 'border-surface-divider bg-surface text-text-secondary dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-secondary',
} as const;

interface InlineNoticeProps {
  message: ReactNode;
  tone?: NoticeTone;
  onClose?: () => void;
  className?: string;
}

export default function InlineNotice({
  message,
  tone = 'warning',
  onClose,
  className,
}: InlineNoticeProps) {
  return (
    <div
      className={clsx(
        'rounded-md border px-3 py-2 text-xs',
        toneClassMap[tone],
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1 leading-5">
          {message}
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded opacity-70 transition hover:opacity-100"
            aria-label="关闭提示"
            title="关闭提示"
          >
            ×
          </button>
        ) : null}
      </div>
    </div>
  );
}
