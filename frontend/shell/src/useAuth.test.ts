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
});
