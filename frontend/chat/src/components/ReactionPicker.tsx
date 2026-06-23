// 訊息表情選擇器：快速 6 個 + 「更多表情」開 emoji-mart 完整選擇器。
// 完整選擇器(emoji-mart,~700KB)以 React.lazy 動態載入,不進主 bundle、只在開啟時才抓。

import { lazy, Suspense, useState } from 'react';

import { QUICK_REACTIONS } from '../../../contracts';

const EmojiFullPicker = lazy(() => import('./EmojiFullPicker'));

/** 表情選擇器：快速 6 個 + 「更多表情」開 emoji-mart 完整選擇器。 */
export function ReactionPicker({ onPick }: { onPick: (emoji: string) => void }) {
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState(false);
  return (
    <span className="relative">
      <button
        type="button"
        aria-label="新增表情"
        onClick={() => { setOpen((v) => !v); setFull(false); }}
        className="rounded-full px-2 py-0.5 text-xs bg-slate-100 text-slate-500 hover:bg-slate-200"
      >
        ＋
      </button>
      <button
        type="button"
        aria-label="更多表情"
        onClick={() => { setFull((v) => !v); setOpen(false); }}
        className="rounded px-1 text-slate-400 hover:bg-slate-100 text-xs"
      >
        ⋯
      </button>
      {open && (
        <span className="absolute bottom-full left-0 z-10 mb-1 flex items-center gap-1 rounded-xl bg-white p-1 shadow-lg">
          {QUICK_REACTIONS.map((e) => (
            <button
              key={e}
              type="button"
              onClick={() => { onPick(e); setOpen(false); }}
              className="rounded px-1 hover:bg-slate-100"
            >
              {e}
            </button>
          ))}
        </span>
      )}
      {full && (
        <span className="absolute bottom-full left-0 z-20 mb-1">
          <Suspense fallback={<span className="block rounded-xl bg-white p-3 text-xs text-slate-400 shadow-lg">載入中…</span>}>
            <EmojiFullPicker onPick={(emoji) => { onPick(emoji); setFull(false); }} />
          </Suspense>
        </span>
      )}
    </span>
  );
}
