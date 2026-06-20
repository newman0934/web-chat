# 語音 / 視訊通話 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓兩個互為好友的使用者在 1對1（direct）對話中發起 WebRTC 視訊通話（音訊＋視訊），後端 `/ws` 只轉送訊號。

**Architecture:** 媒體走瀏覽器對瀏覽器的 `RTCPeerConnection` P2P，永不經過後端。既有 FastAPI `/ws` 新增 5 種 `call_*` 訊號類型，僅在好友之間轉送 SDP / ICE，不解讀內容、不落庫。前端用純狀態機 `callMachine` + 副作用 hook `useCall` + 覆蓋元件 `CallOverlay`，由 `ChatApp` 接線。

**Tech Stack:** FastAPI WebSocket、SQLAlchemy async（僅查詢 Contact）、pytest + starlette TestClient；React 18 + Vite、Vitest + Testing Library、WebRTC（`getUserMedia` / `RTCPeerConnection`）。

## Global Constraints

- 通話**不落庫**：不新增任何 model / migration，後端只查 `Contact`。
- STUN-only：`ICE_SERVERS = [{ urls: 'stun:stun.l.google.com:19302' }]`，不設 TURN。
- 只支援 `direct` 對話發話；非好友訊號一律拒絕（回 `error`，reason `forbidden`）。
- WS 訊號攜帶結構化欄位：`sdp: RTCSessionDescriptionInit`、`candidate: RTCIceCandidateInit`（後端原樣轉送，視為不透明）。
- 好友判定查單向即可：加好友時雙向建立兩筆 `Contact`，故 `where(user_id==a, contact_user_id==b)` 命中即為好友。
- WS DB 存取維持 `from app import db as db_module` + `db_module.SessionLocal()` 間接層（測試需 monkeypatch）。
- Commit 標題格式：`[voice-video][type][scope] description`，type ∈ feat|fix|docs|test|refactor|chore，內文結尾保留 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 前端 remote 改動需 `npm run build` 後 `preview` 才會反映到 host（手動 E2E 時注意）。

---

### Task 1: 後端 — 好友判定 helper + WS `call_*` 訊號轉送

**Files:**
- Modify: `backend/app/services/conversations.py`（新增 `are_friends`；import 加 `Contact`）
- Modify: `backend/app/ws/router.py`（新增 `_handle_call_signal` 與分派）
- Test: `backend/tests/test_ws_call.py`（新建）

**Interfaces:**
- Produces:
  - `are_friends(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool`
  - WS 協定：Client→Server `call_offer{to_user_id, sdp}` / `call_answer{to_user_id, sdp}` / `call_ice{to_user_id, candidate}` / `call_reject{to_user_id}` / `call_hangup{to_user_id}`；Server→Client 同型別並附 `from:{id, display_name}`，以及 `call_unavailable{to_user_id}`。

- [ ] **Step 1: 寫失敗測試** — 新建 `backend/tests/test_ws_call.py`

```python
import pytest
from starlette.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.asyncio


async def _setup(client, register_user, auth_headers):
    alice = await register_user("vva@example.com", "Alice")
    bob = await register_user("vvb@example.com", "Bob")
    await client.post("/contacts", json={"email": "vvb@example.com"}, headers=auth_headers(alice))
    aid = (await client.get("/users/me", headers=auth_headers(alice))).json()["id"]
    bid = (await client.get("/users/me", headers=auth_headers(bob))).json()["id"]
    return alice, bob, aid, bid


async def test_call_offer_relayed_to_online_friend(client, register_user, auth_headers):
    alice, bob, aid, bid = await _setup(client, register_user, auth_headers)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={bob}") as ws_bob, \
             tc.websocket_connect(f"/ws?token={alice}") as ws_alice:
            ws_alice.send_json({
                "type": "call_offer", "to_user_id": bid,
                "sdp": {"type": "offer", "sdp": "v=0..."},
            })
            got = ws_bob.receive_json()
            assert got["type"] == "call_offer"
            assert got["from"]["id"] == aid
            assert got["from"]["display_name"] == "Alice"
            assert got["sdp"] == {"type": "offer", "sdp": "v=0..."}


async def test_call_answer_relayed(client, register_user, auth_headers):
    alice, bob, aid, bid = await _setup(client, register_user, auth_headers)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as ws_alice, \
             tc.websocket_connect(f"/ws?token={bob}") as ws_bob:
            ws_bob.send_json({
                "type": "call_answer", "to_user_id": aid,
                "sdp": {"type": "answer", "sdp": "v=0..."},
            })
            got = ws_alice.receive_json()
            assert got["type"] == "call_answer"
            assert got["from"]["id"] == bid


async def test_call_signal_rejected_for_non_friend(client, register_user, auth_headers):
    alice, bob, aid, bid = await _setup(client, register_user, auth_headers)
    outsider = await register_user("vvout@example.com", "Out")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={outsider}") as ws:
            ws.send_json({"type": "call_offer", "to_user_id": bid, "sdp": {"type": "offer", "sdp": "x"}})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert resp["reason"] == "forbidden"


async def test_call_offer_to_offline_friend_returns_unavailable(client, register_user, auth_headers):
    alice, bob, aid, bid = await _setup(client, register_user, auth_headers)
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws?token={alice}") as ws_alice:
            ws_alice.send_json({"type": "call_offer", "to_user_id": bid, "sdp": {"type": "offer", "sdp": "x"}})
            resp = ws_alice.receive_json()
            assert resp["type"] == "call_unavailable"
            assert resp["to_user_id"] == bid
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_ws_call.py -v`（於 `backend/` 目錄）
Expected: FAIL — 目前 `call_offer` 走到 `_handle_client_message` 的 else 分支，回 `{"type":"error","reason":"unknown_type"}`，斷言不符。

