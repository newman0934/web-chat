# 圖片與檔案傳輸 — 設計文件

- 日期：2026-06-20
- 狀態：設計定案，待 review
- 範圍：在現有聊天（1對1 + 群組）上新增「最小可用」的圖片/檔案附件
- 前置：本功能原列於 [MVP 設計文件](2026-06-19-chat-web-mvp-design.md) 的「明確不做」，經使用者要求納入。建立在 `feat/group-chat` 分支（含群組聊天 + zustand）之上。

## 1. 目標與範圍

讓使用者在訊息中傳送圖片與檔案。圖片在對話內嵌顯示，其他檔案顯示為下載連結。

### 驗收範圍（最小可用）

- ✅ 一則訊息可帶**一個**附件（可另附選填文字 caption；亦可純附件無文字）
- ✅ 圖片內嵌顯示原圖（點擊開新分頁看大圖）
- ✅ 其他檔案顯示為下載連結（檔名 + 大小）
- ✅ 單檔上限 **10MB**、任意型別
- ✅ 附件與訊息一樣即時送達（沿用現有 WS 廣播 / 群組廣播 / 樂觀更新）
- ✅ 下載/檢視需授權（僅該對話成員）

### 明確不做（之後擴充）

- ❌ 一則多附件
- ❌ 圖片縮圖 / 伺服器端影像處理
- ❌ 拖拉上傳、上傳進度條、貼上圖片、全螢幕預覽 modal
- ❌ 物件儲存（S3/MinIO）、CDN、簽章 URL
- ❌ 孤兒附件自動清理（先不做，僅備註）

## 2. 核心決策

- **儲存**：檔案存 API server 本機檔案系統（`backend/uploads/`），DB 只存中繼資料。零額外基礎設施，配合現有 SQLite/local 開發。取捨：不適合多機水平擴充，MVP 可接受。
- **傳送流程（方案 A）**：先 `POST /uploads` 取得 `attachment_id`，再走**現有 WS 送訊息路徑**引用它。附件只是 Message 多出來的關聯，完全重用既有的 WS ack / 樂觀更新 / 群組廣播；不為檔案另開一條送訊息路徑。

替代方案 B（單一 REST multipart 端點直接建訊息）已否決：會讓送訊息分裂成「文字走 WS、檔案走 REST」兩套，樂觀更新與 ack 需重做、與現有流程不一致。

## 3. 資料模型（SQLAlchemy）

```
Attachment
  id (PK, Uuid)
  message_id (FK→Message, ondelete CASCADE, nullable, UNIQUE)  # 上傳當下為 NULL；送訊息時綁定
  uploader_id (FK→User, ondelete CASCADE)
  stored_name      # 存到磁碟的隨機檔名（uuid hex + 副檔名）
  original_name    # 使用者原始檔名（下載時用）
  content_type     # MIME，如 image/png、application/pdf
  size             # bytes
  is_image         # bool（content_type 以 "image/" 開頭）
  created_at
```

- **Message**：`content` 放寬為可空字串（純附件訊息允許無文字）；模型欄位不變，僅語意放寬。附件透過 `Attachment.message_id` 一對一關聯（UNIQUE，一則最多一附件）。
- **磁碟**：檔案存 `backend/uploads/<stored_name>`（加入 `.gitignore`）。`stored_name` 用隨機 uuid hex + 原副檔名，避免衝突與路徑穿越；絕不使用使用者提供的檔名當磁碟路徑。
- **兩段式生命週期**：上傳先建 `message_id=NULL` 的孤兒附件（屬上傳者）；WS 送訊息帶 `attachment_id` 時驗證並綁定。
- 孤兒附件（上傳未送出）MVP 不清理；備註：未來可加排程清掉超過 N 小時未綁定者。

## 4. REST API

`/auth`、`/users/me`、`/contacts`、`/conversations` 不變。

| Method | 路徑 | 說明 |
|---|---|---|
| POST | `/uploads` | multipart 上傳單檔，建孤兒 Attachment，回中繼資料 |
| GET | `/attachments/{id}` | 串流檔案內容（內嵌圖片 / 下載） |

### `POST /uploads`（需登入）

- 欄位 `file`（multipart/form-data）。
- 驗證：必須有檔；`size ≤ 10MB`，超過回 **413**；無檔回 **400**。
- `is_image = content_type.startswith("image/")`。存檔到 `uploads/<uuid_hex><ext>`，建 `Attachment(uploader=current_user, message_id=NULL, …)`。
- 回 **201**：

```
AttachmentOut { id, original_name, content_type, size, is_image }
```

### `GET /attachments/{id}`

- **驗證**：接受 `Authorization: Bearer` **或** query `?token=`（因 `<img>` 無法帶 header，沿用 `/ws?token=` 既有模式）。
- **權限**：
  - 附件已綁定訊息 → 要求者必須是該訊息所屬對話的成員，否則 **404**。
  - 孤兒附件（`message_id IS NULL`）→ 僅上傳者可存取，否則 **404**。
