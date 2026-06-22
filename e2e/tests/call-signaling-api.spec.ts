/**
 * E2E spec: 語音/視訊「訊號中繼」後端 API 驗收（純 WebSocket，無媒體、無 UI）
 *
 * 後端只在好友之間「轉送」SDP / ICE 訊號，不解讀內容、不落庫；媒體流為 P2P 不經後端。
 * 故此 spec 驗的是訊號路由與守門，不涉及真正的 WebRTC 連線。
 *
 * 協定（client→server）：
 *   {type:"call_offer",  to_user_id, sdp}
 *   {type:"call_answer", to_user_id, sdp}
 *   {type:"call_ice",    to_user_id, candidate}
 *   {type:"call_reject", to_user_id}
 *   {type:"call_hangup", to_user_id}
 * server 轉送給對端時附 from:{id,display_name}；offer/answer 帶 sdp、ice 帶 candidate。
 * 對端離線且為 call_offer → 回撥號者 {type:"call_unavailable", to_user_id}；
 * 非好友 → {type:"error", reason:"forbidden"}；缺 to_user_id → invalid_payload。
 *
 * 場景（VC = Voice/Video Call signaling）：
 *   VC-01 call_offer 轉送 → 對端收到，from.id 為撥號者、帶 sdp
 *   VC-02 call_answer 轉送 → 對端收到，帶 sdp
 *   VC-03 call_ice 轉送 → 對端收到，帶 candidate
 *   VC-04 call_reject / call_hangup 轉送 → 對端收到
 *   VC-05 非好友撥號被拒（forbidden）
 *   VC-06 缺 to_user_id 被拒（invalid_payload）
 *   VC-07 對端離線時 call_offer → 撥號者收到 call_unavailable
 *
 * backend pytest（test_ws_call.py）已覆蓋這些路由/守門；此處補 E2E 追溯。
 */

import { test, expect, Page, Browser } from "@playwright/test";
import { apiRegister, apiAddContact, apiMe, wsRequest, wsSendRaw, wsOpenCollector, wsWaitForCollected } from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";

const U = {
  alice: { email: `vc-alice-${TS}@example.com`, name: "VC-Alice" },
  bob:   { email: `vc-bob-${TS}@example.com`,   name: "VC-Bob"   },
  carol: { email: `vc-carol-${TS}@example.com`, name: "VC-Carol" }, // 與 Alice 非好友
};

let tokens: Record<"alice" | "bob" | "carol", string> = {} as any;
let ids: Record<"alice" | "bob" | "carol", string> = {} as any;
let sharedPage: Page; // 宿主 Alice 的送訊 evaluate

test.beforeAll(async ({ request, browser }) => {
  tokens.alice = await apiRegister(request, U.alice.email, U.alice.name, PW);
  tokens.bob   = await apiRegister(request, U.bob.email,   U.bob.name,   PW);
  tokens.carol = await apiRegister(request, U.carol.email, U.carol.name, PW);
  ids.alice = (await apiMe(request, tokens.alice)).id;
  ids.bob   = (await apiMe(request, tokens.bob)).id;
  ids.carol = (await apiMe(request, tokens.carol)).id;

  // Alice↔Bob 成為好友（通話前提）。Carol 刻意不加。
  await apiAddContact(request, tokens.alice, U.bob.email);

  const ctx = await browser.newContext();
  sharedPage = await ctx.newPage();
  await sharedPage.goto(`${API}/health`);
});

/** 開一條 Bob 的持續監聽連線（獨立 context）。 */
async function bobListener(browser: Browser): Promise<Page> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(`${API}/health`);
  await wsOpenCollector(page, tokens.bob);
  return page;
}

