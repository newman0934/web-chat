import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// 把外部副作用相依(REST / WebSocket / 通話)換成最小替身,只驗 ChatApp 組裝與掛載不崩潰。
vi.mock('./api', () => ({
  ApiClient: class {
    async listConversations() { return []; }
    async listContacts() { return []; }
    async listNotifications() { return { items: [], unread_count: 0 }; }
  },
  ApiError: class extends Error {},
  UnauthorizedError: class extends Error {},
}));
vi.mock('./useChatSocket', () => ({
  useChatSocket: () => ({ status: 'open', send: () => true }),
}));
vi.mock('./useCall', () => ({
  useCall: () => ({
    callState: 'idle', peer: null, localStream: null, remoteStream: null,
    micOn: true, cameraOn: true,
    startCall() {}, acceptCall() {}, rejectCall() {}, hangup() {},
    toggleMic() {}, toggleCamera() {}, handleSignal() {},
  }),
}));

import ChatApp from './ChatApp';
import { useChatStore } from './store';

beforeEach(() => {
  useChatStore.getState().reset();
});

describe('ChatApp 掛載', () => {
  it('渲染側欄(目前使用者)與空對話提示,不崩潰', async () => {
    render(
      <ChatApp
        token="t"
        currentUser={{ id: 'me', email: 'me@example.com', display_name: '我' }}
        apiBaseUrl="http://api"
        wsBaseUrl="ws://api"
        onLogout={vi.fn()}
      />,
    );
    expect(await screen.findByText('我')).toBeInTheDocument();           // Sidebar header
    expect(screen.getByText('選擇一個對話開始聊天')).toBeInTheDocument(); // 無 active 對話
  });
});
