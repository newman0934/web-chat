/**
 * E2E spec: 多附件 後端 API 驗收(REST 上傳 + WS 送訊,無 UI)
 *
 * 對應 BDD MA-01、02、03、05、06、07。MA-04(總量 >10MB)以 ≤1MB×5 無法真實觸發,
 * 由 backend pytest(test_attachments_too_large,直接設 size 中繼)覆蓋。
 */
import { test, expect, Page } from "@playwright/test";
import { apiRegister, apiAddContact, apiMe, wsSendMessage, wsRequest } from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";

const U = {
  alice: { email: `am-a-${TS}@example.com`, name: `AM-Alice-${TS}` },
  bob: { email: `am-b-${TS}@example.com`, name: `AM-Bob-${TS}` },
};

let tokens: Record<"alice" | "bob", string> = {} as any;
let ids: Record<"alice" | "bob", string> = {} as any;
let convAB: string;
let page: Page;

async function upload(request: any, token: string, name: string, size = 1024): Promise<string> {
  const resp = await request.post(`${API}/uploads`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: { file: { name, mimeType: "image/png", buffer: Buffer.alloc(size, 1) } },
  });
  expect(resp.status()).toBe(201);
  return (await resp.json()).id;
}

test.beforeAll(async ({ request, browser }) => {
  tokens.alice = await apiRegister(request, U.alice.email, U.alice.name, PW);
  tokens.bob = await apiRegister(request, U.bob.email, U.bob.name, PW);
  for (const k of ["alice", "bob"] as const) ids[k] = (await apiMe(request, tokens[k])).id;
  convAB = (await apiAddContact(request, tokens.alice, U.bob.email)).conversation_id;
  const ctx = await browser.newContext();
  page = await ctx.newPage();
  await page.goto(`${API}/health`);
});

function sendMsg(token: string, conv: string, attachment_ids: string[], waitType = "ack") {
  return wsRequest(
    page, token,
    { type: "message", conversation_id: conv, content: "", attachment_ids, temp_id: `t-${Date.now()}` },
    waitType,
  );
}

// ── MA-01:多附件依序 ─────────────────────────────────────────────────────
test("MA-01 多附件送出並依序顯示", async ({ request }) => {
  const a1 = await upload(request, tokens.alice, "1.png");
  const a2 = await upload(request, tokens.alice, "2.png");
  const a3 = await upload(request, tokens.alice, "3.png");
  const ack = await sendMsg(tokens.alice, convAB, [a1, a2, a3]);
  expect(ack.message.attachments.map((a: any) => a.id)).toEqual([a1, a2, a3]);
});

// ── MA-02:超過 5 個 ─────────────────────────────────────────────────────
test("MA-02 超過 5 個附件被拒", async ({ request }) => {
  const ids6 = [];
  for (let i = 0; i < 6; i++) ids6.push(await upload(request, tokens.alice, `m${i}.png`));
  const err = await sendMsg(tokens.alice, convAB, ids6, "error");
  expect(err.reason).toBe("too_many_attachments");
});

// ── MA-03:單檔 >1MB ─────────────────────────────────────────────────────
test("MA-03 單檔超過 1MB 上傳被拒(413)", async ({ request }) => {
  const resp = await request.post(`${API}/uploads`, {
    headers: { Authorization: `Bearer ${tokens.alice}` },
    multipart: { file: { name: "big.bin", mimeType: "application/octet-stream", buffer: Buffer.alloc(1024 * 1024 + 1, 1) } },
  });
  expect(resp.status()).toBe(413);
});

// ── MA-05:轉發複製全部 ──────────────────────────────────────────────────
test("MA-05 轉發複製全部附件", async ({ request }) => {
  // Alice↔Carol 當轉發目標
  const carol = { email: `am-c-${TS}@example.com`, name: `AM-Carol-${TS}` };
  await apiRegister(request, carol.email, carol.name, PW);
  const toConv = (await apiAddContact(request, tokens.alice, carol.email)).conversation_id;
  const a1 = await upload(request, tokens.alice, "f1.png");
  const a2 = await upload(request, tokens.alice, "f2.png");
  const src = await sendMsg(tokens.alice, convAB, [a1, a2]);
  const fwd = await wsRequest(
    page, tokens.alice,
    { type: "forward", message_id: src.message.id, to_conversation_id: toConv },
    "message",
  );
  expect(fwd.message.attachments.length).toBe(2);
});

// ── MA-06:撤回清空附件 ──────────────────────────────────────────────────
test("MA-06 撤回清空附件", async ({ request }) => {
  const a1 = await upload(request, tokens.alice, "r1.png");
  const a2 = await upload(request, tokens.alice, "r2.png");
  const ack = await sendMsg(tokens.alice, convAB, [a1, a2]);
  const evt = await wsRequest(page, tokens.alice, { type: "recall", message_id: ack.message.id }, "message_updated");
  expect(evt.message.attachments).toEqual([]);
});

// ── MA-07:非本人附件 ────────────────────────────────────────────────────
test("MA-07 非本人附件被拒", async ({ request }) => {
  const mine = await upload(request, tokens.alice, "mine.png");
  const bobs = await upload(request, tokens.bob, "bobs.png");
  const err = await sendMsg(tokens.alice, convAB, [mine, bobs], "error");
  expect(err.reason).toBe("invalid_attachment");
});
