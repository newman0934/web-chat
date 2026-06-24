// 左側欄：目前使用者、加好友表單、對話清單（含未讀數）、連線狀態與登出。

import { useState, type ReactNode } from 'react';

import type { Contact, Conversation } from '../../../contracts';
import type { PresenceMap } from '../presence';
import { highlightParts, type SearchResultView } from '../search';

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  currentUserName: string;
  socketStatus: string;
  contacts: Contact[];
  onSelect: (conversationId: string) => void;
  onAddContact: (email: string) => Promise<string | null>;
  onCreateGroup: (name: string, memberIds: string[]) => Promise<string | null>;
  onLogout: () => void;
  /** 通知中心（鈴鐺）插槽，由 ChatApp 注入；缺省則不顯示。 */
  notificationSlot?: ReactNode;
  /** 好友線上狀態（user_id → state）；1對1 對話列據此顯示綠/灰點。 */
  presence?: PresenceMap;
  // ---- 訊息搜尋 ----
  /** 目前搜尋關鍵字（受控）；非空時側欄改顯示搜尋結果。 */
  searchQuery?: string;
  onSearchChange?: (q: string) => void;
  searchResults?: SearchResultView[];
  searchLoading?: boolean;
  searchHasMore?: boolean;
  onSearchMore?: () => void;
  /** 點搜尋結果：切到該對話並跳轉到該訊息。 */
  onPickResult?: (conversationId: string, messageId: string) => void;
}

/** 搜尋結果片段:命中關鍵字以 <mark> 高亮。 */
function Snippet({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlightParts(text, query).map((p, i) =>
        p.hit ? (
          <mark key={i} className="bg-yellow-200">{p.text}</mark>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}

/** 線上狀態小圓點：綠=在線、灰=離線。 */
function PresenceDot({ online }: { online: boolean }) {
  return (
    <span
      data-testid="presence-dot"
      data-online={online}
      title={online ? '在線' : '離線'}
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${
        online ? 'bg-green-500' : 'bg-slate-300'
      }`}
    />
  );
}

/** 左側欄：使用者資訊、加好友、建群、對話清單與 WS 連線狀態。 */
export function Sidebar({
  conversations,
  activeId,
  currentUserName,
  socketStatus,
  contacts,
  onSelect,
  onAddContact,
  onCreateGroup,
  onLogout,
  notificationSlot,
  presence = {},
  searchQuery = '',
  onSearchChange,
  searchResults = [],
  searchLoading = false,
  searchHasMore = false,
  onSearchMore,
  onPickResult,
}: SidebarProps) {
  const searching = searchQuery.trim().length > 0;
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [showGroup, setShowGroup] = useState(false);
  const [groupName, setGroupName] = useState('');
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [groupErr, setGroupErr] = useState<string | null>(null);
  const [groupBusy, setGroupBusy] = useState(false);

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

  /** 切換好友選取狀態。 */
  const togglePick = (userId: string) => {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  };

  /** 提交建群表單。 */
  const submitGroup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!groupName.trim()) return;
    setGroupBusy(true);
    setGroupErr(null);
    const err = await onCreateGroup(groupName.trim(), [...picked]);
    setGroupBusy(false);
    if (err) {
      setGroupErr(err);
    } else {
      setShowGroup(false);
      setGroupName('');
      setPicked(new Set());
    }
  };

  return (
    <aside className="flex h-full w-72 flex-col border-r border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 p-4">
        <div>
          <p className="text-sm text-slate-400">已登入</p>
          <p className="font-semibold text-slate-800">{currentUserName}</p>
        </div>
        <div className="flex items-center gap-1">
          {notificationSlot}
          <button
            onClick={onLogout}
            className="text-sm text-slate-500 hover:text-red-600"
          >
            登出
          </button>
        </div>
      </header>

      <div className="border-b border-slate-200 p-4">
        <input
          type="search"
          value={searchQuery}
          onChange={(e) => onSearchChange?.(e.target.value)}
          placeholder="🔍 搜尋訊息"
          aria-label="搜尋訊息"
          className="input w-full"
        />
      </div>

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

      <div className="border-b border-slate-200 p-4">
        <button
          type="button"
          onClick={() => setShowGroup((v) => !v)}
          className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
        >
          ＋ 新群組
        </button>

        {showGroup && (
          <form onSubmit={submitGroup} className="mt-3 space-y-2">
            <div>
              <label
                htmlFor="group-name-input"
                className="block text-sm font-medium text-slate-600"
              >
                群組名稱
              </label>
              <input
                id="group-name-input"
                type="text"
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                aria-label="群組名稱"
                placeholder="輸入群組名稱"
                className="input mt-1 w-full"
              />
            </div>
            {contacts.length > 0 && (
              <ul className="space-y-1">
                {contacts.map((c) => (
                  <li key={c.user_id} className="flex items-center gap-2 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      id={`pick-${c.user_id}`}
                      checked={picked.has(c.user_id)}
                      onChange={() => togglePick(c.user_id)}
                    />
                    <label htmlFor={`pick-${c.user_id}`}>{c.display_name}</label>
                  </li>
                ))}
              </ul>
            )}
            {groupErr && (
              <p className="text-sm text-red-600" role="alert">
                {groupErr}
              </p>
            )}
            <button
              type="submit"
              disabled={groupBusy}
              className="rounded-lg bg-indigo-600 px-3 py-1 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              建立
            </button>
          </form>
        )}
      </div>

      {searching ? (
        <div className="flex-1 overflow-y-auto" data-testid="search-results">
          {searchLoading && searchResults.length === 0 ? (
            <p className="p-4 text-sm text-slate-400">搜尋中…</p>
          ) : searchResults.length === 0 ? (
            <p className="p-4 text-sm text-slate-400">找不到符合的訊息。</p>
          ) : (
            <ul>
              {searchResults.map((r) => (
                <li key={r.messageId}>
                  <button
                    onClick={() => onPickResult?.(r.conversationId, r.messageId)}
                    className="flex w-full flex-col gap-0.5 px-4 py-3 text-left hover:bg-slate-50"
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium text-slate-800">
                        {r.conversationTitle}
                      </span>
                      <span className="shrink-0 text-xs text-slate-400">
                        {new Date(r.createdAt).toLocaleDateString()}
                      </span>
                    </span>
                    <span className="text-xs text-slate-500">{r.senderName}</span>
                    <span className="truncate text-sm text-slate-600">
                      <Snippet text={r.content} query={searchQuery} />
                    </span>
                  </button>
                </li>
              ))}
              {searchHasMore && (
                <li className="p-3 text-center">
                  <button
                    onClick={onSearchMore}
                    className="rounded-full bg-white px-4 py-1 text-sm text-indigo-600 shadow hover:bg-indigo-50"
                  >
                    載入更多結果
                  </button>
                </li>
              )}
            </ul>
          )}
        </div>
      ) : (
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
                    <span className="flex items-center gap-1.5 truncate font-medium text-slate-800">
                      {c.type === 'direct' && c.other_user && (
                        <PresenceDot online={presence[c.other_user.id]?.online ?? false} />
                      )}
                      <span className="truncate">
                        {c.type === 'group' ? c.name : c.other_user?.display_name}
                      </span>
                      {c.type === 'group' && (
                        <span className="ml-1 text-xs text-slate-400">· {c.members.length} 人</span>
                      )}
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
      )}

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
