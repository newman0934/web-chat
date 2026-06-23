/**
 * E2E 測試共用輔助函式。
 *
 * 所有 REST 互動（register / login / addContact / getConversations 等）
 * 直接走 http://localhost:8000 API，不透過 UI，速度快且不依賴 UI 細節。
 */

import { APIRequestContext, Page } from "@playwright/test";

const API = "http://localhost:8000";

// ── REST 輔助函式 ──────────────────────────────────────────────────────────────

/** 建立測試用帳號，回傳 JWT token。若 email 已存在（409）則改用 login。 */
export async function apiRegister(
  request: APIRequestContext,
  email: string,
  displayName: string,
  password = "TestPass123!"
): Promise<string> {
  const res = await request.post(`${API}/auth/register`, {
    data: { email, display_name: displayName, password },
  });
  if (res.status() === 201) {
    const body = await res.json();
    return body.access_token as string;
  }
  if (res.status() === 409) {
    // 已存在 → login
    return apiLogin(request, email, password);
  }
  throw new Error(
    `apiRegister failed: ${res.status()} ${await res.text()}`
  );
}

/** 登入並回傳 JWT token。 */
export async function apiLogin(
  request: APIRequestContext,
  email: string,
  password = "TestPass123!"
): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email, password },
  });
  if (!res.ok()) throw new Error(`apiLogin failed: ${res.status()} ${await res.text()}`);
  const body = await res.json();
  return body.access_token as string;
}

/** 加好友（idempotent — 409 視為成功）。 */
export async function apiAddContact(
  request: APIRequestContext,
  token: string,
  targetEmail: string
): Promise<{ conversation_id: string }> {
  const res = await request.post(`${API}/contacts`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { email: targetEmail },
  });
  if (res.status() === 201) return res.json();
  if (res.status() === 409) {
    // 已是好友 — 從清單撈對話 id
    const contacts = await apiGetContacts(request, token);
    const found = contacts.find((c: any) => c.email === targetEmail);
    if (found) return { conversation_id: found.conversation_id };
  }
  throw new Error(`apiAddContact failed: ${res.status()} ${await res.text()}`);
}

/** 取好友清單。 */
export async function apiGetContacts(
  request: APIRequestContext,
  token: string
): Promise<any[]> {
  const res = await request.get(`${API}/contacts`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) throw new Error(`apiGetContacts failed: ${res.status()}`);
  return res.json();
}

/** 取得目前使用者（含 id），用來組 member_user_ids。 */
export async function apiMe(
  request: APIRequestContext,
  token: string
): Promise<{ id: string; email: string; display_name: string }> {
  const res = await request.get(`${API}/users/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) throw new Error(`apiMe failed: ${res.status()}`);
  return res.json();
}

/** 建群（name + 成員 user id 陣列，成員須為 creator 的好友）。回傳 ConversationOut。 */
export async function apiCreateGroup(
  request: APIRequestContext,
  token: string,
  name: string,
  memberUserIds: string[]
): Promise<any> {
  const res = await request.post(`${API}/conversations/groups`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { name, member_user_ids: memberUserIds },
  });
  if (res.status() !== 201)
    throw new Error(`apiCreateGroup failed: ${res.status()} ${await res.text()}`);
  return res.json();
}

/** 取對話歷史，回傳訊息陣列（最新在後）。 */
export async function apiGetMessages(
  request: APIRequestContext,
  token: string,
  conversationId: string,
  limit = 50
): Promise<any[]> {
  const res = await request.get(
    `${API}/conversations/${conversationId}/messages?limit=${limit}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!res.ok()) throw new Error(`apiGetMessages failed: ${res.status()}`);
  return res.json();
}

// ── WebSocket 輔助函式 ──────────────────────────────────────────────────────────

/**
 * 在瀏覽器內建立 WebSocket 連線，送出訊息並等待指定類型的回應。
 *
 * 因為 Node 端 `ws` 套件在 Playwright 環境下需要額外設定 SSL，
 * 這裡改用 `page.evaluate` 在瀏覽器內建原生 WebSocket，藉以迴避跨環境問題。
 */
export async function wsRequest(
  page: Page,
  token: string,
  payload: object,
  waitForType: string,
  timeoutMs = 8000
): Promise<any> {
  return page.evaluate(
    async ({ token, payload, waitForType, timeoutMs, apiUrl }) => {
      const wsUrl = `${apiUrl.replace("http", "ws")}/ws?token=${token}`;
      return new Promise<any>((resolve, reject) => {
        const ws = new WebSocket(wsUrl);
        const timer = setTimeout(() => {
          ws.close();
          reject(new Error(`wsRequest timeout waiting for type="${waitForType}"`));
        }, timeoutMs);

        ws.onopen = () => {
          ws.send(JSON.stringify(payload));
        };
        ws.onmessage = (e) => {
          try {
            const msg = JSON.parse(e.data);
            if (msg.type === waitForType || (waitForType === "error" && msg.type === "error")) {
              clearTimeout(timer);
              ws.close();
              resolve(msg);
            }
          } catch (_) {}
        };
        ws.onerror = (e) => {
          clearTimeout(timer);
          reject(new Error("WebSocket error"));
        };
      });
    },
    { token, payload, waitForType, timeoutMs, apiUrl: API }
  );
}

