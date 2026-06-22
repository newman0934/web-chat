/**
 * E2E spec: 訊息編輯 / 刪除 / 還原 / 表情回應 後端 API 驗收（純 WebSocket，無 UI）
 *
 * 協定（client→server）：
 *   {type:"edit",    message_id, content}
 *   {type:"delete",  message_id}
 *   {type:"restore", message_id}
 *   {type:"react",   message_id, emoji}
 * server 一律以廣播 {type:"message_updated", message} 回應對話所有在線成員（含操作者本人，
 * 故操作者自己的 socket 也收得到 → 可直接用 wsRequest 等該事件）；失敗回 {type:"error", reason}。
 *
 * 場景（MA = Message Actions）：
 *   MA-01 編輯本人訊息 → message_updated，content 更新、edited_at 非 null
 *   MA-02 編輯非本人訊息被拒（forbidden）
 *   MA-03 編輯空內容被拒（invalid_payload）
 *   MA-04 刪除本人訊息（軟刪）→ deleted=true、content=""
 *   MA-05 刪除非本人訊息被拒（forbidden）
 *   MA-06 還原剛刪除的訊息 → deleted=false、content 回來
 *   MA-07 還原未刪除訊息被拒（forbidden）
 *   MA-08 表情 toggle 加 → reactions 含 {emoji,count:1,user_ids:[me]}
 *   MA-09 表情 toggle 再點移除 → reactions 不再含該 emoji
 *   MA-10 非對話成員按表情被拒（forbidden）
 *   MA-11 編輯廣播 → 對話另一成員（線上）實收 message_updated
 *
 * 不在此自動化：15 分鐘編輯時限 / 5 分鐘還原時限（需操弄時間，由 backend pytest
 * 以可調時窗覆蓋；E2E 不寫以免 flaky）。
 *
 * 規則 backend pytest（test_ws.py / test_message_actions*.py）已完整覆蓋；此處補 E2E 追溯。
 */

import { test, expect, Page } from "@playwright/test";
import { apiRegister, apiAddContact, wsSendMessage, wsRequest, wsOpenCollector, wsWaitForCollected } from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";

const U = {
  alice: { email: `ma-alice-${TS}@example.com`, name: "MA-Alice" },
  bob:   { email: `ma-bob-${TS}@example.com`,   name: "MA-Bob"   },
  carol: { email: `ma-carol-${TS}@example.com`, name: "MA-Carol" }, // 非 Alice↔Bob 成員
};

let tokens: Record<"alice" | "bob" | "carol", string> = {} as any;
let ids: Record<"alice" | "bob" | "carol", string> = {} as any;
let convAB: string;
let sharedPage: Page;

test.beforeAll(async ({ request, browser }) => {
  tokens.alice = await apiRegister(request, U.alice.email, U.alice.name, PW);
  tokens.bob   = await apiRegister(request, U.bob.email,   U.bob.name,   PW);
  tokens.carol = await apiRegister(request, U.carol.email, U.carol.name, PW);
  for (const k of ["alice", "bob", "carol"] as const) {
    const me = await (await request.get(`${API}/users/me`, {
      headers: { Authorization: `Bearer ${tokens[k]}` },
    })).json();
    ids[k] = me.id;
  }
  convAB = (await apiAddContact(request, tokens.alice, U.bob.email)).conversation_id;

  // 共用一個 page 宿主 WebSocket evaluate（導到 backend origin 讓 WS 可連）。
  const ctx = await browser.newContext();
  sharedPage = await ctx.newPage();
  await sharedPage.goto(`${API}/health`);
});

/** Alice 在 Alice↔Bob 送一則訊息，回傳訊息物件。 */
async function aliceSends(content: string) {
  const msg = await wsSendMessage(sharedPage, tokens.alice, convAB, content);
  expect(msg?.id).toBeTruthy();
  return msg;
}

// ── MA-01: 編輯本人訊息 ───────────────────────────────────────────────────
test("MA-01 編輯本人訊息：message_updated、content 更新、edited_at 非 null", async () => {
  const msg = await aliceSends("原始內容 MA-01");
  const updated = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "edit", message_id: msg.id, content: "已編輯內容 MA-01" },
    "message_updated"
  );
  expect(updated.message.id).toBe(msg.id);
  expect(updated.message.content).toBe("已編輯內容 MA-01");
  expect(updated.message.edited_at).not.toBeNull();
});

// ── MA-02: 編輯非本人訊息被拒 ─────────────────────────────────────────────
test("MA-02 Bob 編輯 Alice 的訊息被拒：forbidden", async () => {
  const msg = await aliceSends("Alice 的訊息 MA-02");
  const err = await wsRequest(
    sharedPage,
    tokens.bob,
    { type: "edit", message_id: msg.id, content: "Bob 想亂改" },
    "error"
  );
  expect(err.reason).toBe("forbidden");
});

