import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Conversation } from '../../../contracts';
import { Sidebar } from './Sidebar';

const groupConv: Conversation = {
  id: 'g1', type: 'group', name: '家族群', other_user: null,
  members: [
    { id: 'u1', email: 'a@x.com', display_name: 'A' },
    { id: 'u2', email: 'b@x.com', display_name: 'B' },
    { id: 'u3', email: 'c@x.com', display_name: 'C' },
  ],
  last_message: null, unread_count: 0, roles: {},
};

function renderSidebar(over = {}) {
  return render(
    <Sidebar
      conversations={[groupConv]} activeId={null} currentUserName="A"
      socketStatus="open" contacts={[]}
      onSelect={vi.fn()} onAddContact={vi.fn()} onCreateGroup={vi.fn()} onLogout={vi.fn()}
      {...over}
    />,
  );
}

const directConv: Conversation = {
  id: 'd1', type: 'direct', name: null,
  other_user: { id: 'u2', email: 'b@x.com', display_name: 'Bob' },
  members: [], last_message: null, unread_count: 0, roles: {},
};

describe('Sidebar 群組', () => {
  it('群組顯示名稱與成員數', () => {
    renderSidebar();
    expect(screen.getByText('家族群')).toBeInTheDocument();
    expect(screen.getByText(/3 人/)).toBeInTheDocument();
  });

  it('點新群組展開建群面板', () => {
    renderSidebar();
    fireEvent.click(screen.getByRole('button', { name: /新群組/ }));
    expect(screen.getByLabelText('群組名稱')).toBeInTheDocument();
  });

  it('群組對話列不顯示 presence 點', () => {
    renderSidebar();
    expect(screen.queryByTestId('presence-dot')).toBeNull();
  });
});

describe('Sidebar presence 點(1對1)', () => {
  it('好友在線顯示綠點(data-online=true)', () => {
    renderSidebar({
      conversations: [directConv],
      presence: { u2: { online: true, last_seen_at: null } },
    });
    expect(screen.getByTestId('presence-dot').getAttribute('data-online')).toBe('true');
  });

  it('好友離線顯示灰點(data-online=false)', () => {
    renderSidebar({
      conversations: [directConv],
      presence: { u2: { online: false, last_seen_at: '2026-06-23T00:00:00Z' } },
    });
    expect(screen.getByTestId('presence-dot').getAttribute('data-online')).toBe('false');
  });

  it('presence 缺漏時預設灰點', () => {
    renderSidebar({ conversations: [directConv] });
    expect(screen.getByTestId('presence-dot').getAttribute('data-online')).toBe('false');
  });
});
