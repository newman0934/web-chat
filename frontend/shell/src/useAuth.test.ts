import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TOKEN_STORAGE_KEY } from './config';
import { useAuth } from './useAuth';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useAuth', () => {
  it('無 token 時為 unauthenticated', () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current.status).toBe('unauthenticated');
    expect(result.current.currentUser).toBeNull();
  });

  it('login 後抓取 currentUser 並轉為 authenticated', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ id: 'u1', email: 'a@b.com', display_name: 'Alice' }),
        { status: 200 },
      ),
    );
    const { result } = renderHook(() => useAuth());

    act(() => result.current.login('jwt-1'));

    await waitFor(() => expect(result.current.status).toBe('authenticated'));
    expect(result.current.currentUser?.display_name).toBe('Alice');
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('jwt-1');
  });

  it('token 無效時自動 logout', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 401 }));
    localStorage.setItem(TOKEN_STORAGE_KEY, 'bad');
    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.status).toBe('unauthenticated'));
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it('啟動時若 localStorage 已有 token，初始為 loading（驗證中）', () => {
    // fetch 停在 pending，狀態應卡在 loading 而非提早判定。
    vi.spyOn(globalThis, 'fetch').mockReturnValue(new Promise(() => {}));
    localStorage.setItem(TOKEN_STORAGE_KEY, 'existing');
    const { result } = renderHook(() => useAuth());
    expect(result.current.status).toBe('loading');
    expect(result.current.currentUser).toBeNull();
  });

  it('以 Bearer token 呼叫 /users/me', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ id: 'u1', email: 'a@b.com', display_name: 'Alice' }),
        { status: 200 },
      ),
    );
    const { result } = renderHook(() => useAuth());

    act(() => result.current.login('jwt-x'));

    await waitFor(() => expect(result.current.status).toBe('authenticated'));
    expect(spy).toHaveBeenCalledWith('http://localhost:8000/users/me', {
      headers: { Authorization: 'Bearer jwt-x' },
    });
  });

  it('fetch 失敗（網路錯誤）也會 logout', async () => {
    // 非 401，而是 fetch 直接 reject（網路斷線等），仍應走 catch → logout。
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network down'));
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    const { result } = renderHook(() => useAuth());

    await waitFor(() => expect(result.current.status).toBe('unauthenticated'));
    expect(result.current.currentUser).toBeNull();
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it('logout 後清空 token、currentUser 與 localStorage', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ id: 'u1', email: 'a@b.com', display_name: 'Alice' }),
        { status: 200 },
      ),
    );
    const { result } = renderHook(() => useAuth());
    act(() => result.current.login('jwt-1'));
    await waitFor(() => expect(result.current.status).toBe('authenticated'));

    act(() => result.current.logout());

    expect(result.current.status).toBe('unauthenticated');
    expect(result.current.token).toBeNull();
    expect(result.current.currentUser).toBeNull();
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it('token 變更後，舊 token 的過期回應不覆寫新狀態（cancelled 旗標）', async () => {
    // 依 Authorization header 分別保留各自的 resolve，藉此控制回應順序。
    const resolvers: Record<string, (r: Response) => void> = {};
    vi.spyOn(globalThis, 'fetch').mockImplementation((_url, opts) => {
      const auth = (opts as RequestInit).headers as Record<string, string>;
      return new Promise<Response>((resolve) => {
        resolvers[auth.Authorization] = resolve;
      });
    });

    localStorage.setItem(TOKEN_STORAGE_KEY, 'old');
    const { result } = renderHook(() => useAuth());

    // token 還在驗證中就換成新 token（觸發 effect cleanup → 舊請求被標記 cancelled）。
    act(() => result.current.login('new'));

    // 先回舊 token 的結果（已過期，應被丟棄），再回新 token 的結果。
    await act(async () => {
      resolvers['Bearer old'](
        new Response(JSON.stringify({ id: 'old', email: 'o@b.com', display_name: 'OldUser' }), {
          status: 200,
        }),
      );
    });
    await act(async () => {
      resolvers['Bearer new'](
        new Response(JSON.stringify({ id: 'new', email: 'n@b.com', display_name: 'NewUser' }), {
          status: 200,
        }),
      );
    });

    await waitFor(() => expect(result.current.status).toBe('authenticated'));
    // 應採用新 token 的結果，而非過期的舊結果。
    expect(result.current.currentUser?.display_name).toBe('NewUser');
  });
});
