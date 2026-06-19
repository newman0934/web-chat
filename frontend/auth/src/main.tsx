import React from 'react';
import ReactDOM from 'react-dom/client';

import AuthApp from './AuthApp';
import './index.css';

// 獨立開發用 bootstrap：auth remote 可單獨啟動，模擬 shell 的 props。
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthApp
      apiBaseUrl={API_BASE_URL}
      onAuthSuccess={(token) => {
        // 獨立模式下沒有 shell，僅示意。
        console.info('auth success, token =', token);
        alert('登入成功（獨立模式）');
      }}
    />
  </React.StrictMode>,
);