- [ ] **Step 3: 在 `conversations.py` 新增 `are_friends`**

把第 12 行 import 改為包含 `Contact`：

```python
from app.models import Attachment, Contact, Conversation, ConversationMember, Message, MessageRead, Reaction
```

在檔案末尾（`get_reaction_groups` 之後）新增：

```python
async def are_friends(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    """雙方是否為好友。加好友為雙向建立兩筆 Contact，故查單向即足。"""
    result = await db.execute(
        select(Contact.id).where(
            Contact.user_id == a,
            Contact.contact_user_id == b,
        )
    )
    return result.scalar_one_or_none() is not None
```

- [ ] **Step 4: 在 `ws/router.py` 新增 call 訊號處理**

在第 23-29 行的 `from app.services.conversations import (...)` 匯入區塊內加入 `are_friends,`（與其他名稱並列）。

在 `_handle_client_message`（約第 94-109 行）的 `else` 之前，插入分派：

```python
    elif msg_type in _CALL_TYPES:
        await _handle_call_signal(websocket, user, data)
```

在 `_parse_uuid` 之後新增常數與處理函式：

```python
_CALL_TYPES = {"call_offer", "call_answer", "call_ice", "call_reject", "call_hangup"}


async def _handle_call_signal(websocket: WebSocket, user: User, data: dict) -> None:
    """1對1 通話訊號轉送：只在好友之間轉送 SDP / ICE，不解讀內容、不落庫。"""
    msg_type = data["type"]
    to_id = _parse_uuid(data.get("to_user_id"))
    if to_id is None:
        await websocket.send_json({"type": "error", "reason": "invalid_payload"})
        return
    async with db_module.SessionLocal() as db:
        friends = await are_friends(db, user.id, to_id)
    if not friends:
        await websocket.send_json({"type": "error", "reason": "forbidden"})
        return

    payload: dict = {
        "type": msg_type,
        "from": {"id": str(user.id), "display_name": user.display_name},
    }
    if msg_type in ("call_offer", "call_answer"):
        payload["sdp"] = data.get("sdp")
    elif msg_type == "call_ice":
        payload["candidate"] = data.get("candidate")

    if manager.is_online(to_id):
        await manager.send_to_user(to_id, payload)
    elif msg_type == "call_offer":
        # 只有撥號（offer）需要回報對方不在線；其餘類型對端已離開，靜默丟棄。
        await websocket.send_json({"type": "call_unavailable", "to_user_id": str(to_id)})
```

- [ ] **Step 5: 跑測試確認通過**

Run: `backend/.venv/Scripts/python.exe -m pytest tests/test_ws_call.py -v`
Expected: 4 passed。

- [ ] **Step 6: 跑全套後端測試確認無回歸**

Run: `backend/.venv/Scripts/python.exe -m pytest`
Expected: 全綠（先前 54 passed + 本檔 4 = 58 passed 左右）。

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/conversations.py backend/app/ws/router.py backend/tests/test_ws_call.py
git commit -m "[voice-video][feat][ws] /ws 轉送 call_* 訊號 + are_friends 好友判定

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: contracts — 新增 `call_*` WS 型別

**Files:**
- Modify: `frontend/contracts/index.ts`（擴充 `ClientWsMessage` / `ServerWsMessage`）

**Interfaces:**
- Produces：
  - `ClientWsMessage` 新增 `call_offer` / `call_answer` / `call_ice` / `call_reject` / `call_hangup` 變體。
  - `ServerWsMessage` 新增上述五種（附 `from: CallFrom`）+ `call_unavailable`。
  - `export interface CallFrom { id: string; display_name: string }`

- [ ] **Step 1: 擴充 contracts 型別**

在 `frontend/contracts/index.ts` 的「WebSocket 訊息協定」區塊（約第 85 行起）上方新增：

```typescript
export interface CallFrom {
  id: string;
  display_name: string;
}
```

把 `ClientWsMessage` 聯集（第 87-93 行）尾端 `react` 變體後加入 5 個 call 變體：

