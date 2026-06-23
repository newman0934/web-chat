# 群組管理設計（成員/角色/改名）

- 日期：2026-06-21
- 狀態：設計定案，待 review
- 範圍：補上群組聊天當初「明確不做」的成員管理功能

## 1. 目標與範圍

把 [群組聊天設計](../group-chat/spec.md) 標為「明確不做」的四項補齊：

- ✅ 建群後加入 / 移除成員、退出群組
- ✅ 群組改名
- ✅ 管理員角色 / 權限（admin / member 雙角色，可指派）
- ✅ 用 email 加非好友進群（放寬原「只能加好友」限制）

### 明確不做

- ❌ 群組頭像 / 描述 / 進階設定
- ❌ 邀請連結 / 待審核加入
- ❌ 多階管理員權限細分（只有 admin / member 兩級，且 admin 平權）
- ❌ direct 對話的成員管理（權限只作用於 group）

## 2. 整體設計

沿用現有架構分工：**結構性 CRUD 走 REST，WS 只負責即時通知**（與建群、加好友一致）。
每支成員操作 REST 端點：驗權限 → 改 DB → 寫一筆系統訊息 → 透過既有 `ConnectionManager` 廣播。

核心不變式：**群組只要還有成員，就至少有一位 admin**。會讓 admin 歸零的動作（leave / remove / demote）一律擋下（400）。

## 3. 資料模型

兩個欄位變更，各一支 Alembic migration。

### `ConversationMember.role`

- `String(16)`、`NOT NULL`、預設 `'member'`。值域 `'admin' | 'member'`。
- 遷移回填既有資料：每個 group 對話中 `user_id == conversation.creator_id` 的成員設 `'admin'`，其餘設 `'member'`；direct 對話成員一律 `'member'`。
- 權限只在 `type='group'` 強制；direct 的 role 存在但不使用。

### `Message.kind`

- `String(16)`、`NOT NULL`、預設 `'user'`。值域 `'user' | 'system'`。
- 遷移把既有訊息全部回填 `'user'`。
- 系統訊息：`kind='system'`、`sender_id=` 操作者、`content=` 預先組好的中文字串、無附件/表情/已讀語意。
- 系統訊息照常落庫（分頁歷史可見）、照常經 WS 推播。

### 系統訊息文案

| 動作 | content |
|---|---|
| 加成員 | 「{actor} 把 {target} 加入群組」 |
| 移除成員 | 「{actor} 將 {target} 移出群組」 |
| 退出 | 「{user} 退出群組」 |
| 改名 | 「群組已改名為「{name}」」 |
| 升管理員 | 「{actor} 將 {target} 設為管理員」 |
| 降一般成員 | 「{actor} 取消 {target} 的管理員」 |

> 取捨：系統事件用「預先組字串存進 Message」而非另開 events 表或結構化欄位 —— 最小可用、與現有訊息流（落庫 + WS 推播 + 分頁歷史）完全共用，YAGNI。

## 4. REST API 與權限

全部限 `type='group'`（對 direct 呼叫回 400）。`conversation_id` 不存在或呼叫者非成員 → 404。

| Method | 路徑 | 權限 | 行為與錯誤 |
|---|---|---|---|
| `POST` | `/conversations/{id}/members` | admin | body `{user_id}`（好友快選）或 `{email}`（加非好友）。查無使用者→404；已是成員→400。加為 `member`，寫「加入群組」系統訊息 |
| `DELETE` | `/conversations/{id}/members/{user_id}` | admin | 移除他人（移自己→400，請用 leave）。對象為最後一位 admin→400。寫「移出群組」 |
| `POST` | `/conversations/{id}/leave` | 任何成員 | 退出。最後一位 admin 但群仍有其他人→400（須先指派他人為 admin）。退出後群變空→刪除對話（訊息/成員 CASCADE） |
| `PATCH` | `/conversations/{id}` | admin | body `{name}`（1–100 字，trim 後非空）。改名，寫「已改名為…」 |
| `PATCH` | `/conversations/{id}/members/{user_id}/role` | admin | body `{role: "admin"\|"member"}`。降級最後一位 admin→400。寫「設為/取消管理員」。對已是該角色者為 no-op（不寫系統訊息、回 200） |

### 權限規則

- 全體 admin 平權，可加 / 移 / 改名 / 升降任何成員（含其他 admin）。
- 建立者只是初始 admin，無額外特權；`creator_id` 僅保留作紀錄。
- 不變式檢查集中在服務層（leave / remove / demote 三處共用一個「移除/降級此人後是否還有 admin」判定）。
- 加成員的 email 路徑不需是好友（放寬第 4 項）；好友快選送 `user_id`。
- 權限與不變式邏輯放在 `app/services/conversations.py`（與現有 group 邏輯同檔），REST router 只做 HTTP 轉換。

## 5. WS 通知與系統訊息廣播

每支端點在 DB 改動 + commit 成功後做廣播（用既有 `manager`）。

### 系統訊息推播

