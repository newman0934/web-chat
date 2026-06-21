/**
 * E2E spec: 回覆/轉發後端 API 驗收（驅動 REST + WebSocket，無需完整 UI）
 *
 * BDD 追溯：
 *   RF-04 — 跨對話 reply_to_message_id 被拒（reason: "invalid_reply"）
 *   RF-05 — 缺欄位的轉發被拒（reason: "invalid_payload"）
 *   RF-06 — 轉發到非成員對話被拒（reason: "forbidden"）
 *   RF-07 — 轉發看不到的訊息被拒（reason: "forbidden"）
 *   RF-08 — 轉發已刪除訊息被拒（reason: "forbidden"）
 *
 * 測試策略：
 *   - 所有互動走 REST（register/login/contacts）+ WebSocket（send/forward）
 *   - 不需要 UI（shell/auth/chat remote），因此 webServer 若有問題這些測試仍能運行
 *   - 使用 page.evaluate 內建原生 WebSocket（wsRequest helper）
 *
 * 這些場景在 backend/tests/test_ws.py（pytest）也有完整覆蓋；
 * 此處 Playwright 版本的目的是讓 BDD→Playwright traceability 完整。
 */

import { test, expect, Page } from "@playwright/test";
import { apiRegister, apiAddContact, wsSendMessage, wsRequest } from "./helpers";

const TS = Date.now();

// ── 測試使用者（所有 RF-04..08 共用） ─────────────────────────────────────
const U = {
  alice: { email: `alice-api-${TS}@example.com`, name: "Alice-API" },
  bob:   { email: `bob-api-${TS}@example.com`,   name: "Bob-API"   },
  carol: { email: `carol-api-${TS}@example.com`, name: "Carol-API" },
};
const PW = "TestPass123!";

let tokens: Record<"alice" | "bob" | "carol", string> = {} as any;
let convAliceBob: string;
let convAliceCarol: string;
let convBobCarol: string;  // Alice は非成員
let sharedPage: Page;

test.beforeAll(async ({ request, browser }) => {
  // 建立三個帳號
  tokens.alice = await apiRegister(request, U.alice.email, U.alice.name, PW);
  tokens.bob   = await apiRegister(request, U.bob.email,   U.bob.name,   PW);
  tokens.carol = await apiRegister(request, U.carol.email, U.carol.name, PW);

  // Alice↔Bob, Alice↔Carol 好友關係
  const r1 = await apiAddContact(request, tokens.alice, U.bob.email);
  convAliceBob = r1.conversation_id;
  const r2 = await apiAddContact(request, tokens.alice, U.carol.email);
  convAliceCarol = r2.conversation_id;

  // Bob↔Carol（Alice 非成員）
  const r3 = await apiAddContact(request, tokens.bob, U.carol.email);
  convBobCarol = r3.conversation_id;

  // 共用一個 headless page 來宿主 WebSocket evaluate。
  // 必須導航到 http://localhost:8000（backend 的 origin）才能讓 WS 連線成功；
  // about:blank 的 null origin 在某些 Chromium sandbox 設定下會被拒絕。
  const ctx = await browser.newContext();
  sharedPage = await ctx.newPage();
  await sharedPage.goto("http://localhost:8000/health");
});

// ── RF-04: 跨對話 reply_to_message_id 被拒 ───────────────────────────────
test("RF-04 跨對話回覆被拒：reason=invalid_reply", async () => {
  // Alice 先在 Alice↔Carol 對話建立一則訊息 M
  const msgInCarolConv = await wsSendMessage(
    sharedPage,
    tokens.alice,
    convAliceCarol,
    "Alice 在 Carol 對話的訊息"
  );
  expect(msgInCarolConv?.id).toBeTruthy();
  const foreignMsgId = msgInCarolConv.id;

  // Alice 嘗試在 Alice↔Bob 對話用 reply_to_message_id 指向跨對話的訊息
  const errorResp = await wsRequest(
    sharedPage,
    tokens.alice,
    {
      type: "message",
      conversation_id: convAliceBob,
      content: "嘗試跨對話回覆",
      reply_to_message_id: foreignMsgId,
      temp_id: `tmp-rf04-${Date.now()}`,
    },
    "error"
  );

  expect(errorResp.type).toBe("error");
  expect(errorResp.reason).toBe("invalid_reply");
});