```typescript
export type ClientWsMessage =
  | { type: 'message'; conversation_id: string; content: string; temp_id: string; attachment_id?: string }
  | { type: 'read'; conversation_id: string }
  | { type: 'typing'; conversation_id: string }
  | { type: 'edit'; message_id: string; content: string }
  | { type: 'delete'; message_id: string }
  | { type: 'react'; message_id: string; emoji: string }
  | { type: 'call_offer'; to_user_id: string; sdp: RTCSessionDescriptionInit }
  | { type: 'call_answer'; to_user_id: string; sdp: RTCSessionDescriptionInit }
  | { type: 'call_ice'; to_user_id: string; candidate: RTCIceCandidateInit }
  | { type: 'call_reject'; to_user_id: string }
  | { type: 'call_hangup'; to_user_id: string };
```

把 `ServerWsMessage` 聯集（第 95-101 行）尾端加入 call 事件：

```typescript
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
  | { type: 'call_unavailable'; to_user_id: string };
```

- [ ] **Step 2: 跑 chat typecheck 確認契約可編譯**

Run: `cd frontend/chat && npm run typecheck`
Expected: 乾淨（contracts 變更不破壞既有 chat 程式碼；DOM 型別 `RTCSessionDescriptionInit` 在 chat 的 tsconfig `lib` 內可用）。

- [ ] **Step 3: Commit**

```bash
git add frontend/contracts/index.ts
git commit -m "[voice-video][feat][contracts] 新增 call_* WS 訊號型別

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 前端純狀態機 `callMachine`

**Files:**
- Create: `frontend/chat/src/callMachine.ts`
- Test: `frontend/chat/src/callMachine.test.ts`

**Interfaces:**
- Consumes：無（純函式，自含型別）。
- Produces：
  - `type CallStatus = 'idle' | 'calling' | 'incoming' | 'connected'`
  - `interface CallPeer { id: string; display_name: string }`
  - `interface CallState { status: CallStatus; peer: CallPeer | null; pendingOffer: RTCSessionDescriptionInit | null }`
  - `const initialCallState: CallState`
  - `function callReducer(state: CallState, action: CallAction): CallState`
  - `type CallAction =`
    `{ type: 'START'; peer: CallPeer }` |
    `{ type: 'INCOMING'; peer: CallPeer; sdp: RTCSessionDescriptionInit }` |
    `{ type: 'ACCEPTED' }` | `{ type: 'CONNECTED' }` | `{ type: 'END' }`

- [ ] **Step 1: 寫失敗測試** — `frontend/chat/src/callMachine.test.ts`

```typescript
import { describe, expect, it } from 'vitest';

import { callReducer, initialCallState } from './callMachine';

const peer = { id: 'u-bob', display_name: 'Bob' };
const sdp = { type: 'offer', sdp: 'v=0' } as RTCSessionDescriptionInit;

