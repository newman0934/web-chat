// 轉發目標對話選擇器：列出使用者參與的所有對話，點選後呼叫 onPick。
// 標題邏輯與 Sidebar 一致：群組用 name（無 name 時「群組」），direct 用 other_user.display_name。

import type { Conversation } from '../../../contracts';

interface ForwardPickerProps {
  conversations: Conversation[];
  onPick: (conversationId: string) => void;
  onClose: () => void;
}

/** 取得對話的顯示標題（沿用 Sidebar/Thread 的邏輯）。 */
function convLabel(conv: Conversation): string {
  if (conv.type === 'group') return conv.name ?? '群組';
  return conv.other_user?.display_name ?? '';
}

/** 轉發選對話 modal。 */
export function ForwardPicker({ conversations, onPick, onClose }: ForwardPickerProps) {
  return (
    // backdrop
    <div
      data-testid="forward-picker-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      {/* panel — stopPropagation 防止點 panel 內部觸發 backdrop onClose */}
      <div
        className="flex w-80 flex-col rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h3 className="font-semibold text-slate-800">轉發到</h3>
          <button
            type="button"
            aria-label="關閉"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600"
          >
            ✕
          </button>
        </header>

        <ul className="max-h-80 overflow-y-auto py-2">
          {conversations.map((conv) => (
            <li key={conv.id}>
              <button
                type="button"
                className="w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                onClick={() => onPick(conv.id)}
              >
                {convLabel(conv)}
              </button>
            </li>
          ))}
          {conversations.length === 0 && (
            <li className="px-4 py-3 text-sm text-slate-400">沒有可轉發的對話</li>
          )}
        </ul>
      </div>
    </div>
  );
}
