import { create } from 'zustand';

type ConfirmTone = 'default' | 'danger';

export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: ConfirmTone;
}

interface ConfirmRequest extends ConfirmOptions {
  id: string;
  resolve: (value: boolean) => void;
}

interface ConfirmState {
  request: ConfirmRequest | null;
  openConfirm: (options: ConfirmOptions) => Promise<boolean>;
  resolveConfirm: (value: boolean) => void;
}

export const useConfirmStore = create<ConfirmState>()((set, get) => ({
  request: null,
  openConfirm: (options) => new Promise<boolean>((resolve) => {
    const id = globalThis.crypto?.randomUUID?.() ?? `confirm-${Date.now()}-${Math.random()}`;
    set({
      request: {
        id,
        resolve,
        title: options.title,
        description: options.description,
        confirmLabel: options.confirmLabel ?? '确认',
        cancelLabel: options.cancelLabel ?? '取消',
        tone: options.tone ?? 'default',
      },
    });
  }),
  resolveConfirm: (value) => {
    const current = get().request;
    if (!current) return;
    current.resolve(value);
    set({ request: null });
  },
}));
