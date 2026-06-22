// 站內通知中心：鈴鐺 + 未讀紅點 + 下拉列表。純展示元件（資料由 props 注入，易測）。
// 點一筆 → onOpen(該通知)，由 ChatApp 導向對話並標已讀。開下拉本身不標已讀。

import { useState } from 'react';

import type { Notification } from '../../../contracts';
import { describeNotification } from '../notifications';

interface NotificationCenterProps {
  notifications: Notification[];
  unreadCount: number;
  onOpen: (n: Notification) => void;
}

export function NotificationCenter({ notifications, unreadCount, onOpen }: NotificationCenterProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="通知"
        onClick={() => setOpen((v) => !v)}
        className="relative rounded-lg px-2 py-1 text-lg hover:bg-slate-100"
      >
        🔔
        {unreadCount > 0 && (
          <span
            data-testid="notif-badge"
            className="absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-red-500 px-1 text-center text-[10px] font-semibold leading-[18px] text-white"
          >
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-1 max-h-96 w-80 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg">
          {notifications.length === 0 ? (
            <p className="p-4 text-sm text-slate-400">目前沒有通知</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {notifications.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onOpen(n);
                      setOpen(false);
                    }}
                    className={`flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50 ${
                      n.read ? '' : 'bg-indigo-50/40'
                    }`}
                  >
                    {!n.read && (
                      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-indigo-500" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block text-slate-800">
                        <span className="font-medium">{n.actor.display_name}</span>{' '}
                        {describeNotification(n)}
                      </span>
                      {n.message_preview && (
                        <span className="block truncate text-xs text-slate-400">
                          {n.message_preview}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
