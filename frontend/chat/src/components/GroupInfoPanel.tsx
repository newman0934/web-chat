// 群組資訊面板：成員列 + 角色徽章；admin 可改名/加人/移除/升降/退出，一般成員只見唯讀+退出。

import { useState } from 'react';

import type { Contact, Conversation } from '../../../contracts';
import { isAdmin } from '../groupPermissions';

interface Props {
  conversation: Conversation;
  currentUserId: string;
  contacts: Contact[];
  onAddMember: (opts: { userId?: string; email?: string }) => void;
  onRemoveMember: (userId: string) => void;
  onSetRole: (userId: string, role: 'admin' | 'member') => void;
  onRename: (name: string) => void;
  onLeave: () => void;
  onClose: () => void;
}

/** 群組資訊 / 成員管理面板（側拉）。 */
export function GroupInfoPanel({
  conversation, currentUserId, contacts,
  onAddMember, onRemoveMember, onSetRole, onRename, onLeave, onClose,
}: Props) {
  const admin = isAdmin(conversation.roles, currentUserId);
  const [name, setName] = useState(conversation.name ?? '');
  const [email, setEmail] = useState('');
  // 尚未在群內的好友（可快選加入）
  const memberIds = new Set(conversation.members.map((m) => m.id));
  const addableFriends = contacts.filter((c) => !memberIds.has(c.user_id));

  return (
    <aside className="flex h-full w-80 flex-col border-l border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h3 className="font-semibold text-slate-800">群組資訊</h3>
        <button type="button" aria-label="關閉" onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {admin && (
          <form
            className="flex gap-2"
            onSubmit={(e) => { e.preventDefault(); const v = name.trim(); if (v) onRename(v); }}
          >
            <input
              aria-label="群組名稱" value={name} onChange={(e) => setName(e.target.value)}
              className="input flex-1"
            />
            <button type="submit" className="text-sm text-indigo-600">改名</button>
          </form>
        )}

        <div>
          <p className="mb-1 text-xs font-medium text-slate-400">成員（{conversation.members.length}）</p>
          <ul className="space-y-1">
            {conversation.members.map((m) => {
              const mAdmin = conversation.roles[m.id] === 'admin';
              return (
                <li key={m.id} className="flex items-center gap-2 rounded px-2 py-1 hover:bg-slate-50">
                  <span className="flex-1 truncate text-sm text-slate-700">
                    {m.display_name}
                    {mAdmin && <span className="ml-1 rounded bg-indigo-100 px-1 text-xs text-indigo-600">管理員</span>}
                  </span>
                  {admin && m.id !== currentUserId && (
                    <>
                      <button
                        type="button"
                        onClick={() => onSetRole(m.id, mAdmin ? 'member' : 'admin')}
                        className="text-xs text-slate-500 hover:text-indigo-600"
                      >
                        {mAdmin ? '取消管理員' : '設為管理員'}
                      </button>
                      <button
                        type="button"
                        aria-label={`移除 ${m.display_name}`}
                        onClick={() => onRemoveMember(m.id)}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        移除
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        {admin && (
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <p className="text-xs font-medium text-slate-400">加入成員</p>
            {addableFriends.length > 0 && (
              <select
                aria-label="從好友加入"
                className="input w-full"
                value=""
                onChange={(e) => { if (e.target.value) onAddMember({ userId: e.target.value }); }}
              >
                <option value="">從好友選擇…</option>
                {addableFriends.map((c) => (
                  <option key={c.user_id} value={c.user_id}>{c.display_name}</option>
                ))}
              </select>
            )}
            <form
              className="flex gap-2"
              onSubmit={(e) => { e.preventDefault(); const v = email.trim(); if (v) { onAddMember({ email: v }); setEmail(''); } }}
            >
              <input
                aria-label="以 email 加入" type="email" placeholder="email 加非好友"
                value={email} onChange={(e) => setEmail(e.target.value)} className="input flex-1"
              />
              <button type="submit" className="text-sm text-indigo-600">加入</button>
            </form>
          </div>
        )}
      </div>

      <footer className="border-t border-slate-200 p-4">
        <button
          type="button"
          onClick={onLeave}
          className="w-full rounded-lg bg-red-50 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-100"
        >
          退出群組
        </button>
      </footer>
    </aside>
  );
}
