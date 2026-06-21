import { useEffect, useState } from 'react';

import type { MessageVersion } from '../../../contracts';

/** 點「已編輯」後彈出的編輯歷史：載入版本陣列並逐版列出（最後一筆為目前）。 */
export function EditHistoryPopover({
  messageId,
  load,
  onClose,
}: {
  messageId: string;
  load: (id: string) => Promise<MessageVersion[]>;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<MessageVersion[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    load(messageId)
      .then((v) => { if (alive) setVersions(v); })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [messageId, load]);

  return (
    <div className="absolute z-20 mt-1 w-64 rounded-xl border border-slate-200 bg-white p-3 text-left text-slate-700 shadow-lg">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-slate-500">編輯歷史</span>
        <button type="button" aria-label="關閉" onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
      </div>
      {error && <p className="text-xs text-red-500">載入失敗</p>}
      {!error && versions === null && <p className="text-xs text-slate-400">載入中…</p>}
      {versions && (
        <ol className="space-y-1">
          {versions.map((v, i) => (
            <li key={i} className="border-b border-slate-100 pb-1 last:border-0">
              <p className="whitespace-pre-wrap break-words text-sm">{v.content}</p>
              <p className="text-[10px] text-slate-400">
                {new Date(v.created_at).toLocaleString()}
                {i === versions.length - 1 && '（目前）'}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
