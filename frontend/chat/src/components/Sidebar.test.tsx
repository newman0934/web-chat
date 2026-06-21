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
});
