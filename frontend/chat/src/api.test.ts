import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from './api';

afterEach(() => vi.restoreAllMocks());

describe('ApiClient.getMessageEdits', () => {
  it('打 GET /messages/{id}/edits 並回傳版本陣列', async () => {
    const versions = [
      { content: 'v1', created_at: '2026-06-21T00:00:00Z' },
      { content: 'v2', created_at: '2026-06-21T00:05:00Z' },
    ];
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(versions), { status: 200 }),
    );
    const api = new ApiClient('http://api', 'tok');
    const got = await api.getMessageEdits('m1');
    expect(got).toEqual(versions);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://api/messages/m1/edits',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer tok' }) }),
    );
  });
});
