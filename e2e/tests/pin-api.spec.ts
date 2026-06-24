/**
 * E2E spec: 訊息置頂 後端 API 驗收(WS + REST,無 UI)
 *
 * 對應 BDD MP-01..10。訊息以 WS 種入;釘選/取消走 WS;清單走 REST GET /pins。
 * 多數斷言採「子集」(包含/不包含特定 id),對既有資料累積具韌性;
 * 計數敏感的上限測試(MP-04)用專屬對話 convAC 避免互相干擾。
 */
import { test, expect, Page } from "@playwright/test";
import {
  apiRegister, apiAddContact, apiMe, apiCreateGroup,
  wsSendMessage, wsRequest, wsOpenCollector, wsWaitForCollected,
} from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";

const U = {
  alice: { email: `pin-a-${TS}@example.com`, name: `Pin-Alice-${TS}` },
  bob: { email: `pin-b-${TS}@example.com`, name: `Pin-Bob-${TS}` },
  carol: { email: `pin-c-${TS}@example.com`, name: `Pin-Carol-${TS}` },
};

let tokens: Record<"alice" | "bob" | "carol", string> = {} as any;
let ids: Record<"alice" | "bob" | "carol", string> = {} as any;
let convAB: string;   // Alice ↔ Bob
let convAC: string;   // Alice ↔ Carol(上限測試專用)
let groupId: string;  // Alice(admin)+ Bob + Carol
let page: Page;

test.beforeAll(async ({ request, browser }) => {
  tokens.alice = await apiRegister(request, U.alice.email, U.alice.name, PW);
  tokens.bob = await apiRegister(request, U.bob.email, U.bob.name, PW);
  tokens.carol = await apiRegister(request, U.carol.email, U.carol.name, PW);
  for (const k of ["alice", "bob", "carol"] as const) ids[k] = (await apiMe(request, tokens[k])).id;
  convAB = (await apiAddContact(request, tokens.alice, U.bob.email)).conversation_id;
  convAC = (await apiAddContact(request, tokens.alice, U.carol.email)).conversation_id;
  const g = await apiCreateGroup(request, tokens.alice, `PinG-${TS}`, [ids.bob, ids.carol]);
  groupId = g.id;

  const ctx = await browser.newContext();
  page = await ctx.newPage();
  await page.goto(`${API}/health`);
});

async function getPins(request: any, token: string, convId: string): Promise<any[]> {
  return (await request.get(`${API}/conversations/${convId}/pins`, {
    headers: { Authorization: `Bearer ${token}` },
  })).json();
}

// ── MP-01:釘選並廣播 ─────────────────────────────────────────────────────
test("MP-01 釘選訊息並廣播給成員", async ({ request, browser }) => {
  const msg = await wsSendMessage(page, tokens.bob, convAB, `公告${TS}-01`);
  // Bob 開 collector,Alice 釘選 → Bob(另一成員)收到 message_pinned
  const bobCtx = await browser.newContext();
  const bobPage = await bobCtx.newPage();
  await bobPage.goto(`${API}/health`);
  await wsOpenCollector(bobPage, tokens.bob);

  const pinned = await wsRequest(page, tokens.alice, { type: "pin", message_id: msg.id }, "message_pinned");
  expect(pinned.message.id).toBe(msg.id);
  expect(pinned.message.pinned).toBe(true);

  const got = await wsWaitForCollected(bobPage, "message_pinned");
  expect(got.some((e: any) => e.message.id === msg.id)).toBeTruthy();
  await bobCtx.close();

  const pins = await getPins(request, tokens.alice, convAB);
  expect(pins.some((p: any) => p.id === msg.id)).toBeTruthy();
});

// ── MP-02:取消釘選並廣播 ─────────────────────────────────────────────────
test("MP-02 取消釘選並廣播", async ({ request }) => {
  const msg = await wsSendMessage(page, tokens.bob, convAB, `公告${TS}-02`);
  await wsRequest(page, tokens.alice, { type: "pin", message_id: msg.id }, "message_pinned");
  const unpinned = await wsRequest(page, tokens.alice, { type: "unpin", message_id: msg.id }, "message_unpinned");
  expect(unpinned.message_id).toBe(msg.id);
  const pins = await getPins(request, tokens.alice, convAB);
  expect(pins.some((p: any) => p.id === msg.id)).toBeFalsy();
});

