import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { GroupInfoPanel } from './GroupInfoPanel';
import type { Conversation } from '../../../contracts';

function makeConv(roles: Record<string, 'admin' | 'member'>): Conversation {
  return {
    id: 'c1', type: 'group', name: 'G', other_user: null,
    members: [
      { id: 'a', email: 'a@x.com', display_name: 'Alice' },
      { id: 'b', email: 'b@x.com', display_name: 'Bob' },
    ],
    last_message: null, unread_count: 0, roles,
  };
}

const handlers = {
  contacts: [], onAddMember: vi.fn(), onRemoveMember: vi.fn(),
  onSetRole: vi.fn(), onRename: vi.fn(), onLeave: vi.fn(), onClose: vi.fn(),
};

describe('GroupInfoPanel', () => {
  it('admin 看到改名與管理控制', () => {
    render(<GroupInfoPanel conversation={makeConv({ a: 'admin', b: 'member' })} currentUserId="a" {...handlers} />);
    expect(screen.getByLabelText('群組名稱')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '移除 Bob' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '退出群組' })).toBeInTheDocument();
  });

  it('一般成員只見唯讀成員列與退出', () => {
    render(<GroupInfoPanel conversation={makeConv({ a: 'admin', b: 'member' })} currentUserId="b" {...handlers} />);
    expect(screen.queryByLabelText('群組名稱')).toBeNull();
    expect(screen.queryByRole('button', { name: '移除 Alice' })).toBeNull();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '退出群組' })).toBeInTheDocument();
  });
});
