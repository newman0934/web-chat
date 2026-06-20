# 語音 / 視訊通話設計（1對1）

- 日期：2026-06-21
- 狀態：設計定案，待 review
- 範圍：1對1 即時視訊（含音訊）通話，WebRTC P2P + 既有 `/ws` 轉送訊號

## 1. 目標與範圍

讓兩個互為好友的使用者在 1對1（direct）對話中發起即時視訊通話（音訊 + 視訊）。
媒體串流走 WebRTC P2P（瀏覽器對瀏覽器），後端的既有 `/ws` 只負責**轉送訊號**（signaling），不碰媒體。

### 驗收範圍

- ✅ 1對1 視訊通話（音訊 + 視訊）
- ✅ 撥號 / 接聽 / 拒接 / 掛斷
- ✅ 通話中靜音麥克風、開關鏡頭
- ✅ 對方離線時提示「無法接通」
- ✅ STUN-only（`stun:stun.l.google.com:19302`）

### 明確不做

- ❌ TURN 伺服器（嚴格 NAT 跨網路可能不通，已知限制）
- ❌ 群組通話（只支援 direct 對話）
- ❌ 通話錄製
- ❌ 通話紀錄持久化（不寫 DB）
- ❌ 純語音模式切換 UI（一律開鏡頭，使用者可自行關閉）

## 2. 整體架構與訊號協定

```
  Alice 瀏覽器                 FastAPI /ws                Bob 瀏覽器
  RTCPeerConnection  ──── signal 轉送 ───►  RTCPeerConnection
       │                  (offer/answer/ice)              │
       └──────────────── 媒體 P2P 直連（不經後端）─────────┘
```

- 媒體（音視訊）只在兩個瀏覽器之間直連，**永遠不經過後端**。
- 後端 `/ws` 只把訊號從 A 轉給 B（反之亦然），不解讀 SDP / candidate 內容。

### Client → Server 訊號類型（新增）

| type | 欄位 | 用途 |
|---|---|---|
| `call_offer` | `to_user_id`, `sdp` | 發起通話，帶 SDP offer |
| `call_answer` | `to_user_id`, `sdp` | 接聽，帶 SDP answer |
| `call_ice` | `to_user_id`, `candidate` | 交換 ICE candidate |
| `call_reject` | `to_user_id` | 拒接 |
| `call_hangup` | `to_user_id` | 掛斷（或取消撥號） |

### Server → Client 訊號類型（新增）

- 上述五種**原樣轉送**給 `to_user_id`，但附帶寄件人資訊 `from: { id, display_name }`。
- `call_unavailable { to_user_id }`：當 `call_offer` 的對象離線時，回給撥號者。

### 標準 WebRTC 握手流程

```
撥號方 Alice：
  getUserMedia → 建 RTCPeerConnection → addTrack(本地)
  → createOffer → setLocalDescription → 送 call_offer
接聽方 Bob（按接聽）：
  getUserMedia → 建 pc → setRemoteDescription(offer)
  → addTrack(本地) → createAnswer → setLocalDescription → 送 call_answer
雙方：
  onicecandidate → 送 call_ice；收到 call_ice → addIceCandidate
  ontrack → 顯示對方視訊
  掛斷：close pc + 停止本地 tracks，送 call_hangup
```

進入點：direct 對話的 Thread header 顯示 📞 按鈕 → `startCall(otherUser)`。

## 3. 後端設計

**不動 DB / model**（通話不落庫）。改 `app/ws/router.py`：

- 新增 `_handle_call_signal(...)` 處理上述 5 種類型：
  1. 解析 `to_user_id`（UUID）。
  2. 用新 helper `are_friends(db, a, b)`（查 Contact）驗證雙方為好友；非好友 → 回 `error`（reason 類似 forbidden），不轉送。
  3. 組轉送 payload：`type` + `from: { id, display_name }` + 原始 `sdp`/`candidate`（視類型）。`display_name` 取自已驗證的 WS 使用者。
  4. 對方在線 → 透過 `ConnectionManager` 推給對方所有連線；對方離線 →
     - `call_offer`：回撥號者 `call_unavailable`。
     - 其他（answer/ice/reject/hangup）：靜默丟棄（對端已不在,無意義)。

