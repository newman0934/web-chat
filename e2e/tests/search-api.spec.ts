/**
 * E2E spec: 訊息搜尋 後端 API 驗收(REST + WS 種訊息,無 UI)
 *
 * 對應 BDD(docs/superpowers/specs/message-search/bdd.feature)MS-01..06、08、09、10、11。
 * 訊息以 WebSocket 種入(無 REST 送訊息端點);搜尋走 GET /search/messages。
 * 關鍵字一律帶 per-run 唯一字串(TS),避免與其他測試/既有資料互相干擾。
 */
import { test, expect, Page } from "@playwright/test";
import { apiRegister, apiAddContact, apiMe, wsSendMessage, wsRequest } from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";

const U = {
  alice: { email: `se-alice-${TS}@example.com`, name: `SE-Alice-${TS}` },
  bob: { email: `se-bob-${TS}@example.com`, name: `SE-Bob-${TS}` },
  carol: { email: `se-carol-${TS}@example.com`, name: `SE-Carol-${TS}` },
};

let tokens: Record<"alice" | "bob" | "carol", string> = {} as any;
let ids: Record<"alice" | "bob" | "carol", string> = {} as any;
let convAB: string; // Alice ↔ Bob(Alice 是成員)
let convBC: string; // Bob ↔ Carol(Alice 非成員)
let convAC: string; // Alice ↔ Carol(供 around/互斥 測試)
let page: Page;

test.beforeAll(async ({ request, browser }) => {
  tokens.alice = await apiRegister(request, U.alice.email, U.alice.name, PW);
  tokens.bob = await apiRegister(request, U.bob.email, U.bob.name, PW);
  tokens.carol = await apiRegister(request, U.carol.email, U.carol.name, PW);
  for (const k of ["alice", "bob", "carol"] as const) {
    ids[k] = (await apiMe(request, tokens[k])).id;
  }
  convAB = (await apiAddContact(request, tokens.alice, U.bob.email)).conversation_id;
  convBC = (await apiAddContact(request, tokens.bob, U.carol.email)).conversation_id;
  convAC = (await apiAddContact(request, tokens.alice, U.carol.email)).conversation_id;

  const ctx = await browser.newContext();
  page = await ctx.newPage();
  await page.goto(`${API}/health`);
});

/** 以 token 呼叫搜尋端點。 */
function doSearch(
  request: any,
  token: string | null,
  q: string,
  extra: Record<string, string | number> = {},
) {
  const params = new URLSearchParams({ q });
  for (const [k, v] of Object.entries(extra)) params.set(k, String(v));
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  return request.get(`${API}/search/messages?${params.toString()}`, { headers });
}

// ── MS-01:內容命中 ───────────────────────────────────────────────────────
test("MS-01 以內容關鍵字命中,附對話與寄件者資訊", async ({ request }) => {
  const kw = `會議${TS}A`;
  await wsSendMessage(page, tokens.bob, convAB, `明天的${kw}改到三點`);
  const resp = await doSearch(request, tokens.alice, kw);
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.items.length).toBe(1);
  const item = body.items[0];
  expect(item.message.content).toContain(kw);
  expect(item.conversation.type).toBe("direct");
  expect(item.conversation.other_user.id).toBe(ids.bob);
  expect(item.sender_name).toBe(U.bob.name);
});

// ── MS-02:寄件者名命中 ───────────────────────────────────────────────────
test("MS-02 以寄件者名稱命中", async ({ request }) => {
  const marker = `收到${TS}B`; // 內容不含寄件者名
  await wsSendMessage(page, tokens.bob, convAB, marker);
  const resp = await doSearch(request, tokens.alice, U.bob.name);
  const body = await resp.json();
  expect(body.items.some((r: any) => r.message.content === marker)).toBeTruthy();
});

// ── MS-03:排除已刪除 ─────────────────────────────────────────────────────
test("MS-03 排除已刪除訊息", async ({ request }) => {
  const kw = `稍後刪${TS}`;
  const msg = await wsSendMessage(page, tokens.bob, convAB, kw);
  await wsRequest(page, tokens.bob, { type: "delete", message_id: msg.id }, "message_updated");
  const resp = await doSearch(request, tokens.alice, kw);
  const body = await resp.json();
  expect(body.items.length).toBe(0);
});

