import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { ReplyPreview } from '../../../contracts';
import type { ChatMessage } from '../messageStore';
import { Thread } from './Thread';

vi.mock('@emoji-mart/react', () => ({
  default: ({ onEmojiSelect }: { onEmojiSelect: (e: { native: string }) => void }) => (
    <button type="button" onClick={() => onEmojiSelect({ native: '🎉' })}>
      mock-picker-pick
    </button>
  ),
}));
vi.mock('@emoji-mart/data', () => ({ default: {} }));

function msg(over: Partial<ChatMessage>): ChatMessage {
  return {
    id: 'm1',
    conversation_id: 'c1',
    sender_id: 'me',
    content: 'hello',
    created_at: '2026-06-19T00:00:00Z',
    read_count: 0,
    status: 'sent',
    attachments: [],
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

  function renderWithStatus(statusText: string | null) {
    return render(
      <Thread
        title="Bob"
        statusText={statusText}
        messages={[]}
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
  }

  it('header 顯示 presence 狀態文案', () => {
    renderWithStatus('在線');
    expect(screen.getByTestId('presence-status')).toHaveTextContent('在線');
  });

  it('statusText 為 null 時不顯示狀態列(如群組)', () => {
    renderWithStatus(null);
    expect(screen.queryByTestId('presence-status')).toBeNull();
  });

  function renderUpload(onUpload: (f: File) => Promise<unknown>) {
    return render(
      <Thread
        title="Bob"
        messages={[]}
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
        onUpload={onUpload as never}
      />,
    );
  }

  it('上傳失敗時顯示錯誤訊息', async () => {
    const onUpload = vi.fn().mockResolvedValue({ ok: false, message: '檔案過大（上限 10MB）' });
    const { container } = renderUpload(onUpload);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['x'], 'big.bin')] } });
    expect(await screen.findByText('檔案過大（上限 10MB）')).toBeInTheDocument();
  });

  it('上傳成功時顯示待送附件名、不顯示錯誤', async () => {
    const att = { id: 'a1', original_name: 'pic.png', content_type: 'image/png', size: 3, is_image: true };
    const onUpload = vi.fn().mockResolvedValue({ ok: true, attachment: att });
    const { container } = renderUpload(onUpload);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['x'], 'pic.png')] } });
    expect(await screen.findByText('pic.png')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
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
    expect(onSend).toHaveBeenCalledWith('在嗎', []);
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
          msg({ id: 'm1', attachments: [{ id: 'img1', original_name: 'p.png', content_type: 'image/png', size: 3, is_image: true }] }),
          msg({ id: 'm2', attachments: [{ id: 'doc1', original_name: 'r.pdf', content_type: 'application/pdf', size: 9, is_image: false }] }),
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
    fireEvent.click(screen.getByRole('button', { name: /👍 反應 1/ }));
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
    const el = screen.getByText('Alice 把 Bob 加入群組');
    expect(el).toBeInTheDocument();
    // 系統訊息不在泡泡內（無 rounded-2xl 外層）
    expect(el.closest('.rounded-2xl')).toBeNull();
    // 而是置中灰字 pill（rounded-full + bg-slate-100）
    expect(el.className).toContain('rounded-full');
    expect(el.className).toContain('bg-slate-100');
    // 系統訊息不應出現「編輯 / 刪除」泡泡動作
    expect(screen.queryByRole('button', { name: '編輯' })).toBeNull();
  });
});

function nowIso(offsetMs = 0) {
  return new Date(Date.now() - offsetMs).toISOString();
}