// ── VC-01: call_offer 轉送 ───────────────────────────────────────────────
test("VC-01 call_offer 轉送：Bob 收到，from.id 為 Alice、帶 sdp", async ({ browser }) => {
  const bobPage = await bobListener(browser);
  await wsSendRaw(sharedPage, tokens.alice, {
    type: "call_offer",
    to_user_id: ids.bob,
    sdp: "FAKE_OFFER_SDP",
  });
  const got = await wsWaitForCollected(bobPage, "call_offer");
  const sig = got.find((m) => m.from?.id === ids.alice);
  expect(sig).toBeTruthy();
  expect(sig.sdp).toBe("FAKE_OFFER_SDP");
  await bobPage.context().close();
});

// ── VC-02: call_answer 轉送 ──────────────────────────────────────────────
test("VC-02 call_answer 轉送：Bob 收到，帶 sdp", async ({ browser }) => {
  const bobPage = await bobListener(browser);
  await wsSendRaw(sharedPage, tokens.alice, {
    type: "call_answer",
    to_user_id: ids.bob,
    sdp: "FAKE_ANSWER_SDP",
  });
  const got = await wsWaitForCollected(bobPage, "call_answer");
  const sig = got.find((m) => m.from?.id === ids.alice);
  expect(sig).toBeTruthy();
  expect(sig.sdp).toBe("FAKE_ANSWER_SDP");
  await bobPage.context().close();
});

// ── VC-03: call_ice 轉送 ─────────────────────────────────────────────────
test("VC-03 call_ice 轉送：Bob 收到，帶 candidate", async ({ browser }) => {
  const bobPage = await bobListener(browser);
  await wsSendRaw(sharedPage, tokens.alice, {
    type: "call_ice",
    to_user_id: ids.bob,
    candidate: "FAKE_ICE_CANDIDATE",
  });
  const got = await wsWaitForCollected(bobPage, "call_ice");
  const sig = got.find((m) => m.from?.id === ids.alice);
  expect(sig).toBeTruthy();
  expect(sig.candidate).toBe("FAKE_ICE_CANDIDATE");
  await bobPage.context().close();
});

// ── VC-04: call_reject / call_hangup 轉送 ────────────────────────────────
test("VC-04 call_reject 與 call_hangup 皆轉送給對端", async ({ browser }) => {
  const bobPage = await bobListener(browser);
  await wsSendRaw(sharedPage, tokens.alice, { type: "call_reject", to_user_id: ids.bob });
  await wsSendRaw(sharedPage, tokens.alice, { type: "call_hangup", to_user_id: ids.bob });

  const rejects = await wsWaitForCollected(bobPage, "call_reject");
  expect(rejects.some((m) => m.from?.id === ids.alice)).toBeTruthy();
  const hangups = await wsWaitForCollected(bobPage, "call_hangup");
  expect(hangups.some((m) => m.from?.id === ids.alice)).toBeTruthy();

  await bobPage.context().close();
});

// ── VC-05: 非好友撥號被拒 ────────────────────────────────────────────────
test("VC-05 對非好友 Carol 撥號被拒：forbidden", async () => {
  const err = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "call_offer", to_user_id: ids.carol, sdp: "X" },
    "error"
  );
  expect(err.reason).toBe("forbidden");
});

// ── VC-06: 缺 to_user_id 被拒 ────────────────────────────────────────────
test("VC-06 缺 to_user_id 的 call_offer 被拒：invalid_payload", async () => {
  const err = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "call_offer", sdp: "X" },
    "error"
  );
  expect(err.reason).toBe("invalid_payload");
});

// ── VC-07: 對端離線 → call_unavailable ───────────────────────────────────
test("VC-07 Bob 離線時對其 call_offer → 撥號者收到 call_unavailable", async () => {
  // 不開 Bob 的連線（離線）。Alice 撥號，預期自己 socket 收到 call_unavailable。
  const resp = await wsRequest(
    sharedPage,
    tokens.alice,
    { type: "call_offer", to_user_id: ids.bob, sdp: "OFFER_TO_OFFLINE" },
    "call_unavailable"
  );
  expect(resp.type).toBe("call_unavailable");
  expect(resp.to_user_id).toBe(ids.bob);
});
