import clsx from 'clsx';
import { useNotificationStore } from '@/stores/notificationStore';

const toneClassMap = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200',
  error: 'border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-900/30 dark:text-red-200',
  info: 'border-surface-divider bg-white text-text-primary dark:border-dark-divider dark:bg-dark-card dark:text-text-dark-primary',
} as const;

export default function ToastViewport() {
  const notifications = useNotificationStore((state) => state.notifications);
  const dismissNotification = useNotificationStore((state) => state.dismissNotification);

  if (notifications.length === 0) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[70] flex max-w-sm flex-col gap-2">
      {notifications.map((notification) => (
        <div
          key={notification.id}
          className={clsx(
            'pointer-events-auto rounded-xl border px-3 py-3 shadow-lg backdrop-blur-sm',
            toneClassMap[notification.tone],
          )}
          role="status"
          aria-live="polite"
        >
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <p className="whitespace-pre-wrap break-words text-sm leading-6">
                {notification.message}
              </p>
            </div>
            <button
              type="button"
              onClick={() => dismissNotification(notification.id)}
              className="inline-flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md border border-current/10 text-sm opacity-70 transition hover:opacity-100"
              aria-label="关闭通知"
              title="关闭通知"
            >
              ×
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