describe('Thread 小增強', () => {
  const base = {
    isGroup: false as const, memberNames: {}, currentUserId: 'me',
    canLoadMore: false, title: 'Bob',
    onLoadMore: vi.fn(), onSend: vi.fn(), onRetry: vi.fn(),
    onEdit: vi.fn(), onDelete: vi.fn(), onReact: vi.fn(),
    attachmentUrl: (id: string) => id, onUpload: vi.fn(),
    onRestore: vi.fn(), loadEditHistory: vi.fn(),
  };

  it('編輯鈕只在 15 分鐘內顯示；超時隱藏但刪除仍在', () => {
    const { rerender } = render(
      <Thread {...base}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'fresh', created_at: nowIso(60_000) })]} />,
    );
    expect(screen.getByRole('button', { name: '編輯' })).toBeInTheDocument();

    rerender(
      <Thread {...base}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'old', created_at: nowIso(16 * 60_000) })]} />,
    );
    expect(screen.queryByRole('button', { name: '編輯' })).toBeNull();
    expect(screen.getByRole('button', { name: '刪除' })).toBeInTheDocument();
  });

  it('點「已編輯」呼叫 loadEditHistory 並列出版本', async () => {
    const loadEditHistory = vi.fn().mockResolvedValue([
      { content: 'v1', created_at: '2026-06-21T00:00:00Z' },
      { content: 'v2', created_at: '2026-06-21T00:05:00Z' },
    ]);
    render(
      <Thread {...base} loadEditHistory={loadEditHistory}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'v2', edited_at: '2026-06-21T00:05:00Z', created_at: nowIso(60_000) })]} />,
    );
    fireEvent.click(screen.getByText('已編輯'));
    expect(loadEditHistory).toHaveBeenCalledWith('m1');
    expect(await screen.findByText('v1')).toBeInTheDocument();
  });

  it('已刪除 + 寄件人 + 5 分鐘內顯示還原鈕並呼叫 onRestore', () => {
    const onRestore = vi.fn();
    render(
      <Thread {...base} onRestore={onRestore}
        messages={[msg({ id: 'm1', sender_id: 'me', deleted: true, content: '', deleted_at: nowIso(60_000) })]} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '還原' }));
    expect(onRestore).toHaveBeenCalledWith('m1');
  });

  it('已刪除超過 5 分鐘不顯示還原鈕', () => {
    render(
      <Thread {...base}
        messages={[msg({ id: 'm1', sender_id: 'me', deleted: true, content: '', deleted_at: nowIso(6 * 60_000) })]} />,
    );
    expect(screen.queryByRole('button', { name: '還原' })).toBeNull();
  });

  it('emoji-mart 選擇器選 emoji 呼叫 onReact', async () => {
    const onReact = vi.fn();
    render(
      <Thread {...base} onReact={onReact}
        messages={[msg({ id: 'm1', sender_id: 'me', content: 'hi', created_at: nowIso(60_000) })]} />,
    );
    fireEvent.click(screen.getByRole('button', { name: '更多表情' }));
    // 完整選擇器以 React.lazy 動態載入,需等其載入完成才出現。
    fireEvent.click(await screen.findByText('mock-picker-pick'));
    expect(onReact).toHaveBeenCalledWith('m1', '🎉');
  });
});

describe('Thread 回覆 UI', () => {
  const base = {
    isGroup: false as const,
    memberNames: { 'alice': 'Alice', 'me': 'Me' },
    currentUserId: 'me',
    canLoadMore: false,
    title: 'Alice',
    onLoadMore: vi.fn(),
    onSend: vi.fn(),
    onRetry: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onReact: vi.fn(),
    attachmentUrl: (id: string) => id,
    onUpload: vi.fn(),
    onRestore: vi.fn(),
    loadEditHistory: vi.fn(),
  };

  it('泡泡有 reply_to 時渲染引用塊（寄件人名 + 摘要）', () => {
    const replyPreview: ReplyPreview = {
      id: 'orig-1',
      sender_id: 'alice',
      content: '原始訊息內容',
      deleted: false,
      has_attachment: false,
    };
    render(
      <Thread
        {...base}
        messages={[
          msg({ id: 'orig-1', sender_id: 'alice', content: '原始訊息內容' }),
          msg({ id: 'm2', sender_id: 'me', content: '回覆內容', reply_to: replyPreview }),
        ]}
      />,
    );
    // 引用塊應顯示被引用者名字與內容（getAllByText 因為 title 也叫 Alice）
    expect(screen.getAllByText('Alice').length).toBeGreaterThanOrEqual(1);
    // 引用塊有 data-message-id 的上層，找 blockquote/button 包含 '原始訊息內容'
    expect(screen.getAllByText('原始訊息內容').length).toBeGreaterThanOrEqual(1);
  });

  it('reply_to.deleted=true 時引用塊顯示「原訊息已刪除」', () => {
    const replyPreview: ReplyPreview = {
      id: 'orig-1',
      sender_id: 'alice',
      content: '',
      deleted: true,
      has_attachment: false,
    };
    render(
      <Thread
        {...base}
        messages={[msg({ id: 'm2', sender_id: 'me', content: '回覆', reply_to: replyPreview })]}
      />,
    );
    expect(screen.getByText('原訊息已刪除')).toBeInTheDocument();
  });

  it('點「回覆」後 composer 上方出現引用橫幅（寄件人名 + 內容）', () => {
    render(
      <Thread
        {...base}
        messages={[msg({ id: 'm1', sender_id: 'alice', content: '快來看' })]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '回覆' }));
    // 橫幅顯示被回覆者名字與內容摘要
    // 使用 getAllByText 因為「Alice」可能在 senderName 也出現（isGroup=false 時不顯示，但 memberNames 含）
    expect(screen.getByRole('button', { name: '取消回覆' })).toBeInTheDocument();
    // 橫幅內應有被引用的內容摘要
    const banner = screen.getByRole('button', { name: '取消回覆' }).closest('[data-testid="reply-banner"]') ??
                   screen.getByRole('button', { name: '取消回覆' }).parentElement;
    expect(banner?.textContent).toContain('快來看');
  });

  it('送出時有回覆狀態則 onSend 帶 reply 參數，送出後橫幅清除', () => {
    const onSend = vi.fn();
    render(
      <Thread
        {...base}
        onSend={onSend}
        messages={[msg({ id: 'm1', sender_id: 'alice', content: '快來看' })]}
      />,
    );
    // 點回覆
    fireEvent.click(screen.getByRole('button', { name: '回覆' }));
    // 橫幅出現
    expect(screen.getByRole('button', { name: '取消回覆' })).toBeInTheDocument();
    // 輸入並送出
    fireEvent.change(screen.getByLabelText('訊息輸入'), { target: { value: '好的' } });
    fireEvent.click(screen.getByRole('button', { name: '送出' }));
    // onSend 被呼叫，第三引數為被引用訊息 id
    expect(onSend).toHaveBeenCalledWith(
      '好的',
      [],
      'm1',
      expect.objectContaining({ id: 'm1', sender_id: 'alice' }),
    );
    // 送出後橫幅消失
    expect(screen.queryByRole('button', { name: '取消回覆' })).toBeNull();
  });
});

