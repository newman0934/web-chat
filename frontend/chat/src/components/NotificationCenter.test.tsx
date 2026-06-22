import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { NotificationCenter } from './NotificationCenter';
import type { Notification } from '../../../contracts';

function notif(id: string, over: Partial<Notification> = {}): Notification {
  return {
    id,
    type: 'reply',
    actor: { id: 'a1', display_name: 'Alice' },
    conversation_id: 'c1',
    message_id: 'm1',
    message_preview: '原文摘要',
    emoji: null,
    read: false,
    created_at: '2026-06-22T00:00:00Z',
    ...over,
  };
}

describe('NotificationCenter', () => {
  it('未讀數顯示在鈴鐺紅點(>9 顯示 9+)', () => {
    render(<NotificationCenter notifications={[]} unreadCount={12} onOpen={vi.fn()} />);
    expect(screen.getByTestId('notif-badge')).toHaveTextContent('9+');
  });

  it('未讀為 0 時不顯示紅點', () => {
    render(<NotificationCenter notifications={[]} unreadCount={0} onOpen={vi.fn()} />);
    expect(screen.queryByTestId('notif-badge')).toBeNull();
  });

  it('展開後列出通知(actor + 文案 + 摘要)', async () => {
    const user = userEvent.setup();
    render(
      <NotificationCenter
        notifications={[notif('1', { type: 'reaction', emoji: '👍' })]}
        unreadCount={1}
        onOpen={vi.fn()}
      />,
    );
    await user.click(screen.getByRole('button', { name: '通知' }));
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText(/按了 👍/)).toBeInTheDocument();
    expect(screen.getByText('原文摘要')).toBeInTheDocument();
  });

  it('點一筆通知呼叫 onOpen 並帶該通知', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const n = notif('1');
    render(<NotificationCenter notifications={[n]} unreadCount={1} onOpen={onOpen} />);
    await user.click(screen.getByRole('button', { name: '通知' }));
    await user.click(screen.getByText(/回覆了你/));
    expect(onOpen).toHaveBeenCalledWith(n);
  });

  it('沒有通知時顯示空狀態', async () => {
    const user = userEvent.setup();
    render(<NotificationCenter notifications={[]} unreadCount={0} onOpen={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: '通知' }));
    expect(screen.getByText('目前沒有通知')).toBeInTheDocument();
  });
});
