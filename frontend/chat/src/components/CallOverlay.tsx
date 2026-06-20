// 通話覆蓋層：依通話狀態顯示來電 / 撥號中 / 通話中畫面。
// <video> 的 srcObject 經 ref 設定（jsdom 不支援播放，但不影響測試斷言文字/按鈕）。

import { useEffect, useRef } from 'react';

import type { CallStatus } from '../callMachine';

export interface CallOverlayProps {
  status: CallStatus;
  peerName: string | null;
  localStream: MediaStream | null;
  remoteStream: MediaStream | null;
  micOn: boolean;
  cameraOn: boolean;
  onAccept: () => void;
  onReject: () => void;
  onHangup: () => void;
  onToggleMic: () => void;
  onToggleCamera: () => void;
}

/** 把 MediaStream 綁到 <video>（srcObject 無法用 JSX 屬性設定）。 */
function useVideoStream(stream: MediaStream | null) {
  const ref = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (ref.current) ref.current.srcObject = stream;
  }, [stream]);
  return ref;
}

/** 全螢幕通話覆蓋層；status 為 idle 時不渲染。 */
export function CallOverlay({
  status, peerName, localStream, remoteStream, micOn, cameraOn,
  onAccept, onReject, onHangup, onToggleMic, onToggleCamera,
}: CallOverlayProps) {
  const remoteRef = useVideoStream(remoteStream);
  const localRef = useVideoStream(localStream);

  if (status === 'idle') return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-slate-900/95 text-white">
      {status === 'incoming' && (
        <div className="flex flex-col items-center gap-6">
          <p className="text-xl"><span className="font-semibold">{peerName}</span> 來電…</p>
          <div className="flex gap-4">
            <button onClick={onAccept} className="rounded-full bg-green-600 px-6 py-3 font-medium hover:bg-green-700">接聽</button>
            <button onClick={onReject} className="rounded-full bg-red-600 px-6 py-3 font-medium hover:bg-red-700">拒接</button>
          </div>
        </div>
      )}

      {status === 'calling' && (
        <div className="flex flex-col items-center gap-6">
          <p className="text-xl">撥號中… <span className="font-semibold">{peerName}</span></p>
          <button onClick={onHangup} className="rounded-full bg-red-600 px-6 py-3 font-medium hover:bg-red-700">取消</button>
        </div>
      )}

      {status === 'connected' && (
        <>
          <video ref={remoteRef} autoPlay playsInline className="max-h-[70vh] max-w-[90vw] rounded-lg bg-black" />
          <video ref={localRef} autoPlay playsInline muted className="absolute bottom-24 right-6 h-32 w-44 rounded-lg border border-white/30 bg-black object-cover" />
          <div className="absolute bottom-8 flex gap-4">
            <button onClick={onToggleMic} className="rounded-full bg-white/15 px-5 py-3 hover:bg-white/25" aria-label={micOn ? '靜音' : '取消靜音'}>
              {micOn ? '🎙️' : '🔇'}
            </button>
            <button onClick={onToggleCamera} className="rounded-full bg-white/15 px-5 py-3 hover:bg-white/25" aria-label={cameraOn ? '關閉鏡頭' : '開啟鏡頭'}>
              {cameraOn ? '📷' : '🚫'}
            </button>
            <button onClick={onHangup} className="rounded-full bg-red-600 px-5 py-3 hover:bg-red-700" aria-label="掛斷">📞</button>
          </div>
        </>
      )}
    </div>
  );
}