// ── MA-03: 編輯空內容被拒 ─────────────────────────────────────────────────
test("MA-03 編輯為空內容被拒：invalid_payload", async () => {
  const msg = await aliceSends("Alice 的訊息 MA-03");
  const err = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "edit", message_id: msg.id, content: "   " },
    "error"
  );
  expect(err.reason).toBe("invalid_payload");
});

// ── MA-04: 刪除本人訊息（軟刪）─────────────────────────────────────────────
test("MA-04 刪除本人訊息：deleted=true、content 清空", async () => {
  const msg = await aliceSends("即將被刪 MA-04");
  const updated = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "delete", message_id: msg.id },
    "message_updated"
  );
  expect(updated.message.id).toBe(msg.id);
  expect(updated.message.deleted).toBe(true);
  expect(updated.message.content).toBe("");
});

// ── MA-05: 刪除非本人訊息被拒 ─────────────────────────────────────────────
test("MA-05 Bob 刪除 Alice 的訊息被拒：forbidden", async () => {
  const msg = await aliceSends("Alice 的訊息 MA-05");
  const err = await wsRequest(
    sharedPage,
    tokens.bob,
    { type: "delete", message_id: msg.id },
    "error"
  );
  expect(err.reason).toBe("forbidden");
});

// ── MA-06: 還原剛刪除的訊息 ───────────────────────────────────────────────
test("MA-06 還原剛刪除的訊息：deleted=false、content 回來", async () => {
  const msg = await aliceSends("刪了再還原 MA-06");
  await wsRequest(sharedPage, tokens.alice, { type: "delete", message_id: msg.id }, "message_updated");
  const restored = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "restore", message_id: msg.id },
    "message_updated"
  );
  expect(restored.message.deleted).toBe(false);
  expect(restored.message.content).toBe("刪了再還原 MA-06");
});

// ── MA-07: 還原未刪除訊息被拒 ─────────────────────────────────────────────
test("MA-07 還原未刪除的訊息被拒：forbidden", async () => {
  const msg = await aliceSends("沒刪過 MA-07");
  const err = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "restore", message_id: msg.id },
    "error"
  );
  expect(err.reason).toBe("forbidden");
});

// ── MA-08: 表情 toggle 加 ─────────────────────────────────────────────────
test("MA-08 按表情：reactions 含 {emoji:👍, count:1, user_ids:[me]}", async () => {
  const msg = await aliceSends("給我表情 MA-08");
  const updated = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "react", message_id: msg.id, emoji: "👍" },
    "message_updated"
  );
  const thumbs = updated.message.reactions.find((r: any) => r.emoji === "👍");
  expect(thumbs).toBeTruthy();
  expect(thumbs.count).toBe(1);
  expect(thumbs.user_ids).toContain(ids.alice);
});

// ── MA-09: 表情 toggle 再點移除 ───────────────────────────────────────────
test("MA-09 同表情再按一次移除：reactions 不再含該 emoji", async () => {
  const msg = await aliceSends("加了又收回 MA-09");
  await wsRequest(sharedPage, tokens.alice, { type: "react", message_id: msg.id, emoji: "👍" }, "message_updated");
  const updated = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "react", message_id: msg.id, emoji: "👍" },
    "message_updated"
  );
  expect(updated.message.reactions.find((r: any) => r.emoji === "👍")).toBeFalsy();
});

// ── MA-10: 非對話成員按表情被拒 ───────────────────────────────────────────
test("MA-10 Carol（非成員）對 Alice↔Bob 訊息按表情被拒：forbidden", async () => {
  const msg = await aliceSends("Carol 不該能按 MA-10");
  const err = await wsRequest(
    sharedPage,
    tokens.carol,
    { type: "react", message_id: msg.id, emoji: "👍" },
    "error"
  );
  expect(err.reason).toBe("forbidden");
});

// ── MA-11: 編輯廣播給對話另一成員 ─────────────────────────────────────────
test("MA-11 Alice 編輯 → 線上的 Bob 實收 message_updated", async ({ browser }) => {
  const msg = await aliceSends("廣播測試 MA-11");

  // Bob 在獨立 page 開持續監聽
  const bobCtx = await browser.newContext();
  const bobPage = await bobCtx.newPage();
  await bobPage.goto(`${API}/health`);
  await wsOpenCollector(bobPage, tokens.bob);

  // Alice 編輯
  await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "edit", message_id: msg.id, content: "Bob 應該收到這版 MA-11" },
    "message_updated"
  );

  const got = await wsWaitForCollected(bobPage, "message_updated");
  expect(
    got.some((m) => m.message?.id === msg.id && m.message?.content === "Bob 應該收到這版 MA-11")
  ).toBeTruthy();

  await bobCtx.close();
});