建立 `Message(kind='system', …)`，落庫後當成一般 `{type:"message", message}` 推給所有在線成員。`MessageOut` 增加 `kind` 欄位。離線者下次拉歷史可見。

### 對話變更通知（新增 Server→Client 事件）

- `{type:"conversation_updated", conversation_id}`：推給變更後的所有在線成員；客戶端據此重拉 `/conversations`（更新側欄名稱、成員列、角色）。沿用「收到事件就 refetch」模式，不在事件塞整包 ConversationOut（避免 unread / last_message 觀看者相依問題）。
- `{type:"conversation_removed", conversation_id}`：推給被移除者；群被刪除時推給全體在線成員。客戶端從清單移除該對話，若正開著則切回空畫面。

### 對象與順序

- 先寫系統訊息、commit，再廣播。
- 改名 / 升降：發 `conversation_updated` + 系統訊息給所有成員。
- 加成員：發 `conversation_updated` + 系統訊息給所有成員（含新成員）。
- 移除：在移除前算出收件人；被移除者收 `conversation_removed`，其餘成員收 `conversation_updated` + 系統訊息。
- 退出：本人收 `conversation_removed`，其餘收 `conversation_updated` + 系統訊息。
- 群被刪（最後一人退出）：只有該人收 `conversation_removed`，無系統訊息（無人可收）。

## 6. 前端

### contracts（`frontend/contracts/index.ts`）

- `Message` 加 `kind: 'user' | 'system'`。
- `ConversationOut` 加 `roles: Record<string, 'admin' | 'member'>`（user_id → 角色）；`members` 維持 `CurrentUser[]`。
- 新增成員操作的 REST 請求型別；`ServerWsMessage` 加 `conversation_updated` / `conversation_removed`。

### ApiClient（`chat/src/api.ts`）

`addMember(convId, { userId?, email? })`、`removeMember(convId, userId)`、`leaveGroup(convId)`、`renameGroup(convId, name)`、`setMemberRole(convId, userId, role)`。錯誤沿用現有 `ApiError`（帶後端 detail 字串）。

### store（`chat/src/store.ts`，zustand）

- `conversation_updated` → 觸發 `loadConversations` refetch。
- `conversation_removed` → 從 `conversations` 移除；若 `activeId` 等於該對話則 `activeId=null` 切回空畫面。
- 系統訊息照現有 `receiveMessage` 進訊息流。

### 純權限 helper（`chat/src/groupPermissions.ts`）

`isAdmin(roles, userId)`、`adminCount(roles)`、`canManage(roles, userId)` 等純函式，單獨測。

### UI

- 群組 Thread header 加「群組資訊」鈕，開 `GroupInfoPanel`（`chat/src/components/GroupInfoPanel.tsx`，側拉或 modal）。
- `GroupInfoPanel`：
  - **admin 視角**：改名輸入框；每位他人成員旁有「移除」與「設管理員 / 取消管理員」；「加成員」區塊（好友下拉快選 + email 輸入）；底部「退出群組」。
  - **一般成員視角**：唯讀成員列（含 admin 徽章）+「退出群組」。
- 系統訊息：`Thread` 的 `MessageBubble` 在 `kind==='system'` 時改渲染置中灰字一行，不顯示泡泡 / 狀態 / 編輯刪除 / 表情。

### ChatApp 接線

把 `conversation_updated` / `conversation_removed` 路由到 store；把 panel 操作接到 ApiClient；操作失敗顯示 `ApiError.message`。

## 7. 測試策略

### 後端（pytest，可自動化）

- **遷移回填**：套用 migration 後 group creator role=`admin`、其餘=`member`、direct=`member`；既有訊息 kind=`user`。
- **權限矩陣**：每支端點 admin / 一般成員 / 非成員 → 允許 / 403 / 404；對 direct 呼叫 → 400。
- **加成員**：好友 `user_id` OK；非好友 `email` OK；查無 email→404；已是成員→400；產生 system 訊息。
- **移除 / 退出 / 不變式**：移除他人 OK；退出 OK；最後一位 admin 退出 / 被降 / 被移除一律 400；最後一位成員退出 → 對話與訊息被刪（查 DB 確認）。
- **改名 / 角色**：改名寫 system 訊息；升 admin、降 member；降最後 admin→400；對已是該角色者 no-op。
- **WS 廣播**：兩個 TestClient WS 連線，驗 admin 加人後其他在線成員收到 `message`(system) + `conversation_updated`；被移除者收到 `conversation_removed`。

### 前端（Vitest + Testing Library）

- `groupPermissions` 純函式（isAdmin / adminCount / canManage / 最後 admin 判定）。
- store：`conversation_updated` 觸發 refetch、`conversation_removed` 移除對話並在 active 時清空。
- `GroupInfoPanel` 依角色渲染（admin 看到管理控制；一般成員只見唯讀 + 退出）。
- `Thread`：`kind==='system'` 渲染置中灰字、無泡泡動作。

### E2E（手動，選配）

多帳號群組管理流程（加 / 移 / 退 / 改名 / 升降）可後補，如前幾個功能。自動化測試已涵蓋邏輯。