- helper `are_friends`：查 `Contact` 是否存在 `(a→b)` 關係即可（加好友為雙向建立，查一邊即足）。
- 沿用既有 `from app import db as db_module` + `db_module.SessionLocal()` 間接層（保留測試可 monkeypatch）。

## 4. 前端設計

### contracts（`frontend/contracts/index.ts`）

- 新增 5 種 `call_*` 的 `ClientWsMessage` 變體 + 對應 Server 事件（含 `from`）+ `call_unavailable`。

### `chat/src/callMachine.ts` — 純狀態機（可測）

- `callReducer(state, action)`，status：`idle | calling | incoming | connected`。
- 轉移：`start→calling`、`incoming(offer)→incoming`、`accepted/connected→connected`、
  `ended/reject/hangup/unavailable→idle`。
- 保存 `peer: { id, display_name }`、`pendingOffer`（接聽時用）。
- 純函式、不碰 WebRTC，單獨 Vitest 測。

### `chat/src/useCall.ts` — hook（持有副作用）

- 持有單一 `RTCPeerConnection`、本地 / 遠端 `MediaStream`、pending-ICE queue（remote description 設定前到達的 candidate 先暫存）。
- 回傳：`callState` / `peerName` / `localStream` / `remoteStream` / `micOn` / `cameraOn`
  + actions `startCall` / `acceptCall` / `rejectCall` / `hangup` / `toggleMic` / `toggleCamera`
  + `handleSignal(serverMsg)`（吃 server 的 call_* 事件驅動握手）。
- `ICE_SERVERS = [{ urls: 'stun:stun.l.google.com:19302' }]`。
- 透過注入的 `sendWs` callback 送訊號（與既有 WS 連線共用）。

### `chat/src/components/CallOverlay.tsx`

- 當 `callState !== 'idle'` 時覆蓋顯示：
  - `incoming`：來電者名稱 + 接聽 / 拒接。
  - `calling`：撥號中… + 取消。
  - `connected`：遠端視訊放大 + 本地小視窗（PiP）+ 控制列 🎙️ / 📷 / 📞。

### `ChatApp.tsx` 接線

- 把 server 的 `call_*` / `call_unavailable` 事件轉給 `useCall().handleSignal`。
- 掛載 `<CallOverlay>`；在 direct 對話的 Thread header 加 📞 按鈕呼叫 `startCall`。

## 5. 測試策略

### 後端（pytest，可自動化）

- 訊號轉送：`call_offer` 轉給在線好友、payload 帶 `from`；非好友 → `error`；
  對方離線 → 回撥號者 `call_unavailable`；`answer`/`ice`/`reject`/`hangup` 轉給在線好友。
- 用兩個 starlette `TestClient` WS 連線 + Contact 設定（只測「轉送」，不碰媒體）。

### 前端（Vitest，可自動化）

- `callMachine` reducer 狀態轉移（start/incoming/accept/reject/hangup/unavailable）。
- `CallOverlay` 依 state 渲染（incoming 顯示接聽/拒接；calling 顯示取消；connected 顯示控制列）。

### ⚠️ E2E 只能手動

jsdom 無 WebRTC API，`useCall` 的 `getUserMedia` / `RTCPeerConnection` **無法單元測試**。
媒體流程列為**手動驗證**：開兩個瀏覽器視窗（不同使用者）→ 撥號 → 接聽 →
雙方看到對方視訊 → 靜音 / 開關鏡頭 / 掛斷。
localhost 同機走 host candidates，不需 TURN；跨網路嚴格 NAT 可能不通（已知限制）。
