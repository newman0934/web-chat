// shell 的執行期設定。可用 Vite 環境變數覆寫，否則用本機預設值。

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const WS_BASE_URL =
  import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8000';

// JWT 存在 localStorage 的 key；shell 與 chat 獨立模式 bootstrap 共用此鍵。
export const TOKEN_STORAGE_KEY = 'chatweb.token';
