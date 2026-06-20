// 通話副作用 hook：持有單一 RTCPeerConnection、本地/遠端媒體串流，
// 串接 callReducer 與 /ws 訊號。媒體走 P2P，永不經過後端。
// 注意：jsdom 無 WebRTC API，本檔以手動 E2E（兩個瀏覽器）驗證，無單元測試。

import { useCallback, useReducer, useRef, useState } from 'react';

import type { ClientWsMessage, ServerWsMessage } from '../../contracts';
import {
  callReducer,
  initialCallState,
  type CallPeer,
  type CallStatus,
} from './callMachine';

const ICE_SERVERS: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }];

export interface UseCall {
  callState: CallStatus;
  peer: CallPeer | null;
  localStream: MediaStream | null;
  remoteStream: MediaStream | null;
  micOn: boolean;
  cameraOn: boolean;
  startCall: (peer: CallPeer) => Promise<void>;
  acceptCall: () => Promise<void>;
  rejectCall: () => void;
  hangup: () => void;
  toggleMic: () => void;
  toggleCamera: () => void;
  handleSignal: (msg: ServerWsMessage) => void;
}

/** 管理 1對1 WebRTC 通話的生命週期與訊號收發。 */
export function useCall(send: (m: ClientWsMessage) => boolean): UseCall {
  const [state, dispatch] = useReducer(callReducer, initialCallState);
  const [localStream, setLocalStream] = useState<MediaStream | null>(null);
  const [remoteStream, setRemoteStream] = useState<MediaStream | null>(null);
  const [micOn, setMicOn] = useState(true);
  const [cameraOn, setCameraOn] = useState(true);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localRef = useRef<MediaStream | null>(null);
  // remoteDescription 設定前到達的 ICE candidate 先排隊，設定後再補加。
  const pendingIce = useRef<RTCIceCandidateInit[]>([]);
  // state 在非同步 callback 內可能過期，用 ref 取最新值。
  const stateRef = useRef(state);
  stateRef.current = state;

  // toggle 用 ref 追最新開關狀態，避免 useCallback 閉包過期。
  const stateRefMic = useRef(micOn);
  stateRefMic.current = micOn;
  const stateRefCam = useRef(cameraOn);
  stateRefCam.current = cameraOn;

  /** 建立 RTCPeerConnection：綁定 ICE 送出與遠端 track 接收。 */
  const createPc = useCallback(
    (peerId: string): RTCPeerConnection => {
      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      pc.onicecandidate = (e) => {
        if (e.candidate) {
          send({ type: 'call_ice', to_user_id: peerId, candidate: e.candidate.toJSON() });
        }
      };
      pc.ontrack = (e) => {
        setRemoteStream(e.streams[0] ?? null);
      };
      pcRef.current = pc;
      return pc;
    },
    [send],
  );

  /** 取得本地音視訊串流並記錄。 */
  const getLocalMedia = useCallback(async (): Promise<MediaStream> => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    localRef.current = stream;
    setLocalStream(stream);
    setMicOn(true);
    setCameraOn(true);
    return stream;
  }, []);

  /** 套用排隊中的 ICE candidate（remoteDescription 設定後呼叫）。 */
  const flushIce = useCallback(async () => {
    const pc = pcRef.current;
    if (!pc) return;
    for (const c of pendingIce.current) {
      try {
        await pc.addIceCandidate(c);
      } catch {
        // 忽略無效 candidate
      }
    }
    pendingIce.current = [];
  }, []);

  /** 關閉連線、停止本地 track、清空遠端串流與 ICE 佇列。 */
  const cleanup = useCallback(() => {
    pcRef.current?.close();
    pcRef.current = null;
    localRef.current?.getTracks().forEach((t) => t.stop());
    localRef.current = null;
    pendingIce.current = [];
    setLocalStream(null);
    setRemoteStream(null);
  }, []);

  const startCall = useCallback(
    async (peer: CallPeer) => {
      dispatch({ type: 'START', peer });
      const stream = await getLocalMedia();
      const pc = createPc(peer.id);
      stream.getTracks().forEach((t) => pc.addTrack(t, stream));
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      send({ type: 'call_offer', to_user_id: peer.id, sdp: offer });
    },
    [createPc, getLocalMedia, send],
  );

  const acceptCall = useCallback(async () => {
    const cur = stateRef.current;
    if (cur.status !== 'incoming' || !cur.peer || !cur.pendingOffer) return;
    const peer = cur.peer;
    const stream = await getLocalMedia();
    const pc = createPc(peer.id);
    await pc.setRemoteDescription(cur.pendingOffer);
    stream.getTracks().forEach((t) => pc.addTrack(t, stream));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);
    await flushIce();
    send({ type: 'call_answer', to_user_id: peer.id, sdp: answer });
    dispatch({ type: 'ACCEPTED' });
  }, [createPc, flushIce, getLocalMedia, send]);

  const rejectCall = useCallback(() => {
    const peer = stateRef.current.peer;
    if (peer) send({ type: 'call_reject', to_user_id: peer.id });
    cleanup();
    dispatch({ type: 'END' });
  }, [cleanup, send]);

  const hangup = useCallback(() => {
    const peer = stateRef.current.peer;
    if (peer) send({ type: 'call_hangup', to_user_id: peer.id });
    cleanup();
    dispatch({ type: 'END' });
  }, [cleanup, send]);

  const toggleMic = useCallback(() => {
    const stream = localRef.current;
    if (!stream) return;
    const next = !stateRefMic.current;
    stream.getAudioTracks().forEach((t) => (t.enabled = next));
    stateRefMic.current = next;
    setMicOn(next);
  }, []);

  const toggleCamera = useCallback(() => {
    const stream = localRef.current;
    if (!stream) return;
    const next = !stateRefCam.current;
    stream.getVideoTracks().forEach((t) => (t.enabled = next));
    stateRefCam.current = next;
    setCameraOn(next);
  }, []);

  const handleSignal = useCallback(
    (msg: ServerWsMessage) => {
      switch (msg.type) {
        case 'call_offer':
          dispatch({ type: 'INCOMING', peer: msg.from, sdp: msg.sdp });
          break;
        case 'call_answer': {
          const pc = pcRef.current;
          if (!pc) return;
          void pc.setRemoteDescription(msg.sdp).then(flushIce);
          dispatch({ type: 'CONNECTED' });
          break;
        }
        case 'call_ice': {
          const pc = pcRef.current;
          if (pc && pc.remoteDescription) {
            void pc.addIceCandidate(msg.candidate).catch(() => {});
          } else {
            pendingIce.current.push(msg.candidate);
          }
          break;
        }
        case 'call_reject':
        case 'call_hangup':
        case 'call_unavailable':
          cleanup();
          dispatch({ type: 'END' });
          break;
        default:
          break;
      }
    },
    [cleanup, flushIce],
  );

  return {
    callState: state.status,
    peer: state.peer,
    localStream,
    remoteStream,
    micOn,
    cameraOn,
    startCall,
    acceptCall,
    rejectCall,
    hangup,
    toggleMic,
    toggleCamera,
    handleSignal,
  };
}
