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
    read_count: 0,
    status: 'sent',
    attachment: null,
    edited_at: null,
    deleted: false,
    reactions: [],
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
        isGroup={false}
        memberNames={{}}
        canLoadMore={false}
        onLoadMore={vi.fn()}
        onSend={vi.fn()}
        onRetry={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onReact={vi.fn()}
        attachmentUrl={(id) => 'http://api/attachments/' + id}
        onUpload={vi.fn()}
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
        isGroup={false}
        memberNames={{}}
        canLoadMore={false}
        onLoadMore={vi.fn()}
        onSend={vi.fn()}
        onRetry={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onReact={vi.fn()}
        attachmentUrl={(id) => 'http://api/attachments/' + id}
        onUpload={vi.fn()}
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
        isGroup={false}
        memberNames={{}}
        canLoadMore={false}
        onLoadMore={vi.fn()}
        onSend={vi.fn()}
        onRetry={onRetry}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onReact={vi.fn()}
        attachmentUrl={(id) => 'http://api/attachments/' + id}
        onUpload={vi.fn()}
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
        isGroup={false}
        memberNames={{}}
        canLoadMore={false}
        onLoadMore={vi.fn()}
        onSend={onSend}
        onRetry={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onReact={vi.fn()}
        attachmentUrl={(id) => 'http://api/attachments/' + id}
        onUpload={vi.fn()}
      />,
    );
    const input = screen.getByLabelText('訊息輸入') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '在嗎' } });
    fireEvent.click(screen.getByRole('button', { name: '送出' }));
    expect(onSend).toHaveBeenCalledWith('在嗎', undefined);
    expect(input.value).toBe('');
  });

  it('群組顯示寄件人名字與已讀 N', () => {
    render(
      <Thread
        title="家族群" isGroup memberNames={{ u2: 'Bob' }}
        messages={[
          msg({ id: 'm1', sender_id: 'u2', content: '嗨' }),               // 別人 → 顯示名字
          msg({ id: 'm2', sender_id: 'me', content: '哈', read_count: 2 }), // 自己 → 已讀 2
        ]}
        currentUserId="me" canLoadMore={false}
        onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
        onEdit={vi.fn()} onDelete={vi.fn()} onReact={vi.fn()}
        attachmentUrl={(id) => 'http://api/attachments/' + id}
        onUpload={vi.fn()}
      />,
    );
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('已讀 2')).toBeInTheDocument();
  });

  it('圖片附件渲染 img、檔案附件渲染下載連結', () => {
    render(
      <Thread
        title="Bob" isGroup={false} memberNames={{}}
        attachmentUrl={(id) => `http://api/attachments/${id}`}
        messages={[
          msg({ id: 'm1', attachment: { id: 'img1', original_name: 'p.png', content_type: 'image/png', size: 3, is_image: true } }),
          msg({ id: 'm2', attachment: { id: 'doc1', original_name: 'r.pdf', content_type: 'application/pdf', size: 9, is_image: false } }),
        ]}
        currentUserId="me" canLoadMore={false}
        onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
        onEdit={vi.fn()} onDelete={vi.fn()} onReact={vi.fn()}
        onUpload={vi.fn()}
      />,
    );
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('src', 'http://api/attachments/img1');
    const imgLink = img.closest('a');
    expect(imgLink).toHaveAttribute('href', 'http://api/attachments/img1');
    const link = screen.getByRole('link', { name: /r\.pdf/ });
    expect(link).toHaveAttribute('href', 'http://api/attachments/doc1');
  });

  it('已編輯顯示標記、已刪除顯示佔位', () => {
    render(
      <Thread title="Bob" isGroup={false} memberNames={{}}
        attachmentUrl={(id) => id}
        messages={[
          msg({ id: 'm1', content: 'hi', edited_at: '2026-06-20T00:00:00Z' }),
          msg({ id: 'm2', deleted: true, content: '' }),
        ]}
        currentUserId="me" canLoadMore={false}
        onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
        onEdit={vi.fn()} onDelete={vi.fn()} onReact={vi.fn()} onUpload={vi.fn()} />,
    );
    expect(screen.getByText('已編輯')).toBeInTheDocument();
    expect(screen.getByText('此訊息已刪除')).toBeInTheDocument();
  });

  it('表情 chip 高亮並可 toggle', () => {
    const onReact = vi.fn();
    render(
      <Thread title="Bob" isGroup={false} memberNames={{}}
        attachmentUrl={(id) => id}
        messages={[msg({ id: 'm1', reactions: [{ emoji: '👍', count: 1, user_ids: ['me'] }] })]}
        currentUserId="me" canLoadMore={false}
        onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
        onEdit={vi.fn()} onDelete={vi.fn()} onReact={onReact} onUpload={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /👍 1/ }));
    expect(onReact).toHaveBeenCalledWith('m1', '👍');
  });

  it('自己的訊息可刪除', () => {
    const onDelete = vi.fn();
    render(
      <Thread title="Bob" isGroup={false} memberNames={{}}
        attachmentUrl={(id) => id}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'mine' })]}
        currentUserId="me" canLoadMore={false}
        onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
        onEdit={vi.fn()} onDelete={onDelete} onReact={vi.fn()} onUpload={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '刪除' }));
    expect(onDelete).toHaveBeenCalledWith('m1');
  });

  it('系統訊息置中渲染、無泡泡動作', () => {
    render(
      <Thread
        title="G" isGroup memberNames={{}}
        messages={[msg({ id: 's1', sender_id: 'u-actor', content: 'Alice 把 Bob 加入群組', kind: 'system' as const })]}
        currentUserId="me" canLoadMore={false}
        onLoadMore={vi.fn()} onSend={vi.fn()} onRetry={vi.fn()}
        onEdit={vi.fn()} onDelete={vi.fn()} onReact={vi.fn()}
        attachmentUrl={(id) => 'http://api/attachments/' + id}
        onUpload={vi.fn()}
      />,
    );
    expect(screen.getByText('Alice 把 Bob 加入群組')).toBeInTheDocument();
    // 系統訊息不應出現「編輯 / 刪除」泡泡動作
    expect(screen.queryByRole('button', { name: '編輯' })).toBeNull();
  });
});