// ── RF-05: 缺欄位的轉發被拒 ─────────────────────────────────────────────
test("RF-05 缺 to_conversation_id 的轉發被拒：reason=invalid_payload", async () => {
  // Bob 先送一則訊息
  const bobMsg = await wsSendMessage(
    sharedPage,
    tokens.bob,
    convAliceBob,
    "Bob 的訊息（RF-05 用）"
  );
  expect(bobMsg?.id).toBeTruthy();

  // Alice 送 forward 但故意省略 to_conversation_id
  const errorResp = await wsRequest(
    sharedPage,
    tokens.alice,
    {
      type: "forward",
      message_id: bobMsg.id,
      // to_conversation_id 故意省略
    },
    "error"
  );

  expect(errorResp.type).toBe("error");
  expect(errorResp.reason).toBe("invalid_payload");
});

// ── RF-06: 轉發到非成員對話被拒 ─────────────────────────────────────────
test("RF-06 轉發到 Alice 非成員的對話被拒：reason=forbidden", async () => {
  // Bob 在 Alice↔Bob 送一則訊息
  const bobMsg = await wsSendMessage(
    sharedPage,
    tokens.bob,
    convAliceBob,
    "Bob 的訊息（RF-06 用）"
  );
  expect(bobMsg?.id).toBeTruthy();

  // Alice 嘗試把該訊息轉發到 Bob↔Carol（Alice 非成員）
  const errorResp = await wsRequest(
    sharedPage,
    tokens.alice,
    {
      type: "forward",
      message_id: bobMsg.id,
      to_conversation_id: convBobCarol,  // Alice 不在這個對話
    },
    "error"
  );

  expect(errorResp.type).toBe("error");
  expect(errorResp.reason).toBe("forbidden");
});

// ── RF-07: 轉發看不到的訊息被拒 ─────────────────────────────────────────
test("RF-07 轉發 Alice 看不到的訊息（Bob↔Carol 對話）被拒：reason=forbidden", async () => {
  // Bob 在 Bob↔Carol 對話送出訊息（Alice 無法存取）
  const bobPrivateMsg = await wsSendMessage(
    sharedPage,
    tokens.bob,
    convBobCarol,
    "Bob 在 Bob↔Carol 的私訊"
  );
  expect(bobPrivateMsg?.id).toBeTruthy();

  // Alice 嘗試把這則訊息轉發到 Alice↔Carol（Alice 是 Alice↔Carol 成員，但不是 Bob↔Carol 成員）
  const errorResp = await wsRequest(
    sharedPage,
    tokens.alice,
    {
      type: "forward",
      message_id: bobPrivateMsg.id,
      to_conversation_id: convAliceCarol,
    },
    "error"
  );

  expect(errorResp.type).toBe("error");
  expect(errorResp.reason).toBe("forbidden");
});

// ── RF-08: 轉發已刪除訊息被拒 ───────────────────────────────────────────
test("RF-08 轉發已刪除訊息被拒：reason=forbidden", async () => {
  // Step 1: Bob 送一則訊息
  const bobMsg = await wsSendMessage(
    sharedPage,
    tokens.bob,
    convAliceBob,
    "Bob 的訊息（RF-08 用，稍後刪除）"
  );
  expect(bobMsg?.id).toBeTruthy();

  // Step 2: Bob 刪除該訊息
  const deleteResp = await wsRequest(
    sharedPage,
    tokens.bob,
    { type: "delete", message_id: bobMsg.id },
    "message_updated"  // 伺服器廣播 message_updated 給對話成員
  );
  // 若 Bob 不在線（上面 WS 已關閉），delete 操作的 broadcast 收不到；
  // 換個方式：直接確認 delete 發送後再 forward，不等 broadcast
  // 不論 broadcast 是否收到，Bob 的訊息已被 soft-delete

  // Step 3: Alice 嘗試轉發已刪除的訊息
  const errorResp = await wsRequest(
    sharedPage,
    tokens.alice,
    {
      type: "forward",
      message_id: bobMsg.id,
      to_conversation_id: convAliceCarol,
    },
    "error"
  );

  expect(errorResp.type).toBe("error");
  expect(errorResp.reason).toBe("forbidden");
});
