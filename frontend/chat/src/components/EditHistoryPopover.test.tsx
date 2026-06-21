import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { EditHistoryPopover } from './EditHistoryPopover';

describe('EditHistoryPopover', () => {
  it('載入並逐版列出，最後一筆標（目前）', async () => {
    const load = vi.fn().mockResolvedValue([
      { content: '舊文', created_at: '2026-06-21T00:00:00Z' },
      { content: '新文', created_at: '2026-06-21T00:05:00Z' },
    ]);
    render(<EditHistoryPopover messageId="m1" load={load} onClose={vi.fn()} />);
    expect(await screen.findByText('舊文')).toBeInTheDocument();
    expect(screen.getByText('新文')).toBeInTheDocument();
    expect(screen.getByText(/（目前）/)).toBeInTheDocument();
  });

  it('載入失敗顯示錯誤', async () => {
    const load = vi.fn().mockRejectedValue(new Error('x'));
    render(<EditHistoryPopover messageId="m1" load={load} onClose={vi.fn()} />);
    expect(await screen.findByText('載入失敗')).toBeInTheDocument();
  });
});
