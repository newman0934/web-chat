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

export interface ReactionGroup {
  emoji: string;
  count: number;
  user_ids: string[];
}

export const QUICK_REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🙏'];

export interface MessageVersion {
  content: string;
  created_at: string;
}

/** 編輯 / 還原時窗（毫秒）；與後端各一份，前端只用來決定按鈕顯隱。 */
export const EDIT_WINDOW_MS = 15 * 60 * 1000;
export const RESTORE_WINDOW_MS = 5 * 60 * 1000;

export interface ReplyPreview {
  id: string;
  sender_id: string;
  content: string;
  deleted: boolean;
  has_attachment: boolean;
}

export interface ForwardedFrom {
  id: string;
  display_name: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  content: string;
  created_at: string;
  read_count: number;
  attachment: Attachment | null;
  edited_at: string | null;
  deleted: boolean;
  deleted_at?: string | null;
  reactions: ReactionGroup[];
  kind?: 'user' | 'system';
  reply_to?: ReplyPreview | null;
  forwarded_from?: ForwardedFrom | null;
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
  roles: Record<string, 'admin' | 'member'>;
}

export interface GroupCreateRequest {
  name: string;
  member_user_ids: string[];
}

// ---- 站內通知 ----

export type NotificationType = 'reply' | 'reaction' | 'forward';

export interface Notification {
  id: string;
  type: NotificationType;
  actor: { id: string; display_name: string };
  conversation_id: string;
  message_id: string;
  message_preview: string;
  emoji: string | null;
  read: boolean;
  created_at: string;
}

export interface NotificationList {
  items: Notification[];
  unread_count: number;
}

// ---- WebSocket 訊息協定 ----

export interface CallFrom {
  id: string;
  display_name: string;
}

export type ClientWsMessage =
  | { type: 'message'; conversation_id: string; content: string; temp_id: string; attachment_id?: string; reply_to_message_id?: string }
  | { type: 'read'; conversation_id: string }
  | { type: 'typing'; conversation_id: string }
  | { type: 'edit'; message_id: string; content: string }
  | { type: 'delete'; message_id: string }
  | { type: 'restore'; message_id: string }
  | { type: 'react'; message_id: string; emoji: string }
  | { type: 'forward'; message_id: string; to_conversation_id: string }
  | { type: 'call_offer'; to_user_id: string; sdp: RTCSessionDescriptionInit }
  | { type: 'call_answer'; to_user_id: string; sdp: RTCSessionDescriptionInit }
  | { type: 'call_ice'; to_user_id: string; candidate: RTCIceCandidateInit }
  | { type: 'call_reject'; to_user_id: string }
  | { type: 'call_hangup'; to_user_id: string };

export type ServerWsMessage =
  | { type: 'ack'; temp_id: string; message: Message }
  | { type: 'message'; message: Message }
  | { type: 'read'; conversation_id: string; reader_id: string; message_ids: string[] }
  | { type: 'typing'; conversation_id: string; user_id: string }
  | { type: 'error'; reason: string; temp_id?: string }
  | { type: 'message_updated'; message: Message }
  | { type: 'call_offer'; from: CallFrom; sdp: RTCSessionDescriptionInit }
  | { type: 'call_answer'; from: CallFrom; sdp: RTCSessionDescriptionInit }
  | { type: 'call_ice'; from: CallFrom; candidate: RTCIceCandidateInit }
  | { type: 'call_reject'; from: CallFrom }
  | { type: 'call_hangup'; from: CallFrom }
  | { type: 'call_unavailable'; to_user_id: string }
  | { type: 'conversation_updated'; conversation_id: string }
  | { type: 'conversation_removed'; conversation_id: string }
  | { type: 'notification'; notification: Notification };
