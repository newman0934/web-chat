// shell 全域 auth hook：保管 JWT、驗證 token 並載入 currentUser。

import { useCallback, useEffect, useState } from 'react';

import type { CurrentUser } from '../../contracts';
import { API_BASE_URL, TOKEN_STORAGE_KEY } from './config';

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated';

export interface AuthState {
  status: AuthStatus;
  token: string | null;
  currentUser: CurrentUser | null;
  login: (token: string) => void;
  logout: () => void;
}

/** shell 全域 auth 狀態：保管 JWT、載入 currentUser、登入/登出。 */
export function useAuth(): AuthState {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(TOKEN_STORAGE_KEY),
  );
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>(token ? 'loading' : 'unauthenticated');

  /** 清除 localStorage 與記憶體中的登入狀態。 */
  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
    setCurrentUser(null);
    setStatus('unauthenticated');
  }, []);

  /** 保存新 token 並觸發 /users/me 驗證以載入 currentUser。 */
  const login = useCallback((newToken: string) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, newToken);
    setToken(newToken);
    setStatus('loading');
  }, []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    // token 存在時呼叫 /users/me 驗證並載入使用者；失敗則 logout。
    (async () => {
      try {
        const resp = await fetch(`${API_BASE_URL}/users/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) throw new Error('token invalid');
        const user = (await resp.json()) as CurrentUser;
        if (cancelled) return; // 元件已卸載 / token 已變，丟棄這次結果
        setCurrentUser(user);
        setStatus('authenticated');
      } catch {
        if (!cancelled) logout(); // token 失效 → 清狀態導回登入
      }
    })();

    // cancelled 旗標避免過期請求覆寫較新的狀態（含 StrictMode 重跑 effect）。
    return () => {
      cancelled = true;
    };
  }, [token, logout]);

  return { status, token, currentUser, login, logout };
}
