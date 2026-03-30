/**
 * 登录页面
 */
import { useState, type FormEvent } from 'react';
import { useAuthStore } from '@/stores/authStore';

export default function LoginPage() {
  const login = useAuthStore((s) => s.login);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);
    } catch (err) {
      setError((err as Error).message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-surface-sidebar dark:bg-dark">
      <form
        onSubmit={(e) => void handleSubmit(e)}
        className="w-full max-w-sm space-y-5 rounded-xl border border-surface-divider bg-white p-8 shadow-lg dark:border-dark-divider dark:bg-dark-card"
      >
        <div className="text-center">
          <span className="text-3xl">🍒</span>
          <h1 className="mt-2 text-xl font-semibold text-text-primary dark:text-text-dark-primary">
            Meeting Assistant
          </h1>
          <p className="mt-1 text-sm text-text-secondary">请登录以继续</p>
        </div>

        {error && (
          <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
            {error}
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-text-primary dark:text-text-dark-primary">
              用户名
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              className="w-full rounded-md border border-surface-divider bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-primary"
              placeholder="请输入用户名"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-text-primary dark:text-text-dark-primary">
              密码
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full rounded-md border border-surface-divider bg-white px-3 py-2 text-sm focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 dark:border-dark-divider dark:bg-dark-sidebar dark:text-text-dark-primary"
              placeholder="请输入密码"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={loading || !username || !password}
          className="win-button-primary w-full py-2.5 disabled:opacity-50"
        >
          {loading ? '登录中...' : '登 录'}
        </button>
      </form>
    </div>
  );
}