describe('callReducer', () => {
  it('START 進入 calling 並記住對方', () => {
    const s = callReducer(initialCallState, { type: 'START', peer });
    expect(s.status).toBe('calling');
    expect(s.peer).toEqual(peer);
  });

  it('idle 收到 INCOMING 進入 incoming 並暫存 offer', () => {
    const s = callReducer(initialCallState, { type: 'INCOMING', peer, sdp });
    expect(s.status).toBe('incoming');
    expect(s.pendingOffer).toEqual(sdp);
  });

  it('忙線（非 idle）時 INCOMING 不改變狀態', () => {
    const calling = callReducer(initialCallState, { type: 'START', peer });
    const s = callReducer(calling, { type: 'INCOMING', peer: { id: 'x', display_name: 'X' }, sdp });
    expect(s).toBe(calling);
  });

  it('incoming 收到 ACCEPTED 進入 connected', () => {
    const incoming = callReducer(initialCallState, { type: 'INCOMING', peer, sdp });
    const s = callReducer(incoming, { type: 'ACCEPTED' });
    expect(s.status).toBe('connected');
  });

  it('calling 收到 CONNECTED（對方接聽）進入 connected', () => {
    const calling = callReducer(initialCallState, { type: 'START', peer });
    const s = callReducer(calling, { type: 'CONNECTED' });
    expect(s.status).toBe('connected');
  });

  it('END 一律回到 idle 並清空', () => {
    const calling = callReducer(initialCallState, { type: 'START', peer });
    const s = callReducer(calling, { type: 'END' });
    expect(s).toEqual(initialCallState);
  });
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/callMachine.test.ts`
Expected: FAIL — `Cannot find module './callMachine'`。

- [ ] **Step 3: 實作 `callMachine.ts`**

```typescript
// 1對1 通話的純狀態機（不碰 WebRTC，可獨立單元測試）。
// status 流：idle → calling/incoming → connected → idle。

export type CallStatus = 'idle' | 'calling' | 'incoming' | 'connected';

export interface CallPeer {
  id: string;
  display_name: string;
}

export interface CallState {
  status: CallStatus;
  /** 對話中的對方（撥號目標或來電者）。 */
  peer: CallPeer | null;
  /** 來電時暫存對方的 SDP offer，接聽時用來建立 answer。 */
  pendingOffer: RTCSessionDescriptionInit | null;
}

export type CallAction =
  | { type: 'START'; peer: CallPeer }
  | { type: 'INCOMING'; peer: CallPeer; sdp: RTCSessionDescriptionInit }
  | { type: 'ACCEPTED' }
  | { type: 'CONNECTED' }
  | { type: 'END' };

export const initialCallState: CallState = {
  status: 'idle',
  peer: null,
  pendingOffer: null,
};

/** 依 action 推進通話狀態；END 一律回 idle。 */
export function callReducer(state: CallState, action: CallAction): CallState {
  switch (action.type) {
    case 'START':
      return { status: 'calling', peer: action.peer, pendingOffer: null };
    case 'INCOMING':
      // 忙線（已在通話流程中）時忽略新來電，維持現狀（簡化：不另作忙線通知）。
      if (state.status !== 'idle') return state;
      return { status: 'incoming', peer: action.peer, pendingOffer: action.sdp };
    case 'ACCEPTED':
      if (state.status !== 'incoming') return state;
      return { ...state, status: 'connected' };
    case 'CONNECTED':
      return { ...state, status: 'connected' };
    case 'END':
      return initialCallState;
    default:
      return state;
  }
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/callMachine.test.ts`
Expected: 6 passed。

- [ ] **Step 5: Commit**

```bash
git add frontend/chat/src/callMachine.ts frontend/chat/src/callMachine.test.ts
git commit -m "[voice-video][feat][chat] 通話純狀態機 callReducer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 前端 `useCall` hook（WebRTC 副作用）

**Files:**
- Create: `frontend/chat/src/useCall.ts`

**Interfaces:**
- Consumes：`callReducer` / `initialCallState` / `CallPeer`（Task 3）；`ClientWsMessage` / `ServerWsMessage`（Task 2）。
- Produces：
  - `interface UseCall { callState: CallStatus; peer: CallPeer | null; localStream: MediaStream | null; remoteStream: MediaStream | null; micOn: boolean; cameraOn: boolean; startCall: (peer: CallPeer) => Promise<void>; acceptCall: () => Promise<void>; rejectCall: () => void; hangup: () => void; toggleMic: () => void; toggleCamera: () => void; handleSignal: (msg: ServerWsMessage) => void }`
  - `function useCall(send: (m: ClientWsMessage) => boolean): UseCall`

> **測試說明（重要）：** jsdom 無 WebRTC API（`getUserMedia` / `RTCPeerConnection`），本 hook 的媒體流程**無法單元測試**，故無對應 `.test.ts`。正確性由 Task 6 的手動 E2E（兩個瀏覽器）驗證。狀態轉移邏輯已由 Task 3 的 `callReducer` 涵蓋。本任務的「驗收」= `npm run typecheck` 乾淨 + 程式碼符合下方實作。

- [ ] **Step 1: 實作 `useCall.ts`**

```typescript
// 通話副作用 hook：持有單一 RTCPeerConnection、本地/遠端媒體串流，
// 串接 callReducer 與 /ws 訊號。媒體走 P2P，永不經過後端。
// 注意：jsdom 無 WebRTC API，本檔以手動 E2E（兩個瀏覽器）驗證，無單元測試。

import { useCallback, useReducer, useRef, useState } from 'react';

import type { ClientWsMessage, ServerWsMessage } from '../../contracts';
import {
  callReducer,
  initialCallState,
  type CallPeer,
  type CallStatus,
} from './callMachine';

const ICE_SERVERS: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }];

export interface UseCall {
  callState: CallStatus;
  peer: CallPeer | null;
  localStream: MediaStream | null;
  remoteStream: MediaStream | null;
  micOn: boolean;
  cameraOn: boolean;
  startCall: (peer: CallPeer) => Promise<void>;
  acceptCall: () => Promise<void>;
  rejectCall: () => void;
  hangup: () => void;
  toggleMic: () => void;
  toggleCamera: () => void;
  handleSignal: (msg: ServerWsMessage) => void;
}

/** 管理 1對1 WebRTC 通話的生命週期與訊號收發。 */
export function useCall(send: (m: ClientWsMessage) => boolean): UseCall {
  const [state, dispatch] = useReducer(callReducer, initialCallState);
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const [micOn, setMicOn] = useState(true);
  const [cameraOn, setCameraOn] = useState(true);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localRef = useRef<MediaStream | null>(null);
  // remoteDescription 設定前到達的 ICE candidate 先排隊，設定後再補加。
  const pendingIce = useRef<RTCIceCandidateInit[]>([]);
  // state 在非同步 callback 內可能過期，用 ref 取最新值。
  const stateRef = useRef(state);
  stateRef.current = state;

  /** 建立 RTCPeerConnection：綁定 ICE 送出與遠端 track 接收。 */
  const createPc = useCallback(
    (peerId: string): RTCPeerConnection => {
      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      pc.onicecandidate = (e) => {
        if (e.candidate) {
          send({ type: 'call_ice', to_user_id: peerId, candidate: e.candidate.toJSON() });
        }
      };
      pc.ontrack = (e) => {
        setRemoteStream(e.streams[0] ?? null);
      };
      pcRef.current = pc;
      return pc;
    },
    [send],
  );

  /** 取得本地音視訊串流並記錄。 */
  const getLocalMedia = useCallback(async (): Promise<MediaStream> => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    localRef.current = stream;
    setLocalStream(stream);
    setMicOn(true);
    setCameraOn(true);
    return stream;
  }, []);

  /** 套用排隊中的 ICE candidate（remoteDescription 設定後呼叫）。 */
  const flushIce = useCallback(async () => {
    const pc = pcRef.current;
    if (!pc) return;
    for (const c of pendingIce.current) {
      try {
        await pc.addIceCandidate(c);
      } catch {
        // 忽略無效 candidate
      }
    }
    pendingIce.current = [];
  }, []);

  /** 關閉連線、停止本地 track、清空遠端串流與 ICE 佇列。 */
  const cleanup = useCallback(() => {
    pcRef.current?.close();
    pcRef.current = null;
    localRef.current?.getTracks().forEach((t) => t.stop());
    localRef.current = null;
    pendingIce.current = [];
    setLocalStream(null);
    setRemoteStream(null);
  }, []);

  const startCall = useCallback(
    async (peer: CallPeer) => {
      dispatch({ type: 'START', peer });
      const stream = await getLocalMedia();
      const pc = createPc(peer.id);
      stream.getTracks().forEach((t) => pc.addTrack(t, stream));
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      send({ type: 'call_offer', to_user_id: peer.id, sdp: offer });
    },
    [createPc, getLocalMedia, send],
  );

  const acceptCall = useCallback(async () => {
    const cur = stateRef.current;
    if (cur.status !== 'incoming' || !cur.peer || !cur.pendingOffer) return;
    const peer = cur.peer;
    const stream = await getLocalMedia();
    const pc = createPc(peer.id);
    await pc.setRemoteDescription(cur.pendingOffer);
    stream.getTracks().forEach((t) => pc.addTrack(t, stream));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    await flushIce();
    send({ type: 'call_answer', to_user_id: peer.id, sdp: answer });
    dispatch({ type: 'ACCEPTED' });
  }, [createPc, flushIce, getLocalMedia, send]);

  const rejectCall = useCallback(() => {
    const peer = stateRef.current.peer;
    if (peer) send({ type: 'call_reject', to_user_id: peer.id });
    cleanup();
    dispatch({ type: 'END' });
  }, [cleanup, send]);

  const hangup = useCallback(() => {
    const peer = stateRef.current.peer;
    if (peer) send({ type: 'call_hangup', to_user_id: peer.id });
    cleanup();
    dispatch({ type: 'END' });
  }, [cleanup, send]);

  const toggleMic = useCallback(() => {
    const stream = localRef.current;
    if (!stream) return;
    const next = !stateRefMic.current;
    stream.getAudioTracks().forEach((t) => (t.enabled = next));
    stateRefMic.current = next;
    setMicOn(next);
  }, []);

  const toggleCamera = useCallback(() => {
    const stream = localRef.current;
    if (!stream) return;
    const next = !stateRefCam.current;
    stream.getVideoTracks().forEach((t) => (t.enabled = next));
    stateRefCam.current = next;
    setCameraOn(next);
  }, []);

  // toggle 用 ref 追最新開關狀態，避免 useCallback 閉包過期。
  const stateRefMic = useRef(micOn);
  stateRefMic.current = micOn;
  const stateRefCam = useRef(cameraOn);
  stateRefCam.current = cameraOn;

  const handleSignal = useCallback(
    (msg: ServerWsMessage) => {
      switch (msg.type) {
        case 'call_offer':
          dispatch({ type: 'INCOMING', peer: msg.from, sdp: msg.sdp });
          break;
        case 'call_answer': {
          const pc = pcRef.current;
          if (!pc) return;
          void pc.setRemoteDescription(msg.sdp).then(flushIce);
          dispatch({ type: 'CONNECTED' });
          break;
        }
        case 'call_ice': {
          const pc = pcRef.current;
          if (pc && pc.remoteDescription) {
            void pc.addIceCandidate(msg.candidate).catch(() => {});
          } else {
            pendingIce.current.push(msg.candidate);
          }
          break;
        }
        case 'call_reject':
        case 'call_hangup':
        case 'call_unavailable':
          cleanup();
          dispatch({ type: 'END' });
          break;
        default:
          break;
      }
    },
    [cleanup, flushIce],
  );

  return {
    callState: state.status,
    peer: state.peer,
    localStream,
    remoteStream,
    micOn,
    cameraOn,
    startCall,
    acceptCall,
    rejectCall,
    hangup,
    toggleMic,
    toggleCamera,
    handleSignal,
  };
}
```

- [ ] **Step 2: 跑 typecheck 確認乾淨**

Run: `cd frontend/chat && npm run typecheck`
Expected: 乾淨（無型別錯誤）。

> 若 typecheck 對 `stateRefMic`／`stateRefCam` 在宣告前使用報錯（TDZ / use-before-declare），把這兩個 `useRef` 宣告**上移**到 `toggleMic` 之前即可——它們是 hook，必須在每次 render 以固定順序呼叫，位置只要在使用前、且在元件頂層即可。

- [ ] **Step 3: Commit**

```bash
git add frontend/chat/src/useCall.ts
git commit -m "[voice-video][feat][chat] useCall hook 管理 WebRTC 通話與訊號

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: 前端 `CallOverlay` 元件

**Files:**
- Create: `frontend/chat/src/components/CallOverlay.tsx`
- Test: `frontend/chat/src/components/CallOverlay.test.tsx`

**Interfaces:**
- Consumes：`CallStatus`（Task 3）。
- Produces：
  - `interface CallOverlayProps { status: CallStatus; peerName: string | null; localStream: MediaStream | null; remoteStream: MediaStream | null; micOn: boolean; cameraOn: boolean; onAccept: () => void; onReject: () => void; onHangup: () => void; onToggleMic: () => void; onToggleCamera: () => void }`
  - `function CallOverlay(props: CallOverlayProps): JSX.Element | null`

- [ ] **Step 1: 寫失敗測試** — `frontend/chat/src/components/CallOverlay.test.tsx`

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CallOverlay } from './CallOverlay';

const base = {
  peerName: 'Bob',
  localStream: null,
  remoteStream: null,
  micOn: true,
  cameraOn: true,
  onAccept: vi.fn(),
  onReject: vi.fn(),
  onHangup: vi.fn(),
  onToggleMic: vi.fn(),
  onToggleCamera: vi.fn(),
};

describe('CallOverlay', () => {
  it('idle 時不渲染', () => {
    const { container } = render(<CallOverlay status="idle" {...base} />);
    expect(container.firstChild).toBeNull();
  });

  it('incoming 顯示來電者與接聽/拒接', () => {
    render(<CallOverlay status="incoming" {...base} />);
    expect(screen.getByText(/Bob/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '接聽' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '拒接' })).toBeInTheDocument();
  });

  it('calling 顯示撥號中與取消', () => {
    render(<CallOverlay status="calling" {...base} />);
    expect(screen.getByText(/撥號中/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument();
  });

  it('connected 顯示靜音/鏡頭/掛斷控制', () => {
    render(<CallOverlay status="connected" {...base} />);
    expect(screen.getByRole('button', { name: '靜音' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '關閉鏡頭' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '掛斷' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `cd frontend/chat && npx vitest run src/components/CallOverlay.test.tsx`
Expected: FAIL — `Cannot find module './CallOverlay'`。

- [ ] **Step 3: 實作 `CallOverlay.tsx`**

```tsx
// 通話覆蓋層：依通話狀態顯示來電 / 撥號中 / 通話中畫面。
// <video> 的 srcObject 經 ref 設定（jsdom 不支援播放，但不影響測試斷言文字/按鈕）。

import { useEffect, useRef } from 'react';

import type { CallStatus } from '../callMachine';

export interface CallOverlayProps {
  status: CallStatus;
  peerName: string | null;
  localStream: MediaStream | null;
  remoteStream: MediaStream | null;
  micOn: boolean;
  cameraOn: boolean;
  onAccept: () => void;
  onReject: () => void;
  onHangup: () => void;
  onToggleMic: () => void;
  onToggleCamera: () => void;
}

/** 把 MediaStream 綁到 <video>（srcObject 無法用 JSX 屬性設定）。 */
function useVideoStream(stream: MediaStream | null) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (ref.current) ref.current.srcObject = stream;
  }, [stream]);
  return ref;
}

