import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Conversation } from '../../../contracts';
import { ForwardPicker } from './ForwardPicker';

function makeConv(over: Partial<Conversation>): Conversation {
  return {
    id: 'conv-1',
    type: 'direct',
    name: null,
    other_user: null,
    members: [],
    last_message: null,
    unread_count: 0,
    roles: {},
    ...over,
  };
}

const directConv = makeConv({
  id: 'c-direct',
  type: 'direct',
  other_user: { id: 'u2', email: 'bob@example.com', display_name: 'Bob' },
});

const groupConv = makeConv({
  id: 'c-group',
  type: 'group',
  name: '家族群',
});

const groupNoName = makeConv({
  id: 'c-group-noname',
  type: 'group',
  name: null,
});

describe('ForwardPicker', () => {
  it('列出 direct 對話，顯示 other_user.display_name', () => {
    render(
      <ForwardPicker
        conversations={[directConv]}
        onPick={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('Bob')).toBeInTheDocument();
  });

  it('列出 group 對話，顯示 name', () => {
    render(
      <ForwardPicker
        conversations={[groupConv]}
        onPick={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('家族群')).toBeInTheDocument();
  });

  it('group 沒有 name 時顯示「群組」', () => {
    render(
      <ForwardPicker
        conversations={[groupNoName]}
        onPick={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText('群組')).toBeInTheDocument();
  });

  it('點擊對話列呼叫 onPick(conv.id)', () => {
    const onPick = vi.fn();
    render(
      <ForwardPicker
        conversations={[directConv, groupConv]}
        onPick={onPick}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText('Bob'));
    expect(onPick).toHaveBeenCalledWith('c-direct');
  });

  it('點擊群組列呼叫 onPick(conv.id)', () => {
    const onPick = vi.fn();
    render(
      <ForwardPicker
        conversations={[directConv, groupConv]}
        onPick={onPick}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText('家族群'));
    expect(onPick).toHaveBeenCalledWith('c-group');
  });

  it('點擊 ✕ 按鈕呼叫 onClose', () => {
    const onClose = vi.fn();
    render(
      <ForwardPicker
        conversations={[directConv]}
        onPick={vi.fn()}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '關閉' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('點擊 backdrop 呼叫 onClose', () => {
    const onClose = vi.fn();
    const { container } = render(
      <ForwardPicker
        conversations={[directConv]}
        onPick={vi.fn()}
        onClose={onClose}
      />,
    );
    // backdrop 是最外層 div
    const backdrop = container.querySelector('[data-testid="forward-picker-backdrop"]');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalled();
  });
});