// ── MP-07:取得釘選清單(新釘在前) ────────────────────────────────────────
test("MP-07 群組釘選清單,新釘在前", async ({ request }) => {
  const m1 = await wsSendMessage(page, tokens.bob, groupId, `群公告${TS}-A`);
  const m2 = await wsSendMessage(page, tokens.bob, groupId, `群公告${TS}-B`);
  await wsRequest(page, tokens.alice, { type: "pin", message_id: m1.id }, "message_pinned");
  await wsRequest(page, tokens.alice, { type: "pin", message_id: m2.id }, "message_pinned");
  const pins = await getPins(request, tokens.alice, groupId);
  const idsInPins = pins.map((p: any) => p.id);
  // m2 後釘 → 應排在 m1 之前
  expect(idsInPins.indexOf(m2.id)).toBeLessThan(idsInPins.indexOf(m1.id));
});

// ── MP-03:群組非管理員釘選被拒 ──────────────────────────────────────────
test("MP-03 群組非 admin 釘選被拒(forbidden)", async ({ request }) => {
  const msg = await wsSendMessage(page, tokens.carol, groupId, `非admin${TS}`);
  const err = await wsRequest(page, tokens.bob, { type: "pin", message_id: msg.id }, "error");
  expect(err.reason).toBe("forbidden");
  const pins = await getPins(request, tokens.alice, groupId);
  expect(pins.some((p: any) => p.id === msg.id)).toBeFalsy();
});

// ── MP-05:非成員釘選被拒 ────────────────────────────────────────────────
test("MP-05 非成員釘選被拒", async () => {
  const msg = await wsSendMessage(page, tokens.bob, convAB, `機密${TS}`);
  const err = await wsRequest(page, tokens.carol, { type: "pin", message_id: msg.id }, "error");
  expect(err.reason).toBe("not_found");
});

// ── MP-04:超過上限被拒 ──────────────────────────────────────────────────
test("MP-04 釘滿 10 則後第 11 則被拒(pin_limit)", async ({ request }) => {
  for (let i = 0; i < 10; i++) {
    const m = await wsSendMessage(page, tokens.alice, convAC, `lim${TS}-${i}`);
    await wsRequest(page, tokens.alice, { type: "pin", message_id: m.id }, "message_pinned");
  }
  const extra = await wsSendMessage(page, tokens.alice, convAC, `lim${TS}-x`);
  const err = await wsRequest(page, tokens.alice, { type: "pin", message_id: extra.id }, "error");
  expect(err.reason).toBe("pin_limit");
  expect((await getPins(request, tokens.alice, convAC)).length).toBe(10);
});

// ── MP-04b:取消後可再釘 ─────────────────────────────────────────────────
test("MP-04b 取消一則後可再釘新則", async ({ request }) => {
  const pins = await getPins(request, tokens.alice, convAC); // 來自 MP-04,已 10 則
  expect(pins.length).toBe(10);
  await wsRequest(page, tokens.alice, { type: "unpin", message_id: pins[0].id }, "message_unpinned");
  const fresh = await wsSendMessage(page, tokens.alice, convAC, `lim${TS}-new`);
  await wsRequest(page, tokens.alice, { type: "pin", message_id: fresh.id }, "message_pinned");
  expect((await getPins(request, tokens.alice, convAC)).length).toBe(10);
});

// ── MP-06:刪除已釘訊息自動取消釘選 ─────────────────────────────────────
test("MP-06 刪除已釘訊息自動取消釘選", async ({ request }) => {
  const msg = await wsSendMessage(page, tokens.bob, convAB, `待刪${TS}`);
  await wsRequest(page, tokens.alice, { type: "pin", message_id: msg.id }, "message_pinned");
  // Bob(sender)刪除 → 收到 message_unpinned(也會有 message_updated)
  const evt = await wsRequest(page, tokens.bob, { type: "delete", message_id: msg.id }, "message_unpinned");
  expect(evt.message_id).toBe(msg.id);
  const pins = await getPins(request, tokens.alice, convAB);
  expect(pins.some((p: any) => p.id === msg.id)).toBeFalsy();
});

// ── MP-09:重複釘選為冪等 ────────────────────────────────────────────────
test("MP-09 重複釘選冪等,不重複計數", async ({ request }) => {
  const msg = await wsSendMessage(page, tokens.bob, convAB, `冪等${TS}`);
  await wsRequest(page, tokens.alice, { type: "pin", message_id: msg.id }, "message_pinned");
  await wsRequest(page, tokens.alice, { type: "pin", message_id: msg.id }, "message_pinned");
  const pins = await getPins(request, tokens.alice, convAB);
  expect(pins.filter((p: any) => p.id === msg.id).length).toBe(1);
});

// ── MP-10:釘選不存在的訊息被拒 ──────────────────────────────────────────
test("MP-10 釘不存在的訊息被拒(not_found)", async () => {
  const err = await wsRequest(
    page, tokens.alice,
    { type: "pin", message_id: "00000000-0000-0000-0000-000000000000" },
    "error",
  );
  expect(err.reason).toBe("not_found");
});
