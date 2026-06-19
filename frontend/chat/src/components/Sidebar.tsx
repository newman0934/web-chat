// 左側欄：目前使用者、加好友表單、對話清單（含未讀數）、連線狀態與登出。

import { useState } from 'react';

import type { Conversation } from '../../../contracts';

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  currentUserName: string;
  socketStatus: string;
  onSelect: (conversationId: string) => void;
  onAddContact: (email: string) => Promise<string | null>;
  onLogout: () => void;
}

/** 左側欄：使用者資訊、加好友、對話清單與 WS 連線狀態。 */
export function Sidebar({
  conversations,
  activeId,
  currentUserName,
  socketStatus,
  onSelect,
  onAddContact,
  onLogout,
}: SidebarProps) {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** 提交加好友表單；成功清空 email，失敗顯示錯誤。 */
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    const err = await onAddContact(email.trim());
    setBusy(false);
    if (err) {
      setError(err);
    } else {
      setEmail('');
    }
  };

  return (
    <aside className="flex h-full w-72 flex-col border-r border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 p-4">
        <div>
          <p className="text-sm text-slate-400">已登入</p>
          <p className="font-semibold text-slate-800">{currentUserName}</p>
        </div>
        <button
          onClick={onLogout}
          className="text-sm text-slate-500 hover:text-red-600"
        >
          登出
        </button>
      </header>

      <form onSubmit={submit} className="space-y-2 border-b border-slate-200 p-4">
        <label className="block text-sm font-medium text-slate-600">用 email 加好友</label>
        <div className="flex gap-2">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="friend@example.com"
            aria-label="好友 email"
            className="input flex-1"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-indigo-600 px-3 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            加入
          </button>
        </div>
        {error && (
          <p className="text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
      </form>

      <div className="flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <p className="p-4 text-sm text-slate-400">還沒有對話，先加個好友吧。</p>
        ) : (
          <ul>
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => onSelect(c.id)}
                  className={`flex w-full items-center justify-between gap-2 px-4 py-3 text-left hover:bg-slate-50 ${
                    activeId === c.id ? 'bg-indigo-50' : ''
                  }`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-slate-800">
                      {c.other_user.display_name}
                    </span>
                    <span className="block truncate text-sm text-slate-400">
                      {c.last_message?.content ?? '尚無訊息'}
                    </span>
                  </span>
                  {c.unread_count > 0 && (
                    <span className="rounded-full bg-indigo-600 px-2 py-0.5 text-xs font-semibold text-white">
                      {c.unread_count}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <footer className="border-t border-slate-200 p-3 text-xs text-slate-400">
        連線狀態：{socketStatusLabel(socketStatus)}
      </footer>
    </aside>
  );
}

/** 將 WebSocket 狀態碼轉成使用者可讀的中文標籤。 */
function socketStatusLabel(status: string): string {
  switch (status) {
    case 'open':
      return '已連線';
    case 'connecting':
      return '連線中…';
    case 'reconnecting':
      return '重新連線中…';
    default:
      return '已斷線';
  }
}
