import clsx from 'clsx';
import { useConfirmStore } from '@/stores/confirmStore';

export default function ConfirmDialogHost() {
  const request = useConfirmStore((state) => state.request);
  const resolveConfirm = useConfirmStore((state) => state.resolveConfirm);

  if (!request) return null;

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center bg-black/45 backdrop-blur-sm"
      onClick={() => resolveConfirm(false)}
    >
      <div
        className="win-modal w-full max-w-md p-5"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
      >
        <h3
          id="confirm-dialog-title"
          className="text-base font-semibold text-text-primary dark:text-text-dark-primary"
        >
          {request.title}
        </h3>
        {request.description ? (
          <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-text-secondary dark:text-text-dark-secondary">
            {request.description}
          </p>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => resolveConfirm(false)}
            className="win-button h-9 px-4 text-sm"
          >
            {request.cancelLabel}
          </button>
          <button
            type="button"
            onClick={() => resolveConfirm(true)}
            className={clsx(
              'inline-flex h-9 items-center justify-center rounded-md px-4 text-sm font-medium text-white shadow-sm transition-colors',
              request.tone === 'danger'
                ? 'bg-red-500 hover:bg-red-600'
                : 'bg-primary hover:bg-primary/90',
            )}
          >
            {request.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
