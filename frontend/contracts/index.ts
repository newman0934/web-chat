// 微前端邊界契約：shell ↔ remote 的共享型別。
// 各 remote 只透過這些 props 與 host 溝通，不直接碰 shell 內部狀態。
// 用 `import type` 引用，建置時會被抹除，不會造成跨套件的執行期解析。

export interface CurrentUser {
  id: string;
  email: string;
  display_name: string;
}

/** auth remote（`auth/AuthApp`）對外 props。 */
export interface AuthAppProps {
  /** 登入或註冊成功後，把 JWT 交回 shell。 */
  onAuthSuccess: (token: string) => void;
  /** 後端 REST base URL，由 shell 提供。 */
  apiBaseUrl: string;
}

/** chat remote（`chat/ChatApp`）對外 props。 */
export interface ChatAppProps {
  token: string;
  currentUser: CurrentUser;
  /** token 失效或使用者登出時通知 shell。 */
  onLogout: () => void;
  apiBaseUrl: string;
  /** WebSocket base URL（ws:// 或 wss://），由 shell 提供。 */
  wsBaseUrl: string;
}

// ---- REST / WS 資料型別（前後端共用語意） ----

export interface Contact {
  user_id: string;
  email: string;
  display_name: string;
  conversation_id: string;
}

export interface Attachment {
  id: string;
  original_name: string;
  content_type: string;
  size: number;
  is_image: boolean;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  content: string;
  created_at: string;
  read_count: number;
  attachment: Attachment | null;
}

export type AttachmentOut = Attachment;

export interface Conversation {
  id: string;
  type: 'direct' | 'group';
  name: string | null;
  other_user: CurrentUser | null;
  members: CurrentUser[];
  last_message: Message | null;
  unread_count: number;
}

export interface GroupCreateRequest {
  name: string;
  member_user_ids: string[];
}

// ---- WebSocket 訊息協定 ----

export type ClientWsMessage =
  | { type: 'message'; conversation_id: string; content: string; temp_id: string; attachment_id?: string }
  | { type: 'read'; conversation_id: string }
  | { type: 'typing'; conversation_id: string };

export type ServerWsMessage =
  | { type: 'ack'; temp_id: string; message: Message }
  | { type: 'message'; message: Message }
  | { type: 'read'; conversation_id: string; reader_id: string; message_ids: string[] }
  | { type: 'typing'; conversation_id: string; user_id: string }
  | { type: 'error'; reason: string; temp_id?: string };
