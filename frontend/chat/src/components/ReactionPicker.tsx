// 訊息表情選擇器：快速 6 個 + 「更多表情」開 emoji-mart 完整選擇器。

import { useState } from 'react';

import Picker from '@emoji-mart/react';
import data from '@emoji-mart/data';

import { QUICK_REACTIONS } from '../../../contracts';

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
          <Picker
            data={data}
            onEmojiSelect={(e: { native: string }) => { onPick(e.native); setFull(false); }}
          />
        </span>
      )}
    </span>
  );
}
