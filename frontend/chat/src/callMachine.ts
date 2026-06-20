// 1對1 通話的純狀態機（不碰 WebRTC，可獨立單元測試）。
// status 流：idle → calling/incoming → connected → idle。

export type CallStatus = 'idle' | 'calling' | 'incoming' | 'connected';

export interface CallPeer {
  id: string;
  display_name: string;
}

export interface CallState {
  status: CallStatus;
  /** 對話中的對方（撥號目標或來電者）。 */
  peer: CallPeer | null;
  /** 來電時暫存對方的 SDP offer，接聽時用來建立 answer。 */
  pendingOffer: RTCSessionDescriptionInit | null;
}

export type CallAction =
  | { type: 'START'; peer: CallPeer }
  | { type: 'INCOMING'; peer: CallPeer; sdp: RTCSessionDescriptionInit }
  | { type: 'ACCEPTED' }
  | { type: 'CONNECTED' }
  | { type: 'END' };

export const initialCallState: CallState = {
  status: 'idle',
  peer: null,
  pendingOffer: null,
};

/** 依 action 推進通話狀態；END 一律回 idle。 */
export function callReducer(state: CallState, action: CallAction): CallState {
  switch (action.type) {
    case 'START':
      return { status: 'calling', peer: action.peer, pendingOffer: null };
    case 'INCOMING':
      // 忙線（已在通話流程中）時忽略新來電，維持現狀（簡化：不另作忙線通知）。
      if (state.status !== 'idle') return state;
      return { status: 'incoming', peer: action.peer, pendingOffer: action.sdp };
    case 'ACCEPTED':
      if (state.status !== 'incoming') return state;
      return { ...state, status: 'connected' };
    case 'CONNECTED':
      return { ...state, status: 'connected' };
    case 'END':
      return initialCallState;
    default:
      return state;
  }
}
