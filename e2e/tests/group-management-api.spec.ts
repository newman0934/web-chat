/**
 * E2E spec: 群組管理後端 API 驗收（驅動 REST + WebSocket，無需完整 UI）
 *
 * 取代原本「兩三個瀏覽器手動點」的驗證：把加入/移除/退出/改名/角色 + 守門規則
 * 全部寫成 REST 斷言，並用一條持續監聽的 WS 連線驗證即時廣播
 * （系統訊息 message / conversation_updated / conversation_removed）。
 *
 * 場景（GM = Group Management）：
 *   GM-01 admin 加好友入群 → 成員列更新 + 線上成員收到系統訊息與 conversation_updated
 *   GM-02 admin 用 email 加「非好友」入群（放寬 friends-only）
 *   GM-03 admin 移除成員 → 被移除者收到 conversation_removed
 *   GM-04 admin 改名 → 成員收到 conversation_updated + 系統訊息
 *   GM-05 admin 升級成員為 admin → 該員取得管理權限（可改名）
 *   GM-06 成員退出群組 → 自己收到 conversation_removed、其餘成員少一人
 *   GM-07 非 admin 執行管理操作被拒（403）
 *   GM-08 最後一位 admin 不能退出（400）
 *   GM-09 移除非成員被拒（404）
 *   GM-10 加入已是成員者被拒（400）
 *
 * 測試策略：每個會變更成員/角色的場景各自 apiCreateGroup 一個新群，彼此獨立、
 * 不依賴執行順序。所有互動走 REST + 瀏覽器內原生 WebSocket（見 helpers）。
 * 這些規則在 backend pytest（test_group_*.py）也有覆蓋；此處補 BDD→Playwright 追溯。
 */

import { test, expect, Page, Browser } from "@playwright/test";
import {
  apiRegister,
  apiAddContact,
  apiMe,
  apiCreateGroup,
  wsOpenCollector,
  wsWaitForCollected,
} from "./helpers";
import { APIRequestContext } from "@playwright/test";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";

// owner = 群主/admin；m1, m2 = 一般成員；friend3 = owner 的好友（用來加入）；outsider = 非好友
const U = {
  owner:   { email: `gm-owner-${TS}@example.com`,   name: "GM-Owner"   },
  m1:      { email: `gm-m1-${TS}@example.com`,      name: "GM-M1"      },
  m2:      { email: `gm-m2-${TS}@example.com`,      name: "GM-M2"      },
  friend3: { email: `gm-friend3-${TS}@example.com`, name: "GM-Friend3" },
  outsider:{ email: `gm-outsider-${TS}@example.com`,name: "GM-Outsider"},
};

let tokens: Record<keyof typeof U, string> = {} as any;
let ids: Record<keyof typeof U, string> = {} as any;

/** 用 owner 身分建一個含 m1、m2 的群，回傳 conversation id。 */
async function newGroup(request: APIRequestContext, name: string): Promise<string> {
  const conv = await apiCreateGroup(request, tokens.owner, name, [ids.m1, ids.m2]);
  return conv.id as string;
}

/** 開一個獨立 context 的 page 並掛上 WS collector（導到 backend origin 讓 WS 可連）。 */
async function listener(browser: Browser, token: string): Promise<Page> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(`${API}/health`);
  await wsOpenCollector(page, token);
  return page;
}

test.beforeAll(async ({ request }) => {
  for (const k of Object.keys(U) as (keyof typeof U)[]) {
    tokens[k] = await apiRegister(request, U[k].email, U[k].name, PW);
    ids[k] = (await apiMe(request, tokens[k])).id;
  }
  // owner 與 m1 / m2 / friend3 成為好友（建群與加好友入群的前提）。outsider 刻意不加。
  await apiAddContact(request, tokens.owner, U.m1.email);
  await apiAddContact(request, tokens.owner, U.m2.email);
  await apiAddContact(request, tokens.owner, U.friend3.email);
});