- 回應：`FileResponse` 串流，`Content-Type` 用儲存的 MIME。`is_image` → `Content-Disposition: inline`；否則 `attachment; filename="<original_name>"`（觸發下載）。

> 取捨：token 出現在 URL（可能進 access log），與本專案 WS 既有做法一致，MVP 可接受；未來可換短效簽章 URL。

## 5. WebSocket：`/ws`

訊息類型不變。`_handle_send` 調整：

```
1. 取 content（可空）與選填 attachment_id
2. 若 content 為空「且」無 attachment_id → 回 {type:"error", reason:"invalid_payload", temp_id}
3. 若有 attachment_id：
   - 解析 UUID；查 Attachment
   - 驗 uploader == sender 且 message_id IS NULL（未被使用）
   - 否則回 {type:"error", reason:"invalid_attachment", temp_id}
4. 驗 sender 為該對話成員（沿用 get_conversation_for_member）
5. 建 Message（content 可為 ""）→ 設 attachment.message_id = message.id → commit
6. 回 ACK（message 帶 attachment）給寄件人；廣播給其他在線成員（沿用群組廣播）
```

- WS 序列化的 `message` 物件新增 `attachment` 欄位（無附件為 `null`）。
- 既有 ack / message / read / 群組廣播路徑不變，附件僅是 message 多帶的資料。

## 6. 前端（微前端）

### 契約 `frontend/contracts/index.ts`

```ts
interface Attachment {
  id: string;
  original_name: string;
  content_type: string;
  size: number;
  is_image: boolean;
}

interface Message {           // 既有欄位不變，新增：
  attachment: Attachment | null;
}

// ClientWsMessage 的 'message' 變體新增選填欄位：
| { type: 'message'; conversation_id: string; content: string; temp_id: string; attachment_id?: string }

// 上傳回應型別（= Attachment 同形）
type AttachmentOut = Attachment;
```

### chat remote

- `api.ts`：`uploadFile(file: File): Promise<Attachment>` — `POST /uploads` 送 `FormData`，**不手動設 `Content-Type`**（讓瀏覽器帶 multipart boundary）；沿用既有 401→UnauthorizedError 處理。
- `messageStore.ts`：`ChatMessage` 自動繼承 `Message.attachment`；`makeOptimistic` 新增選填 `attachment` 參數（送出當下檔案已上傳完成、已有真實 id，故樂觀訊息可直接顯示）。
- `ChatApp.tsx`：
  - 提供 `attachmentUrl(id) = \`${apiBaseUrl}/attachments/${id}?token=${token}\``。
  - `sendMessage(content, attachment?)`：樂觀訊息帶 attachment 中繼資料；WS 送出帶 `attachment_id`。
  - 透過 props 把 `onUpload`（呼叫 `api.uploadFile`）與 `attachmentUrl` 傳給 `Thread`。
- `components/Thread.tsx`：
  - composer 加 **📎 附件鈕**（file input）。選檔 → `onUpload(file)` 上傳，顯示「上傳中…」與選好的附件預覽 chip（可移除）；送出後清除。
  - 送出改為 `onSend(content, attachmentId?)`；允許純附件無文字（draft 與 pendingAttachment 至少一者有值才可送）。
  - `MessageBubble` 依 `message.attachment` 渲染：`is_image` → `<img src={attachmentUrl(id)}>`（限寬、點擊開新分頁）；否則 → 下載 chip `📎 {original_name}（{size}）` 連到 `attachmentUrl(id)`。
- props 串接：`Thread` 新增 `onUpload: (file: File) => Promise<Attachment | null>`、`attachmentUrl: (id: string) => string`。

### shell

不動。附件不影響 host/remote 邊界。

## 7. 測試策略

### 後端（pytest）

- 上傳：成功回中繼資料；超過 10MB → 413；無檔 → 400；`is_image` 對 image/* 為真、其他為假。
- 下載權限：成員可取；非成員 → 404；孤兒附件僅上傳者可取、他人 → 404。
- WS 帶附件：成功綁定訊息並廣播（ack/push 的 message 帶 attachment）；附件非本人或已被使用 → `invalid_attachment`；純附件無文字可送；content 與 attachment 皆空 → `invalid_payload`。
- 歷史 API：`MessageOut` 帶 `attachment`。

### 前端（Vitest）

- `messageStore.makeOptimistic` 帶 attachment → 訊息含該附件。
- `MessageBubble`：圖片附件渲染 `<img>`（src 指向 attachmentUrl）；非圖片渲染下載連結（含原始檔名）。
- `api.uploadFile`：以 FormData POST，回 AttachmentOut 形狀。

## 8. 安全與備註

- `stored_name` 一律用隨機 uuid，**絕不**用使用者檔名組磁碟路徑（防路徑穿越）；下載以附件 id 查 DB 再讀對應 `stored_name`。
- 下載端點務必做對話成員權限檢查，避免單憑 id 取得他人對話附件。
- 大小上限於上傳端點強制（避免塞爆磁碟）；型別不限，但圖片以外一律以 `attachment` disposition 下載，不在瀏覽器直接執行。
- `uploads/` 需存在且加入 `.gitignore`；正式部署時應放在持久化 volume。
