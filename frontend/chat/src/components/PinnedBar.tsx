// 對話頂部釘選列:顯示最新釘選 + 「共 N 則」;點擊跳轉,可展開全部、可取消(具權限時)。

import { useState } from 'react';

import type { Message } from '../../../contracts';
import { pinnedBarView } from '../pins';

export function PinnedBar({
  pins,
  canManage,
  onJump,
  onUnpin,
}: {
  pins: Message[];
  canManage: boolean;
  onJump: (messageId: string) => void;
  onUnpin: (messageId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const view = pinnedBarView(pins);
  if (!view) return null;

  return (
    <div data-testid="pinned-bar" className="border-b border-amber-200 bg-amber-50">
      <div className="flex items-center gap-2 px-4 py-2 text-sm">
        <span aria-hidden>📌</span>
        <button
          type="button"
          onClick={() => onJump(view.latest.id)}
          className="min-w-0 flex-1 truncate text-left text-slate-700 hover:text-slate-900"
        >
          {view.latest.content || '（附件）'}
        </button>
        {view.count > 1 ? (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            className="shrink-0 rounded-full bg-amber-200 px-2 py-0.5 text-xs text-amber-800"
          >
            共 {view.count} 則 {open ? '▴' : '▾'}
          </button>
        ) : (
          canManage && (
            <button
              type="button"
              aria-label="取消釘選"
              onClick={() => onUnpin(view.latest.id)}
              className="shrink-0 text-amber-700 hover:text-amber-900"
            >
              ✕
            </button>
          )
        )}
      </div>

      {open && view.count > 1 && (
        <ul className="border-t border-amber-200">
          {pins.map((p) => (
            <li key={p.id} className="flex items-center gap-2 px-4 py-1.5 text-sm hover:bg-amber-100">
              <button
                type="button"
                onClick={() => onJump(p.id)}
                className="min-w-0 flex-1 truncate text-left text-slate-700"
              >
                {p.content || '（附件）'}
              </button>
              {canManage && (
                <button
                  type="button"
                  aria-label="取消釘選"
                  onClick={() => onUnpin(p.id)}
                  className="shrink-0 text-amber-700 hover:text-amber-900"
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