// ── GM-01: admin 加好友入群 → 成員列更新 + 廣播 ──────────────────────────
test("GM-01 admin 加好友入群：成員列含新成員、線上成員收到系統訊息與 conversation_updated", async ({
  request,
  browser,
}) => {
  const convId = await newGroup(request, `GM01 群 ${TS}`);
  const m1Page = await listener(browser, tokens.m1); // m1 在線監聽

  const res = await request.post(`${API}/conversations/${convId}/members`, {
    headers: { Authorization: `Bearer ${tokens.owner}` },
    data: { user_id: ids.friend3 },
  });
  expect(res.status()).toBe(200);
  const conv = await res.json();
  const memberIds = conv.members.map((u: any) => u.id);
  expect(memberIds).toContain(ids.friend3);
  expect(conv.roles[ids.friend3]).toBe("member");

  // m1 應收到一則系統訊息與 conversation_updated
  const updated = await wsWaitForCollected(m1Page, "conversation_updated");
  expect(updated.some((m) => m.conversation_id === convId)).toBeTruthy();
  const sysMsgs = await wsWaitForCollected(m1Page, "message");
  expect(
    sysMsgs.some((m) => m.message?.kind === "system" && m.message?.content?.includes("加入群組"))
  ).toBeTruthy();

  await m1Page.context().close();
});

// ── GM-02: 用 email 加「非好友」入群（放寬 friends-only）──────────────────
test("GM-02 admin 用 email 加非好友入群：成員列含 outsider", async ({ request }) => {
  const convId = await newGroup(request, `GM02 群 ${TS}`);

  const res = await request.post(`${API}/conversations/${convId}/members`, {
    headers: { Authorization: `Bearer ${tokens.owner}` },
    data: { email: U.outsider.email }, // outsider 不是 owner 的好友
  });
  expect(res.status()).toBe(200);
  const conv = await res.json();
  expect(conv.members.map((u: any) => u.id)).toContain(ids.outsider);
});

// ── GM-03: 移除成員 → 被移除者收到 conversation_removed ───────────────────
test("GM-03 admin 移除成員：成員列移除該員、被移除者收到 conversation_removed", async ({
  request,
  browser,
}) => {
  const convId = await newGroup(request, `GM03 群 ${TS}`);
  const m2Page = await listener(browser, tokens.m2); // 即將被移除者監聽

  const res = await request.delete(`${API}/conversations/${convId}/members/${ids.m2}`, {
    headers: { Authorization: `Bearer ${tokens.owner}` },
  });
  expect(res.status()).toBe(200);
  const conv = await res.json();
  expect(conv.members.map((u: any) => u.id)).not.toContain(ids.m2);

  const removed = await wsWaitForCollected(m2Page, "conversation_removed");
  expect(removed.some((m) => m.conversation_id === convId)).toBeTruthy();

  await m2Page.context().close();
});

// ── GM-04: 改名 → 成員收到 conversation_updated + 系統訊息 ─────────────────
test("GM-04 admin 改名：name 更新、成員收到 conversation_updated 與系統訊息", async ({
  request,
  browser,
}) => {
  const convId = await newGroup(request, `GM04 舊名 ${TS}`);
  const m1Page = await listener(browser, tokens.m1);

  const newName = `GM04 新名 ${TS}`;
  const res = await request.patch(`${API}/conversations/${convId}`, {
    headers: { Authorization: `Bearer ${tokens.owner}` },
    data: { name: newName },
  });
  expect(res.status()).toBe(200);
  expect((await res.json()).name).toBe(newName);

  const updated = await wsWaitForCollected(m1Page, "conversation_updated");
  expect(updated.some((m) => m.conversation_id === convId)).toBeTruthy();
  const sysMsgs = await wsWaitForCollected(m1Page, "message");
  expect(sysMsgs.some((m) => m.message?.kind === "system" && m.message?.content?.includes("改名"))).toBeTruthy();

  await m1Page.context().close();
});