// ── MS-04:不外洩他人對話 ─────────────────────────────────────────────────
test("MS-04 非成員對話不外洩", async ({ request }) => {
  const kw = `機密${TS}`;
  await wsSendMessage(page, tokens.bob, convBC, `${kw} Alice看不到`);
  const resp = await doSearch(request, tokens.alice, kw); // Alice 非 convBC 成員
  const body = await resp.json();
  expect(body.items.length).toBe(0);
});

// ── MS-06:未授權 ─────────────────────────────────────────────────────────
test("MS-06 未授權搜尋 → 401", async ({ request }) => {
  const resp = await doSearch(request, null, "anything");
  expect(resp.status()).toBe(401);
});

// ── MS-05:驗證失敗 ───────────────────────────────────────────────────────
test("MS-05a 空白關鍵字 → 422", async ({ request }) => {
  expect((await doSearch(request, tokens.alice, "")).status()).toBe(422);
  expect((await doSearch(request, tokens.alice, "   ")).status()).toBe(422);
});

test("MS-05b 過長關鍵字 → 422", async ({ request }) => {
  expect((await doSearch(request, tokens.alice, "a".repeat(101))).status()).toBe(422);
});

// ── MS-09:萬用字元逸出 ───────────────────────────────────────────────────
test("MS-09 萬用字元逸出(50% 字面)", async ({ request }) => {
  await wsSendMessage(page, tokens.bob, convAB, `促銷50%${TS}結束`); // 含字面 "50%TS"
  await wsSendMessage(page, tokens.bob, convAB, `序號50ABCDE${TS}`); // 若 % 當萬用會誤命中
  const resp = await doSearch(request, tokens.alice, `50%${TS}`);
  const body = await resp.json();
  const contents = body.items.map((r: any) => r.message.content);
  expect(contents.some((c: string) => c.includes(`促銷50%${TS}`))).toBeTruthy();
  expect(contents.some((c: string) => c.includes(`50ABCDE${TS}`))).toBeFalsy();
});

// ── MS-10:分頁不重不漏 ───────────────────────────────────────────────────
test("MS-10 分頁不重不漏(25 則,limit=20)", async ({ request }) => {
  const kw = `報表${TS}P`;
  for (let i = 0; i < 25; i++) {
    await wsSendMessage(page, tokens.bob, convAB, `${kw} 第${i}版`);
  }
  const page1 = await (await doSearch(request, tokens.alice, kw, { limit: 20 })).json();
  expect(page1.items.length).toBe(20);
  expect(page1.next_before).not.toBeNull();
  const page2 = await (
    await doSearch(request, tokens.alice, kw, { limit: 20, before: page1.next_before })
  ).json();
  expect(page2.items.length).toBe(5);
  expect(page2.next_before).toBeNull();
  const ids1 = new Set(page1.items.map((r: any) => r.message.id));
  const ids2 = page2.items.map((r: any) => r.message.id);
  expect(ids2.every((id: string) => !ids1.has(id))).toBeTruthy();
});

// ── MS-08:互斥分頁參數 ───────────────────────────────────────────────────
test("MS-08 before 與 around 同時帶 → 422", async ({ request }) => {
  const msg = await wsSendMessage(page, tokens.alice, convAC, `互斥${TS}`);
  const resp = await request.get(
    `${API}/conversations/${convAC}/messages?before=${new Date().toISOString()}&around=${msg.id}`,
    { headers: { Authorization: `Bearer ${tokens.alice}` } },
  );
  expect(resp.status()).toBe(422);
});

// ── MS-11:around 視窗邊界(末則只有較舊側) ───────────────────────────────
test("MS-11 around 視窗載入邊界不報錯", async ({ request }) => {
  let last: any;
  for (let i = 0; i < 4; i++) {
    last = await wsSendMessage(page, tokens.alice, convAC, `視窗${TS} m${i}`);
  }
  const resp = await request.get(
    `${API}/conversations/${convAC}/messages?around=${last.id}&limit=6`,
    { headers: { Authorization: `Bearer ${tokens.alice}` } },
  );
  expect(resp.status()).toBe(200);
  const msgs = await resp.json();
  expect(msgs.some((m: any) => m.id === last.id)).toBeTruthy(); // 末則(無較新側)仍含自己
});