/** 全螢幕通話覆蓋層；status 為 idle 時不渲染。 */
export function CallOverlay({
  status, peerName, localStream, remoteStream, micOn, cameraOn,
  onAccept, onReject, onHangup, onToggleMic, onToggleCamera,
}: CallOverlayProps) {
  const remoteRef = useVideoStream(remoteStream);
  const localRef = useVideoStream(localStream);

  if (status === 'idle') return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-900/95 text-white">
      {status === 'incoming' && (
        <div className="flex flex-col items-center gap-6">
          <p className="text-xl"><span className="font-semibold">{peerName}</span> 來電…</p>
          <div className="flex gap-4">
            <button onClick={onAccept} className="rounded-full bg-green-600 px-6 py-3 font-medium hover:bg-green-700">接聽</button>
            <button onClick={onReject} className="rounded-full bg-red-600 px-6 py-3 font-medium hover:bg-red-700">拒接</button>
          </div>
        </div>
      )}

      {status === 'calling' && (
        <div className="flex flex-col items-center gap-6">
          <p className="text-xl">撥號中… <span className="font-semibold">{peerName}</span></p>
          <button onClick={onHangup} className="rounded-full bg-red-600 px-6 py-3 font-medium hover:bg-red-700">取消</button>
        </div>
      )}

      {status === 'connected' && (
        <>
          <video ref={remoteRef} autoPlay playsInline className="max-h-[70vh] max-w-[90vw] rounded-lg bg-black" />
          <video ref={localRef} autoPlay playsInline muted className="absolute bottom-24 right-6 h-32 w-44 rounded-lg border border-white/30 bg-black object-cover" />
          <div className="absolute bottom-8 flex gap-4">
            <button onClick={onToggleMic} className="rounded-full bg-white/15 px-5 py-3 hover:bg-white/25" aria-label={micOn ? '靜音' : '取消靜音'}>
              {micOn ? '🎙️' : '🔇'}
            </button>
            <button onClick={onToggleCamera} className="rounded-full bg-white/15 px-5 py-3 hover:bg-white/25" aria-label={cameraOn ? '關閉鏡頭' : '開啟鏡頭'}>
              {cameraOn ? '📷' : '🚫'}
            </button>
            <button onClick={onHangup} className="rounded-full bg-red-600 px-5 py-3 hover:bg-red-700" aria-label="掛斷">📞</button>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `cd frontend/chat && npx vitest run src/components/CallOverlay.test.tsx`
Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add frontend/chat/src/components/CallOverlay.tsx frontend/chat/src/components/CallOverlay.test.tsx
git commit -m "[voice-video][feat][chat] CallOverlay 通話覆蓋層 UI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: 接線 `ChatApp` + Thread 撥號鈕，並更新文件

**Files:**
- Modify: `frontend/chat/src/ChatApp.tsx`（掛 `useCall` / `CallOverlay`、路由 call 訊號、傳 `onStartCall`）
- Modify: `frontend/chat/src/components/Thread.tsx`（header 加 📞 按鈕）
- Modify: `progress.md`、`docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md`（把「語音/視訊」從未做改為已做）

**Interfaces:**
- Consumes：`useCall`（Task 4）、`CallOverlay`（Task 5）、`ClientWsMessage`/`ServerWsMessage`（Task 2）。
- Thread 新增 prop：`onStartCall?: () => void`（僅 direct 對話時由 ChatApp 提供）。

- [ ] **Step 1: Thread 加撥號鈕**

在 `Thread.tsx` 的 `ThreadProps`（第 10-25 行）尾端加入：

```typescript
  onStartCall?: () => void;
```

在函式參數解構（第 28-43 行）尾端加入 `onStartCall,`。

把 header（第 77-79 行）改為標題 + 可選 📞 按鈕：

```tsx
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <h2 className="font-semibold text-slate-800">{title}</h2>
        {onStartCall && (
          <button
            type="button"
            aria-label="視訊通話"
            onClick={onStartCall}
            className="rounded-lg px-3 py-1 text-lg hover:bg-slate-100"
          >
            📞
          </button>
        )}
      </header>
```

- [ ] **Step 2: ChatApp 掛 useCall 與 CallOverlay**

在 import 區（第 5-13 行）加入：

```typescript
import { CallOverlay } from './components/CallOverlay';
import { useCall } from './useCall';
```

在 `socketRef.current = socket;`（第 120 行）之後插入 useCall 接線：

```typescript
  // 通話：用穩定的 wsSend 包裝 socketRef，讓 useCall 不因 socket 換參考而重建。
  const wsSend = useCallback(
    (m: Parameters<typeof socket.send>[0]) => socketRef.current?.send(m) ?? false,
    [],
  );
  const call = useCall(wsSend);
  const callRef = useRef(call);
  callRef.current = call;
```

在 `handleServerMessage` 的 `switch`（第 77-103 行）內，於 `default:` 之前加入 call 事件路由：

```typescript
        case 'call_offer':
        case 'call_answer':
        case 'call_ice':
        case 'call_reject':
        case 'call_hangup':
        case 'call_unavailable':
          callRef.current.handleSignal(msg);
          break;
```

- [ ] **Step 3: 傳 onStartCall 給 Thread 並掛 CallOverlay**

在算出 `activeConv` 之後（第 261 行附近）新增撥號 handler：

```typescript
  const otherUser = activeConv && activeConv.type === 'direct' ? activeConv.other_user : null;
  const startCall = useCallback(() => {
    if (otherUser) call.startCall({ id: otherUser.id, display_name: otherUser.display_name });
  }, [otherUser, call]);
```

在 `<Thread ... />` 的 props（第 286-301 行）尾端、`onReact={toggleReaction}` 之後加入：

```tsx
          onStartCall={otherUser ? startCall : undefined}
```

把最外層 `return` 的 `<div className="flex h-screen">…</div>`（第 272-308 行）末尾、緊接 `</div>` 之前插入覆蓋層：

```tsx
      <CallOverlay
        status={call.callState}
        peerName={call.peer?.display_name ?? otherUser?.display_name ?? null}
        localStream={call.localStream}
        remoteStream={call.remoteStream}
        micOn={call.micOn}
        cameraOn={call.cameraOn}
        onAccept={call.acceptCall}
        onReject={call.rejectCall}
        onHangup={call.hangup}
        onToggleMic={call.toggleMic}
        onToggleCamera={call.toggleCamera}
      />
```

- [ ] **Step 4: 跑 chat 測試與 typecheck 確認無回歸**

Run: `cd frontend/chat && npx vitest run && npm run typecheck`
Expected: 全綠（先前 28 + callMachine 6 + CallOverlay 4 = 38 passed 左右）、tsc 乾淨。

- [ ] **Step 5: 手動 E2E（兩個瀏覽器，無法自動化）**

依 CLAUDE.md 啟動整套（backend + 三個前端，remote 需 build+preview）。
用兩個瀏覽器視窗（或一般視窗 + 無痕）分別登入 `alice@example.com` 與 `bob@example.com`（密碼 `secret123`，互為好友）。
Alice 開與 Bob 的 direct 對話 → 按 header 📞 → 允許相機/麥克風 → Bob 端跳出「Alice 來電」→ 按「接聽」→ 確認雙方看到對方視訊 → 測試靜音 🎙️ / 關鏡頭 📷 → 任一方按掛斷 📞，雙方覆蓋層關閉。
（localhost 同機走 host candidates，不需 TURN。）截圖存 `call-01`（撥號中）、`call-02`（接通雙視訊）。

- [ ] **Step 6: 更新文件**

`progress.md`：在「一句話現況」與功能段落加入「語音/視訊通話（1對1，WebRTC P2P）」已完成，註明 E2E 為手動驗證、無 TURN 限制。
`docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md`：把「明確不做」清單的 `❌ 語音 / 視訊` 改為 `✅ ~~語音 / 視訊~~ —— 已於 2026-06-21 實作（最小可用），見 [語音/視訊設計](2026-06-21-voice-video-design.md)。`

- [ ] **Step 7: Commit**

```bash
git add frontend/chat/src/ChatApp.tsx frontend/chat/src/components/Thread.tsx progress.md docs/superpowers/specs/2026-06-19-chat-web-mvp-design.md
git commit -m "[voice-video][feat][chat] ChatApp 接線通話 + Thread 撥號鈕 + 更新文件

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage（對照 spec 五段）：**
- §1 範圍（音視訊、撥號/接聽/拒接/掛斷、靜音/鏡頭、離線提示、STUN-only）→ Task 1（離線→call_unavailable、STUN 由前端設定）、Task 4（startCall/acceptCall/rejectCall/hangup/toggleMic/toggleCamera）、Task 5（UI）。✅
- §2 架構與 5 種訊號協定 + `from` + `call_unavailable` → Task 1（後端轉送）、Task 2（contracts 型別）。✅
- §3 後端 `_handle_call_signal` + `are_friends` + 不落庫 + db_module 間接層 → Task 1。✅
- §4 前端 `callMachine` / `useCall` / `CallOverlay` / ChatApp 接線 + 📞 鈕 → Task 3/4/5/6。✅
- §5 測試策略（後端轉送 pytest、前端 reducer/overlay vitest、媒體手動 E2E）→ Task 1 測試、Task 3/5 測試、Task 6 Step 5 手動。✅

**Placeholder scan：** 無 TBD/TODO；每個程式步驟均附完整程式碼與確切指令。✅

**Type consistency：**
- `sdp: RTCSessionDescriptionInit` / `candidate: RTCIceCandidateInit` 在 contracts（Task 2）、useCall（Task 4）、callMachine（Task 3 `pendingOffer`）一致。
- `CallPeer{id, display_name}` 與後端轉送的 `from:{id, display_name}` 對齊（Task 1 payload ↔ Task 4 `dispatch INCOMING peer: msg.from`）。
- `CallStatus` 由 callMachine 匯出，useCall 回傳 `callState: CallStatus`，CallOverlay `status: CallStatus` 一致。
- WS send 簽章 `(m: ClientWsMessage) => boolean` 與 `useChatSocket` 的 `send` 一致；ChatApp 以 `wsSend` 包裝。✅

無缺口。
