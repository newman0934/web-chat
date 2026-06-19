import React from 'react';
import ReactDOM from 'react-dom/client';

import type { CurrentUser } from '../../contracts';
import ChatApp from './ChatApp';
import './index.css';

// 獨立開發用 bootstrap：chat remote 可單獨啟動。
// 從 localStorage 取 token（可先用 auth remote / shell 登入後拿到），再抓 currentUser。
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8000';
const TOKEN_KEY = 'chatweb.token';

/** 獨立開發入口：從 localStorage 取 token，驗證後掛載 ChatApp。 */
async function bootstrap() {
  const root = ReactDOM.createRoot(document.getElementById('root')!);
  const token = localStorage.getItem(TOKEN_KEY);

  if (!token) {
    root.render(
      <div style={{ padding: 24, fontFamily: 'sans-serif' }}>
        獨立模式需要 token。請先用 shell（:5000）登入，或在 localStorage 設定
        <code> {TOKEN_KEY} </code>。
      </div>,
    );
    return;
  }

  const resp = await fetch(`${API_BASE_URL}/users/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) {
    localStorage.removeItem(TOKEN_KEY);
    root.render(<div style={{ padding: 24 }}>token 失效，請重新登入。</div>);
    return;
  }
  const currentUser = (await resp.json()) as CurrentUser;

  root.render(
    <React.StrictMode>
      <ChatApp
        token={token}
        currentUser={currentUser}
        apiBaseUrl={API_BASE_URL}
        wsBaseUrl={WS_BASE_URL}
        onLogout={() => {
          localStorage.removeItem(TOKEN_KEY);
          location.reload();
        }}
      />
    </React.StrictMode>,
  );
}

void bootstrap();
