// emoji-mart 完整選擇器的薄包裝;刻意獨立成檔,讓 ReactionPicker 以 React.lazy 動態載入,
// 把 emoji-mart(react 包裝 + 大型 data JSON,~700KB)拆出主 bundle,只在開啟時才抓。

import Picker from '@emoji-mart/react';
import data from '@emoji-mart/data';

export default function EmojiFullPicker({ onPick }: { onPick: (emoji: string) => void }) {
  return (
    <Picker
      data={data}
      onEmojiSelect={(e: { native: string }) => onPick(e.native)}
    />
  );
}
