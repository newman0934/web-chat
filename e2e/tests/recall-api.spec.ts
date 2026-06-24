/**
 * E2E spec: 訊息撤回 後端 API 驗收(WS + REST,無 UI)
 *
 * 對應 BDD MR-01、02、04、05、06、07、08。逾時(MR-03)由 backend pytest 覆蓋。
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
  alice: { email: `rc-a-${TS}@example.com`, name: `RC-Alice-${TS}` },
  bob: { email: `rc-b-${TS}@example.com`, name: `RC-Bob-${TS}` },
  carol: { email: `rc-c-${TS}@example.com`, name: `RC-Carol-${TS}` },
};

let tokens: Record<"alice" | "bob" | "carol", string> = {} as any;
let ids: Record<"alice" | "bob" | "carol", string> = {} as any;
let convAB: string;
let groupId: string;
let page: Page;

test.beforeAll(async ({ request, browser }) => {
  tokens.alice = await apiRegister(request, U.alice.email, U.alice.name, PW);
  tokens.bob = await apiRegister(request, U.bob.email, U.bob.name, PW);
  tokens.carol = await apiRegister(request, U.carol.email, U.carol.name, PW);
  for (const k of ["alice", "bob", "carol"] as const) ids[k] = (await apiMe(request, tokens[k])).id;
  convAB = (await apiAddContact(request, tokens.alice, U.bob.email)).conversation_id;
  await apiAddContact(request, tokens.alice, U.carol.email);
  groupId = (await apiCreateGroup(request, tokens.alice, `RCG-${TS}`, [ids.bob, ids.carol])).id;

  const ctx = await browser.newContext();
  page = await ctx.newPage();
  await page.goto(`${API}/health`);
});

// ── MR-01:撤回成功並廣播 ─────────────────────────────────────────────────
test("MR-01 寄件人撤回成功並廣播", async ({ browser }) => {
  const msg = await wsSendMessage(page, tokens.alice, convAB, `誤傳${TS}-01`);
  const bobCtx = await browser.newContext();
  const bobPage = await bobCtx.newPage();
  await bobPage.goto(`${API}/health`);
  await wsOpenCollector(bobPage, tokens.bob);

  const evt = await wsRequest(page, tokens.alice, { type: "recall", message_id: msg.id }, "message_updated");
  expect(evt.message.recalled).toBe(true);
  expect(evt.message.content).toBe("");

  const got = await wsWaitForCollected(bobPage, "message_updated");
  expect(got.some((e: any) => e.message.id === msg.id && e.message.recalled === true)).toBeTruthy();
  await bobCtx.close();
});

// ── MR-02:非寄件人撤回被拒 ──────────────────────────────────────────────
test("MR-02 非寄件人撤回被拒(forbidden)", async () => {
  const msg = await wsSendMessage(page, tokens.alice, convAB, `abc${TS}-02`);
  const err = await wsRequest(page, tokens.bob, { type: "recall", message_id: msg.id }, "error");
  expect(err.reason).toBe("forbidden");
});

// ── MR-04:撤回後不可再 edit/react/pin ───────────────────────────────────
test("MR-04 撤回後不可再編輯/表情/釘選", async () => {
  const msg = await wsSendMessage(page, tokens.alice, convAB, `待撤${TS}-04`);
  await wsRequest(page, tokens.alice, { type: "recall", message_id: msg.id }, "message_updated");
  for (const op of [
    { type: "edit", message_id: msg.id, content: "x" },
    { type: "react", message_id: msg.id, emoji: "👍" },
    { type: "pin", message_id: msg.id },
  ]) {
    const err = await wsRequest(page, tokens.alice, op, "error");
    expect(["forbidden", "not_found"]).toContain(err.reason);
  }
});

// ── MR-05:撤回已刪除訊息被拒 ────────────────────────────────────────────
test("MR-05 撤回已刪除訊息被拒", async () => {
  const msg = await wsSendMessage(page, tokens.alice, convAB, `刪撤${TS}-05`);
  await wsRequest(page, tokens.alice, { type: "delete", message_id: msg.id }, "message_updated");
  const err = await wsRequest(page, tokens.alice, { type: "recall", message_id: msg.id }, "error");
  expect(err.reason).toBe("forbidden");
});

// ── MR-06:重複撤回被拒 ──────────────────────────────────────────────────
test("MR-06 重複撤回被拒", async () => {
  const msg = await wsSendMessage(page, tokens.alice, convAB, `重撤${TS}-06`);
  await wsRequest(page, tokens.alice, { type: "recall", message_id: msg.id }, "message_updated");
  const err = await wsRequest(page, tokens.alice, { type: "recall", message_id: msg.id }, "error");
  expect(err.reason).toBe("forbidden");
});

// ── MR-07:已撤回不出現在搜尋 ────────────────────────────────────────────
test("MR-07 已撤回訊息不出現在搜尋", async ({ request }) => {
  const kw = `撤回搜尋${TS}07`;
  const msg = await wsSendMessage(page, tokens.alice, convAB, kw);
  await wsRequest(page, tokens.alice, { type: "recall", message_id: msg.id }, "message_updated");
  const resp = await request.get(`${API}/search/messages?q=${encodeURIComponent(kw)}`, {
    headers: { Authorization: `Bearer ${tokens.alice}` },
  });
  expect((await resp.json()).items.length).toBe(0);
});

// ── MR-08:撤回已釘選自動取消釘選 ───────────────────────────────────────
test("MR-08 撤回已釘選訊息自動取消釘選", async ({ request }) => {
  const msg = await wsSendMessage(page, tokens.bob, groupId, `群撤${TS}-08`);
  await wsRequest(page, tokens.alice, { type: "pin", message_id: msg.id }, "message_pinned");
  // Bob(寄件人)撤回 → 廣播 message_unpinned
  const evt = await wsRequest(page, tokens.bob, { type: "recall", message_id: msg.id }, "message_unpinned");
  expect(evt.message_id).toBe(msg.id);
  const pins = await (await request.get(`${API}/conversations/${groupId}/pins`, {
    headers: { Authorization: `Bearer ${tokens.alice}` },
  })).json();
  expect(pins.some((p: any) => p.id === msg.id)).toBeFalsy();
});
