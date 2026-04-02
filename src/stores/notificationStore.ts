import { create } from 'zustand';

export type NotificationTone = 'success' | 'error' | 'info';

export interface NotificationItem {
  id: string;
  message: string;
  tone: NotificationTone;
  durationMs?: number;
}

interface NotificationState {
  notifications: NotificationItem[];
  pushNotification: (input: Omit<NotificationItem, 'id'>) => string;
  dismissNotification: (id: string) => void;
  clearNotifications: () => void;
}

export const useNotificationStore = create<NotificationState>()((set, get) => ({
  notifications: [],
  pushNotification: (input) => {
    const id = globalThis.crypto?.randomUUID?.() ?? `notice-${Date.now()}-${Math.random()}`;
    const item: NotificationItem = { id, ...input };

    set((state) => ({
      notifications: [...state.notifications, item],
    }));

    const durationMs = input.durationMs ?? 5000;
    if (durationMs > 0) {
      window.setTimeout(() => {
        const current = get().notifications;
        if (current.some((entry) => entry.id === id)) {
          get().dismissNotification(id);
        }
      }, durationMs);
    }

    return id;
  },
  dismissNotification: (id) => set((state) => ({
    notifications: state.notifications.filter((item) => item.id !== id),
  })),
  clearNotifications: () => set({ notifications: [] }),
}));