// ── GM-05: 升級成員為 admin → 取得管理權限 ───────────────────────────────
test("GM-05 admin 升級 m1 為 admin：roles 反映、m1 取得改名權限", async ({ request }) => {
  const convId = await newGroup(request, `GM05 群 ${TS}`);

  const promote = await request.patch(
    `${API}/conversations/${convId}/members/${ids.m1}/role`,
    {
      headers: { Authorization: `Bearer ${tokens.owner}` },
      data: { role: "admin" },
    }
  );
  expect(promote.status()).toBe(200);
  expect((await promote.json()).roles[ids.m1]).toBe("admin");

  // m1 升級後應能改名（原本非 admin 會 403）
  const rename = await request.patch(`${API}/conversations/${convId}`, {
    headers: { Authorization: `Bearer ${tokens.m1}` },
    data: { name: `GM05 由m1改名 ${TS}` },
  });
  expect(rename.status()).toBe(200);
});

// ── GM-06: 成員退出群組 ─────────────────────────────────────────────────
test("GM-06 成員退出群組：回 ok、自己收到 conversation_removed、群組少一人", async ({
  request,
  browser,
}) => {
  const convId = await newGroup(request, `GM06 群 ${TS}`);
  const m2Page = await listener(browser, tokens.m2);

  const res = await request.post(`${API}/conversations/${convId}/leave`, {
    headers: { Authorization: `Bearer ${tokens.m2}` },
  });
  expect(res.status()).toBe(200);
  expect((await res.json()).ok).toBe(true);

  const removed = await wsWaitForCollected(m2Page, "conversation_removed");
  expect(removed.some((m) => m.conversation_id === convId)).toBeTruthy();

  // owner 視角：成員列不再含 m2
  const list = await request.get(`${API}/conversations`, {
    headers: { Authorization: `Bearer ${tokens.owner}` },
  });
  const group = (await list.json()).find((c: any) => c.id === convId);
  expect(group.members.map((u: any) => u.id)).not.toContain(ids.m2);

  await m2Page.context().close();
});

// ── GM-07: 非 admin 執行管理操作被拒 ─────────────────────────────────────
test("GM-07 非 admin 成員改名被拒：403", async ({ request }) => {
  const convId = await newGroup(request, `GM07 群 ${TS}`);

  const res = await request.patch(`${API}/conversations/${convId}`, {
    headers: { Authorization: `Bearer ${tokens.m1}` }, // m1 為一般成員
    data: { name: "非法改名" },
  });
  expect(res.status()).toBe(403);
});

// ── GM-08: 最後一位 admin 不能退出 ───────────────────────────────────────
test("GM-08 唯一 admin（群主）退出被拒：400", async ({ request }) => {
  const convId = await newGroup(request, `GM08 群 ${TS}`); // owner 是唯一 admin

  const res = await request.post(`${API}/conversations/${convId}/leave`, {
    headers: { Authorization: `Bearer ${tokens.owner}` },
  });
  expect(res.status()).toBe(400);
});

// ── GM-09: 移除非成員被拒 ────────────────────────────────────────────────
test("GM-09 移除非群組成員被拒：404", async ({ request }) => {
  const convId = await newGroup(request, `GM09 群 ${TS}`); // outsider 不在群內

  const res = await request.delete(
    `${API}/conversations/${convId}/members/${ids.outsider}`,
    { headers: { Authorization: `Bearer ${tokens.owner}` } }
  );
  expect(res.status()).toBe(404);
});

// ── GM-10: 加入已是成員者被拒 ────────────────────────────────────────────
test("GM-10 加入已是群組成員者被拒：400", async ({ request }) => {
  const convId = await newGroup(request, `GM10 群 ${TS}`); // m1 已在群內

  const res = await request.post(`${API}/conversations/${convId}/members`, {
    headers: { Authorization: `Bearer ${tokens.owner}` },
    data: { user_id: ids.m1 },
  });
  expect(res.status()).toBe(400);
});
