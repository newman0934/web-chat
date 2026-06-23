/**
 * E2E spec: 線上狀態(presence) 後端 API 驗收(REST + WebSocket,無 UI)
 *
 * 場景(PR = Presence)：
 *   PR-01 好友首條連線上線 → 在線的我收到 presence online
 *   PR-02 好友末條連線斷開 → 我收到 offline + last_seen_at
 *   PR-03 GET /contacts 每筆含 online / last_seen_at
 *   PR-04 同一好友第二條連線不重播 online
 *   PR-05 仍有其他連線時某條斷開不誤報 offline
 *   PR-06 非好友上線不廣播給我
 *   PR-08 從未上線好友 → online=false / last_seen_at=null
 *
 * backend pytest(test_presence.py)已完整覆蓋首尾/廣播/權限;此處補 E2E 追溯。
 * 設計註記:presence 為 in-memory、單程序;last_seen 存 ConnectionManager(不落 DB)。
 */

import { test, expect, Page, BrowserContext } from "@playwright/test";
import {
  apiRegister,
  apiAddContact,
  apiGetContacts,
  apiMe,
  wsOpenCollector,
  wsCloseCollector,
  wsWaitForCollected,
  wsCollected,
} from "./helpers";

const API = "http://localhost:8000";
const PW = "TestPass123!";

/** 開一個獨立 context 的 page 並導到 health(供 WS 用)。 */
async function openPage(browser: any): Promise<{ ctx: BrowserContext; page: Page }> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(`${API}/health`);
  return { ctx, page };
}

// ── PR-01 / PR-02: 上線/離線廣播 + last_seen ────────────────────────────────
test("PR-01/02 好友上線→我收 online;末條斷線→我收 offline + last_seen", async ({
  request,
  browser,
}) => {
  const ts = Date.now();
  const aEmail = `pr-a-${ts}@example.com`;
  const bEmail = `pr-b-${ts}@example.com`;
  const ta = await apiRegister(request, aEmail, "Alice", PW);
  const tb = await apiRegister(request, bEmail, "Bob", PW);
  await apiAddContact(request, ta, bEmail);
  const bobId = (await apiMe(request, tb)).id;

  // Alice 持續監聽
  const alice = await openPage(browser);
  await wsOpenCollector(alice.page, ta);

  // Bob 上線 → Alice 收 online
  const bob = await openPage(browser);
  await wsOpenCollector(bob.page, tb);

  const online = await wsWaitForCollected(alice.page, "presence");
  const onEvt = online.find((m) => m.user_id === bobId);
  expect(onEvt).toBeTruthy();
  expect(onEvt.online).toBe(true);
  expect(onEvt.last_seen_at).toBeNull();

  // Bob 末條連線斷開 → Alice 收 offline + last_seen
  await wsCloseCollector(bob.page);
  await alice.page.waitForFunction(
    (uid) =>
      ((window as any).__wsMessages || []).some(
        (m: any) => m.type === "presence" && m.user_id === uid && m.online === false
      ),
    bobId,
    { timeout: 8000 }
  );
  const all = await wsCollected(alice.page, "presence");
  const offEvt = all.find((m) => m.user_id === bobId && m.online === false);
  expect(offEvt).toBeTruthy();
  expect(offEvt.last_seen_at).toBeTruthy(); // 帶最後上線時間

  await alice.ctx.close();
  await bob.ctx.close();
});

// ── PR-03 / PR-08: GET /contacts 帶 presence ────────────────────────────────
test("PR-03/08 /contacts 帶 online/last_seen;從未上線好友 false/null", async ({
  request,
  browser,
}) => {
  const ts = Date.now();
  const aEmail = `prc-a-${ts}@example.com`;
  const bEmail = `prc-b-${ts}@example.com`;
  const cEmail = `prc-c-${ts}@example.com`;
  const ta = await apiRegister(request, aEmail, "Alice", PW);
  const tb = await apiRegister(request, bEmail, "Bob", PW);
  await apiRegister(request, cEmail, "Carol", PW);
  await apiAddContact(request, ta, bEmail);
  await apiAddContact(request, ta, cEmail); // Carol 全程不上線

  // Bob 上線
  const bob = await openPage(browser);
  await wsOpenCollector(bob.page, tb);

  const contacts = await apiGetContacts(request, ta);
  const byEmail = Object.fromEntries(contacts.map((c: any) => [c.email, c]));
  expect(byEmail[bEmail].online).toBe(true);
  expect(byEmail[cEmail].online).toBe(false);
  expect(byEmail[cEmail].last_seen_at).toBeNull();

  await bob.ctx.close();
});

