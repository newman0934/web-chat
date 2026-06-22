// chat remote 的 REST 客戶端：包裝 fetch，統一帶上 JWT 與錯誤處理。
// 即時訊息走 WebSocket（見 useChatSocket.ts）；這裡只負責「非即時」的讀取與加好友。

import type { Attachment, Contact, Conversation, GroupCreateRequest, Message, MessageVersion, NotificationList } from '../../contracts';

export class ApiClient {
  /** @param baseUrl REST API 根路徑 @param token JWT，附在 Authorization header */
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
  ) {}

  /** 共用請求邏輯：附帶 auth header，並把 401 / 其他錯誤轉成具型別的例外。 */
  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.token}`,
        ...(init?.headers ?? {}),
      },
    });
    // 401 單獨成一類，呼叫端據此觸發登出（token 失效）。
    if (resp.status === 401) {
      throw new UnauthorizedError();
    }
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new ApiError(data.detail ?? `請求失敗 (${resp.status})`, resp.status);
    }
    return (await resp.json()) as T;
  }

  /** 取得目前使用者的好友清單。 */
  listContacts() {
    return this.req<Contact[]>('/contacts');
  }

  /** 以 email 加好友；後端會一併建立或回傳對話 id。 */
  addContact(email: string) {
    return this.req<Contact>('/contacts', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  /** 取得對話清單（含對方資訊、最後訊息、未讀數）。 */
  listConversations() {
    return this.req<Conversation[]>('/conversations');
  }

  /** 建立群組對話，並回傳新建的 Conversation。 */
  createGroup(name: string, memberUserIds: string[]) {
    const body: GroupCreateRequest = { name, member_user_ids: memberUserIds };
    return this.req<Conversation>('/conversations/groups', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  /** 撈歷史訊息。before 為游標（取更早的訊息），limit 為每頁筆數。 */
  listMessages(conversationId: string, opts?: { before?: string; limit?: number }) {
    const params = new URLSearchParams();
    if (opts?.before) params.set('before', opts.before);
    if (opts?.limit) params.set('limit', String(opts.limit));
    const qs = params.toString();
    return this.req<Message[]>(
      `/conversations/${conversationId}/messages${qs ? `?${qs}` : ''}`,
    );
  }

  /** 取得某訊息的編輯歷史（由舊到新，最後一筆為目前版本）。 */
  getMessageEdits(messageId: string) {
    return this.req<MessageVersion[]>(`/messages/${messageId}/edits`);
  }

  /** 加成員（user_id 好友快選 或 email 加非好友）。回更新後的 Conversation。 */
  addMember(conversationId: string, opts: { userId?: string; email?: string }) {
    return this.req<Conversation>(`/conversations/${conversationId}/members`, {
      method: 'POST',
      body: JSON.stringify({ user_id: opts.userId, email: opts.email }),
    });
  }

  /** 移除成員（admin）。回更新後的 Conversation。 */
  removeMember(conversationId: string, userId: string) {
    return this.req<Conversation>(`/conversations/${conversationId}/members/${userId}`, {
      method: 'DELETE',
    });
  }

  /** 退出群組。 */
  leaveGroup(conversationId: string) {
    return this.req<{ ok: boolean }>(`/conversations/${conversationId}/leave`, {
      method: 'POST',
    });
  }

  /** 群組改名（admin）。 */
  renameGroup(conversationId: string, name: string) {
    return this.req<Conversation>(`/conversations/${conversationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    });
  }

  /** 設定成員角色（admin）。 */
  setMemberRole(conversationId: string, userId: string, role: 'admin' | 'member') {
    return this.req<Conversation>(`/conversations/${conversationId}/members/${userId}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    });
  }

  /** 取得站內通知列表(新→舊)與未讀數。before 為游標(取更早的)。 */
  listNotifications(opts?: { before?: string; limit?: number }) {
    const params = new URLSearchParams();
    if (opts?.before) params.set('before', opts.before);
    if (opts?.limit) params.set('limit', String(opts.limit));
    const qs = params.toString();
    return this.req<NotificationList>(`/notifications${qs ? `?${qs}` : ''}`);
  }

  /** 開啟某對話時呼叫:把該對話下的通知標為已讀。 */
  markNotificationsRead(conversationId: string) {
    return this.req<{ ok: boolean; marked: number }>('/notifications/read', {
      method: 'POST',
      body: JSON.stringify({ conversation_id: conversationId }),
    });
  }

  /** 上傳單一檔案，回附件中繼資料。不手動設 Content-Type，讓瀏覽器帶 multipart boundary。 */
  async uploadFile(file: File): Promise<Attachment> {
    const form = new FormData();
    form.append('file', file);
    const resp = await fetch(`${this.baseUrl}/uploads`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.token}` },
      body: form,
    });
    if (resp.status === 401) throw new UnauthorizedError();
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new ApiError(data.detail ?? `上傳失敗 (${resp.status})`, resp.status);
    }
    return (await resp.json()) as Attachment;
  }
}

/** 一般 API 錯誤，帶 HTTP status 與後端的 detail 訊息。 */
export class ApiError extends Error {
  /** @param message 後端 detail 或預設錯誤文字 @param status HTTP 狀態碼 */
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** 401 專用：呼叫端 catch 到這個就觸發 onLogout。 */
export class UnauthorizedError extends ApiError {
  /** 固定訊息「憑證失效」與 status 401。 */
  constructor() {
    super('憑證失效', 401);
    this.name = 'UnauthorizedError';
  }
}
