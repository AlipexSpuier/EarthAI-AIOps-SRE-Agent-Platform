import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api, ApiError, errorMessage } from '../lib/api';
import type { ChatPreferences, User } from '../types';

interface AuthState {
  user: User | null; loading: boolean; error: string;
  login: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => Promise<void>; update: (values: Partial<User>) => Promise<User>; retry: () => Promise<void>;
  loadChatPreferences: () => Promise<ChatPreferences>;
  saveChatPreferences: (values: Partial<ChatPreferences>) => Promise<ChatPreferences>;
}
const AuthContext = createContext<AuthState | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const account = useRef(user?.id);
  account.current = user?.id;
  const saves = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(new Set<{ owner: string; values: Partial<ChatPreferences> }>());
  const saveChatPreferences = useCallback((values: Partial<ChatPreferences>) => {
    const owner = account.current;
    if (!owner) return Promise.reject(new Error('请先登录'));
    const item = { owner, values: { ...values } };
    pending.current.add(item);
    const result = saves.current.catch(() => undefined).then(async () => {
      if (account.current !== owner) throw new Error('账户已切换，未保存旧账户配置');
      const response = await fetch('/api/preferences/chat', {
        method: 'PATCH', credentials: 'same-origin', keepalive: true,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(item.values),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null;
        if (response.status === 401) window.dispatchEvent(new Event('earthai:unauthorized'));
        throw new ApiError(typeof body?.detail === 'string' ? body.detail : `请求失败（${response.status}）`, response.status);
      }
      return response.json() as Promise<ChatPreferences>;
    }).finally(() => { pending.current.delete(item); });
    saves.current = result;
    return result;
  }, []);
  const loadChatPreferences = useCallback(async () => {
    const owner = account.current;
    await saves.current.catch(() => undefined);
    if (!owner || account.current !== owner) throw new Error('账户已切换，请重新加载配置');
    return api.get<ChatPreferences>('/preferences/chat');
  }, []);
  useEffect(() => {
    const flush = () => {
      const values = Object.assign({}, ...[...pending.current].filter(item => item.owner === account.current).map(item => item.values)) as Partial<ChatPreferences>;
      if (Object.keys(values).length) void fetch('/api/preferences/chat', {
        method: 'PATCH', credentials: 'same-origin', keepalive: true,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values),
      }).catch(() => undefined);
    };
    window.addEventListener('pagehide', flush);
    return () => window.removeEventListener('pagehide', flush);
  }, []);
  const retry = useCallback(async () => {
    setLoading(true); setError('');
    try { setUser(await api.get<User>('/auth/me')); }
    catch (err) { if (!(err instanceof ApiError && err.status === 401)) setError(errorMessage(err)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void retry(); const unauthorized = () => setUser(null); window.addEventListener('earthai:unauthorized', unauthorized); return () => window.removeEventListener('earthai:unauthorized', unauthorized); }, [retry]);
  useEffect(() => {
    let active = true;
    let refreshing = false;
    const refresh = async () => {
      const owner = account.current;
      if (!owner || refreshing) return;
      refreshing = true;
      try {
        const next = await api.get<User>('/auth/me');
        if (active && account.current === owner) setUser(next);
      } catch (err) {
        if (active && account.current === owner && err instanceof ApiError && err.status === 401) setUser(null);
      } finally { refreshing = false; }
    };
    const focus = () => { void refresh(); };
    const visible = () => { if (document.visibilityState === 'visible') void refresh(); };
    window.addEventListener('focus', focus);
    document.addEventListener('visibilitychange', visible);
    window.addEventListener('earthai:permissions-refresh', focus);
    return () => {
      active = false;
      window.removeEventListener('focus', focus);
      document.removeEventListener('visibilitychange', visible);
      window.removeEventListener('earthai:permissions-refresh', focus);
    };
  }, []);
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const theme = user?.theme || 'light';
    const apply = () => { document.documentElement.dataset.theme = theme === 'system' ? query.matches ? 'dark' : 'light' : theme; };
    apply(); query.addEventListener('change', apply); return () => query.removeEventListener('change', apply);
  }, [user?.theme]);
  const login = async (email: string, password: string, name?: string) => {
    setUser(await api.post<User>(name === undefined ? '/auth/login' : '/auth/register', { email, password, ...(name === undefined ? {} : { name }) }));
  };
  const logout = async () => { await saves.current.catch(() => undefined); await api.post('/auth/logout'); setUser(null); };
  const update = async (values: Partial<User>) => { const result = await api.patch<User>('/auth/me', values); setUser(result); return result; };
  return <AuthContext.Provider value={{ user, loading, error, login, logout, update, retry, loadChatPreferences, saveChatPreferences }}>{children}</AuthContext.Provider>;
}
export function useAuth() { const value = useContext(AuthContext); if (!value) throw new Error('AuthProvider is required'); return value; }