// ── PR-04 / PR-05: 多連線首尾 ────────────────────────────────────────────────
test("PR-04/05 第二條不重播 online;倒數第二條斷不誤報 offline;末條才 offline", async ({
  request,
  browser,
}) => {
  const ts = Date.now();
  const aEmail = `prm-a-${ts}@example.com`;
  const bEmail = `prm-b-${ts}@example.com`;
  const ta = await apiRegister(request, aEmail, "Alice", PW);
  const tb = await apiRegister(request, bEmail, "Bob", PW);
  await apiAddContact(request, ta, bEmail);
  const bobId = (await apiMe(request, tb)).id;

  const alice = await openPage(browser);
  await wsOpenCollector(alice.page, ta);

  // Bob 第一條
  const bob1 = await openPage(browser);
  await wsOpenCollector(bob1.page, tb);
  await wsWaitForCollected(alice.page, "presence");
  let online = (await wsCollected(alice.page, "presence")).filter(
    (m) => m.user_id === bobId && m.online === true
  );
  expect(online.length).toBe(1);

  // Bob 第二條 → 不再廣播 online
  const bob2 = await openPage(browser);
  await wsOpenCollector(bob2.page, tb);
  await alice.page.waitForTimeout(800);
  online = (await wsCollected(alice.page, "presence")).filter(
    (m) => m.user_id === bobId && m.online === true
  );
  expect(online.length).toBe(1); // 仍只有一筆

  // 關第一條(仍有第二條)→ 不誤報 offline
  await wsCloseCollector(bob1.page);
  await alice.page.waitForTimeout(800);
  let offline = (await wsCollected(alice.page, "presence")).filter(
    (m) => m.user_id === bobId && m.online === false
  );
  expect(offline.length).toBe(0);

  // 關第二條(末條)→ offline
  await wsCloseCollector(bob2.page);
  await alice.page.waitForFunction(
    (uid) =>
      ((window as any).__wsMessages || []).some(
        (m: any) => m.type === "presence" && m.user_id === uid && m.online === false
      ),
    bobId,
    { timeout: 8000 }
  );
  offline = (await wsCollected(alice.page, "presence")).filter(
    (m) => m.user_id === bobId && m.online === false
  );
  expect(offline.length).toBe(1);

  await alice.ctx.close();
  await bob1.ctx.close();
  await bob2.ctx.close();
});

// ── PR-06: 非好友不外洩 ─────────────────────────────────────────────────────
test("PR-06 非好友上線不廣播給我", async ({ request, browser }) => {
  const ts = Date.now();
  const aEmail = `prn-a-${ts}@example.com`;
  const bEmail = `prn-b-${ts}@example.com`;
  const xEmail = `prn-x-${ts}@example.com`;
  const ta = await apiRegister(request, aEmail, "Alice", PW);
  const tb = await apiRegister(request, bEmail, "Bob", PW);
  const tx = await apiRegister(request, xEmail, "Stranger", PW);
  await apiAddContact(request, ta, bEmail); // 只加 Bob,不加 Stranger
  const bobId = (await apiMe(request, tb)).id;
  const xId = (await apiMe(request, tx)).id;

  const alice = await openPage(browser);
  await wsOpenCollector(alice.page, ta);

  // 非好友 Stranger 先上線
  const stranger = await openPage(browser);
  await wsOpenCollector(stranger.page, tx);
  // 好友 Bob 後上線
  const bob = await openPage(browser);
  await wsOpenCollector(bob.page, tb);

  // 等到 Bob 的 online,確保事件已流動
  await alice.page.waitForFunction(
    (uid) =>
      ((window as any).__wsMessages || []).some(
        (m: any) => m.type === "presence" && m.user_id === uid
      ),
    bobId,
    { timeout: 8000 }
  );
  const presence = await wsCollected(alice.page, "presence");
  // 收得到 Bob、收不到 Stranger
  expect(presence.some((m) => m.user_id === bobId)).toBeTruthy();
  expect(presence.some((m) => m.user_id === xId)).toBeFalsy();

  await alice.ctx.close();
  await stranger.ctx.close();
  await bob.ctx.close();
});
