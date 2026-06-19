// shell（host）的根元件：依登入狀態與路由，動態掛載 auth / chat 兩個 remote。

import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';

import { API_BASE_URL, WS_BASE_URL } from './config';
import { useAuth } from './useAuth';

// Module Federation 動態載入：實際模組在執行期由各 remote 的 remoteEntry.js 提供。
const AuthApp = lazy(() => import('auth/AuthApp'));
const ChatApp = lazy(() => import('chat/ChatApp'));

/** 全頁載入占位：驗證 token 或 lazy 載入 remote 時顯示。 */
function Loading({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center text-slate-400">
      {label}
    </div>
  );
}

/** shell 根元件：依 auth 狀態與路由掛載 auth / chat remote。 */
export default function App() {
  const auth = useAuth();
  const navigate = useNavigate();

  // 啟動時若帶著舊 token 正在驗證 currentUser，先顯示載入避免畫面閃動。
  if (auth.status === 'loading') {
    return <Loading label="載入中…" />;
  }

  return (
    <Routes>
      {/* /login：未登入掛 auth remote；已登入則導回首頁。 */}
      <Route
        path="/login"
        element={
          auth.status === 'authenticated' ? (
            <Navigate to="/" replace />
          ) : (
            <Suspense fallback={<Loading label="載入登入模組…" />}>
              <AuthApp
                apiBaseUrl={API_BASE_URL}
                onAuthSuccess={(token) => {
                  auth.login(token);
                  navigate('/', { replace: true });
                }}
              />
            </Suspense>
          )
        }
      />
      {/* /：已登入掛 chat remote，把 token/currentUser 以 props 下傳；否則導去登入。 */}
      <Route
        path="/"
        element={
          auth.status === 'authenticated' && auth.token && auth.currentUser ? (
            <Suspense fallback={<Loading label="載入聊天模組…" />}>
              <ChatApp
                token={auth.token}
                currentUser={auth.currentUser}
                apiBaseUrl={API_BASE_URL}
                wsBaseUrl={WS_BASE_URL}
                onLogout={() => {
                  auth.logout();
                  navigate('/login', { replace: true });
                }}
              />
            </Suspense>
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
      {/* 其餘路徑一律導回首頁。 */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