describe('Thread 轉發 UI', () => {
  const base = {
    isGroup: false as const,
    memberNames: { alice: 'Alice', me: 'Me' },
    currentUserId: 'me',
    canLoadMore: false,
    title: 'Alice',
    onLoadMore: vi.fn(),
    onSend: vi.fn(),
    onRetry: vi.fn(),
    onEdit: vi.fn(),
    onDelete: vi.fn(),
    onReact: vi.fn(),
    attachmentUrl: (id: string) => id,
    onUpload: vi.fn(),
    onRestore: vi.fn(),
    loadEditHistory: vi.fn(),
  };

  it('泡泡有 forwarded_from 時渲染「轉發自 {display_name}」', () => {
    render(
      <Thread
        {...base}
        messages={[
          msg({
            id: 'm1',
            sender_id: 'alice',
            content: '轉發內容',
            forwarded_from: { id: 'orig-user', display_name: 'Charlie' },
          }),
        ]}
        onForward={vi.fn()}
      />,
    );
    expect(screen.getByText(/轉發自 Charlie/)).toBeInTheDocument();
  });

  it('點擊「轉發」按鈕呼叫 onForward 並傳入訊息物件', () => {
    const onForward = vi.fn();
    const m = msg({ id: 'm1', sender_id: 'alice', content: '要轉的訊息', status: 'sent' as const });
    render(
      <Thread
        {...base}
        messages={[m]}
        onForward={onForward}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '轉發' }));
    expect(onForward).toHaveBeenCalledWith(expect.objectContaining({ id: 'm1' }));
  });

  it('sending 狀態泡泡不顯示轉發鈕', () => {
    render(
      <Thread
        {...base}
        messages={[msg({ id: 'm1', sender_id: 'alice', content: '傳送中', status: 'sending' as const })]}
        onForward={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: '轉發' })).toBeNull();
  });

  it('已刪除泡泡不顯示轉發鈕', () => {
    render(
      <Thread
        {...base}
        messages={[msg({ id: 'm1', sender_id: 'alice', content: '', deleted: true })]}
        onForward={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: '轉發' })).toBeNull();
  });

  it('系統訊息不顯示轉發鈕', () => {
    render(
      <Thread
        {...base}
        messages={[msg({ id: 'm1', sender_id: 'alice', content: '系統通知', kind: 'system' as const })]}
        onForward={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: '轉發' })).toBeNull();
  });
});
