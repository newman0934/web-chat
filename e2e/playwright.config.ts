/**
 * Playwright 設定檔：啟動 backend + 三個前端服務，再跑 E2E 測試。
 *
 * 啟動順序（相依性）：
 *   1. backend（uvicorn :8000，套用 alembic migration 後才啟動）
 *   2. auth remote（build → preview :5001）
 *   3. chat remote（build → preview :5002）
 *   4. shell host（dev server :5000）
 *
 * 環境需求：
 *   - backend/.venv 已建立（見 CLAUDE.md）
 *   - frontend/auth、frontend/chat、frontend/shell 各自 npm install 完成
 */

import { defineConfig, devices } from "@playwright/test";
import path from "path";

// e2e 用的 SQLite 資料庫（每次跑前由 global-setup 清除重建）
const E2E_DB = path.resolve(__dirname, "e2e.db");
const BACKEND_VENV_PYTHON = path.resolve(
  __dirname,
  "../backend/.venv/Scripts/python.exe"
);
const BACKEND_DIR = path.resolve(__dirname, "../backend");
const AUTH_DIR = path.resolve(__dirname, "../frontend/auth");
const CHAT_DIR = path.resolve(__dirname, "../frontend/chat");
const SHELL_DIR = path.resolve(__dirname, "../frontend/shell");

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // 避免多個 context 同時搶 WS 連線干擾
  retries: 0,
  reporter: [["html", { open: "never" }], ["list"]],

  use: {
    baseURL: "http://localhost:5000",
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  /**
   * webServer 陣列依序啟動所有服務。
   * reuseExistingServer:true 讓開發者手動啟動的服務也能被沿用（不重複啟動）。
   * remote build 指令合併為單一 shell 命令（PowerShell）。
   */
  webServer: [
    {
      // 1. Backend：先 migrate 再啟動 uvicorn。
      // Playwright 在 Windows 透過 cmd.exe 執行 webServer command，故用 cmd 相容語法
      // （`&&` 串連、引號包路徑），不可用 PowerShell 的 `$env:` / `&` 呼叫運算子。
      // DATABASE_URL 改由下方 env 欄位注入（不在命令列內 inline 設定）。
      command: [
        `"${BACKEND_VENV_PYTHON}" -m alembic upgrade head`,
        `"${BACKEND_VENV_PYTHON}" -m uvicorn app.main:app --port 8000`,
      ].join(" && "),
      cwd: BACKEND_DIR,
      url: "http://localhost:8000/health",
      reuseExistingServer: true,
      timeout: 60_000,
      env: {
        DATABASE_URL: `sqlite+aiosqlite:///${E2E_DB.replace(/\\/g, "/")}`,
      },
    },
    {
      // 2. Auth remote：build 後 preview（Module Federation 限制，必須 build 才有 remoteEntry.js）
      command: "npm run build && npm run preview",
      cwd: AUTH_DIR,
      url: "http://localhost:5001",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      // 3. Chat remote：同上
      command: "npm run build && npm run preview",
      cwd: CHAT_DIR,
      url: "http://localhost:5002",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      // 4. Shell host：dev server（host 不需要 build）
      command: "npm run dev",
      cwd: SHELL_DIR,
      url: "http://localhost:5000",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
