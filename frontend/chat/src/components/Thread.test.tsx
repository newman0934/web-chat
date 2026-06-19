import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ChatMessage } from '../messageStore';
import { Thread } from './Thread';

function msg(over: Partial<ChatMessage>): ChatMessage {
  return {
    id: 'm1',
    conversation_id: 'c1',
    sender_id: 'me',
    content: 'hello',
    created_at: '2026-06-19T00:00:00Z',
    read_at: null,
    status: 'sent',
    ...over,
  };
}

describe('Thread', () => {
  it('渲染訊息內容與標題', () => {
    render(
      <Thread
        title="Bob"
        messages={[msg({ content: '哈囉' })]}
        currentUserId="me"
        canLoadMore={false}
        onLoadMore={vi.fn()}
        onSend={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('哈囉')).toBeInTheDocument();
  });

  it('我方 sending 訊息顯示「傳送中…」', () => {
    render(
      <Thread
        title="Bob"
        messages={[msg({ status: 'sending' })]}
        currentUserId="me"
        canLoadMore={false}
        onLoadMore={vi.fn()}
        onSend={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText('傳送中…')).toBeInTheDocument();
  });

  it('failed 訊息可點擊重試', () => {
    const onRetry = vi.fn();
    render(
      <Thread
        title="Bob"
        messages={[msg({ status: 'failed', temp_id: 'tmp-9' })]}
        currentUserId="me"
        canLoadMore={false}
        onLoadMore={vi.fn()}
        onSend={vi.fn()}
        onRetry={onRetry}
      />,
    );
    fireEvent.click(screen.getByText('未送出，點擊重試'));
    expect(onRetry).toHaveBeenCalledWith('tmp-9');
  });

  it('送出後呼叫 onSend 並清空輸入', () => {
    const onSend = vi.fn();
    render(
      <Thread
        title="Bob"
        messages={[]}
        currentUserId="me"
        canLoadMore={false}
        onLoadMore={vi.fn()}
        onSend={onSend}
        onRetry={vi.fn()}
      />,
    );
    const input = screen.getByLabelText('訊息輸入') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '在嗎' } });
    fireEvent.click(screen.getByRole('button', { name: '送出' }));
    expect(onSend).toHaveBeenCalledWith('在嗎');
    expect(input.value).toBe('');
  });
});
