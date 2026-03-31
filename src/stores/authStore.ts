/**
 * 认证状态管理 (Zustand)
 * 管理：登录/登出、JWT token 持久化、当前用户信息
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '@/types';
import { login as apiLogin, getMe } from '@/services/api';

const AUTH_STORAGE_KEY = 'CPSC AI 中台 智枢-auth';

interface AuthState {
  /** 当前登录用户 */
  user: User | null;
  /** JWT token */
  token: string | null;
  /** 是否已完成初始化检查 */
  initialized: boolean;

  /** 登录 */
  login: (username: string, password: string) => Promise<void>;
  /** 登出 */
  logout: () => void;
  /** 初始化：用已有 token 校验登录状态 */
  init: () => Promise<void>;

  /** 便捷判断 */
  isAdmin: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      initialized: false,

      login: async (username, password) => {
        const resp = await apiLogin(username, password);
        set({ user: resp.user, token: resp.token });
      },

      logout: () => {
        set({ user: null, token: null });
      },

      init: async () => {
        const { token } = get();
        if (!token) {
          set({ initialized: true });
          return;
        }
        try {
          const user = await getMe();
          set({ user, initialized: true });
        } catch {
          // token 无效，清除
          set({ user: null, token: null, initialized: true });
        }
      },

      isAdmin: () => get().user?.system_role === 'admin',
    }),
    {
      name: AUTH_STORAGE_KEY,
      partialize: (state) => ({
        token: state.token,
        user: state.user,
      }),
    }
  )
);

