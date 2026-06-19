import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AuthApp from './AuthApp';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AuthApp', () => {
  it('用無效 email 不會送出，並顯示驗證錯誤', () => {
    const onAuthSuccess = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<AuthApp apiBaseUrl="http://api" onAuthSuccess={onAuthSuccess} />);

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'not-an-email' },
    });
    fireEvent.change(screen.getByLabelText('密碼'), {
      target: { value: 'secret123' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登入' }));

    expect(screen.getByText('請輸入有效的 email')).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(onAuthSuccess).not.toHaveBeenCalled();
  });

  it('短密碼顯示錯誤', () => {
    render(<AuthApp apiBaseUrl="http://api" onAuthSuccess={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'a@b.com' },
    });
    fireEvent.change(screen.getByLabelText('密碼'), { target: { value: '123' } });
    fireEvent.click(screen.getByRole('button', { name: '登入' }));
    expect(screen.getByText('密碼至少 6 碼')).toBeInTheDocument();
  });

  it('登入成功後呼叫 onAuthSuccess 並帶回 token', async () => {
    const onAuthSuccess = vi.fn();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ access_token: 'jwt-123' }), { status: 200 }),
    );
    render(<AuthApp apiBaseUrl="http://api" onAuthSuccess={onAuthSuccess} />);

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'a@b.com' },
    });
    fireEvent.change(screen.getByLabelText('密碼'), {
      target: { value: 'secret123' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登入' }));

    await waitFor(() => expect(onAuthSuccess).toHaveBeenCalledWith('jwt-123'));
  });

  it('後端錯誤時顯示 detail 訊息', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'email 或密碼錯誤' }), { status: 401 }),
    );
    render(<AuthApp apiBaseUrl="http://api" onAuthSuccess={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'a@b.com' },
    });
    fireEvent.change(screen.getByLabelText('密碼'), {
      target: { value: 'secret123' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登入' }));

    expect(await screen.findByText('email 或密碼錯誤')).toBeInTheDocument();
  });
});