/**
 * 透過 WebSocket 送一則 text 訊息，等待 ack 並回傳訊息物件。
 * 這是 "Alice sends a message over WS" 的標準流程。
 */
export async function wsSendMessage(
  page: Page,
  token: string,
  conversationId: string,
  content: string
): Promise<any> {
  const ack = await wsRequest(
    page,
    token,
    {
      type: "message",
      conversation_id: conversationId,
      content,
      temp_id: `tmp-${Date.now()}`,
    },
    "ack"
  );
  return ack.message;
}

/**
 * 在一個 page 上開一條「持續監聽」的 WebSocket，把收到的訊息全部累積到
 * `window.__wsMessages`。回傳後 socket 仍存活（掛在 window 上）。
 *
 * 用法：先在收件人的 page 上 wsOpenCollector → 再用另一條路徑（REST/別人 WS）
 * 觸發群組操作 → 用 wsWaitForCollected 斷言這條連線收到了對應廣播。
 * 每個 page 各自獨立的 __wsMessages，故多位收件人請各開一個 context/page。
 */
export async function wsOpenCollector(page: Page, token: string): Promise<void> {
  await page.evaluate(
    ({ token, apiUrl }) =>
      new Promise<void>((resolve, reject) => {
        const wsUrl = `${apiUrl.replace("http", "ws")}/ws?token=${token}`;
        const ws = new WebSocket(wsUrl);
        (window as any).__wsMessages = [];
        ws.onmessage = (e) => {
          try {
            (window as any).__wsMessages.push(JSON.parse(e.data));
          } catch (_) {}
        };
        ws.onopen = () => resolve();
        ws.onerror = () => reject(new Error("wsOpenCollector: WebSocket error"));
        (window as any).__ws = ws; // 持有參照避免被 GC
      }),
    { token, apiUrl: API }
  );
}

/** 關閉 wsOpenCollector 開的連線（觸發 server 端 disconnect，例如測 presence offline）。 */
export async function wsCloseCollector(page: Page): Promise<void> {
  await page.evaluate(() => {
    const ws = (window as any).__ws as WebSocket | undefined;
    if (ws) ws.close();
  });
}

/** 取 collector 目前累積、指定 type 的訊息（不等待；用於負向斷言「沒有」）。 */
export async function wsCollected(page: Page, type: string): Promise<any[]> {
  return page.evaluate(
    (t) => ((window as any).__wsMessages || []).filter((m: any) => m.type === t),
    type
  );
}

/**
 * 等待 collector 收到指定 type 的廣播，回傳所有符合的訊息。
 * 逾時即拋錯（代表該廣播沒送到 → 測試失敗）。
 */
export async function wsWaitForCollected(
  page: Page,
  type: string,
  timeoutMs = 8000
): Promise<any[]> {
  await page.waitForFunction(
    (t) => ((window as any).__wsMessages || []).some((m: any) => m.type === t),
    type,
    { timeout: timeoutMs }
  );
  return page.evaluate(
    (t) => ((window as any).__wsMessages || []).filter((m: any) => m.type === t),
    type
  );
}

/**
 * 只送一則 WS 訊息、不等待任何回應（送完短暫保留連線讓 server 完成轉送後關閉）。
 * 用於「對端才會收到、寄件人自己 socket 沒有回應」的情境，如通話訊號 call_offer 轉送。
 */
export async function wsSendRaw(
  page: Page,
  token: string,
  payload: object,
  settleMs = 400
): Promise<void> {
  await page.evaluate(
    ({ token, payload, settleMs, apiUrl }) =>
      new Promise<void>((resolve, reject) => {
        const wsUrl = `${apiUrl.replace("http", "ws")}/ws?token=${token}`;
        const ws = new WebSocket(wsUrl);
        ws.onopen = () => {
          ws.send(JSON.stringify(payload));
          setTimeout(() => {
            ws.close();
            resolve();
          }, settleMs);
        };
        ws.onerror = () => reject(new Error("wsSendRaw: WebSocket error"));
      }),
    { token, payload, settleMs, apiUrl: API }
  );
}

// ── UI 輔助函式 ────────────────────────────────────────────────────────────────

/**
 * 透過 shell UI 完成登入流程。
 * shell 在 / 時若無 token → 重導到 /login，auth remote 掛在 /login。
 */
export async function uiLogin(page: Page, email: string, password = "TestPass123!") {
  await page.goto("/");
  // 等待 auth remote 載入（Module Federation 非同步）
  await page.waitForURL("**/login", { timeout: 15_000 });
  await page.waitForSelector("input[type=email]", { timeout: 15_000 });
  await page.fill("input[type=email]", email);
  await page.fill("input[type=password]", password);
  await page.click("button[type=submit]");
  // 登入成功後 shell 回到 /
  await page.waitForURL("/", { timeout: 15_000 });
}
