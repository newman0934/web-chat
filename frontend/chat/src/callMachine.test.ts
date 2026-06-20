import { describe, expect, it } from 'vitest';

import { callReducer, initialCallState } from './callMachine';

const peer = { id: 'u-bob', display_name: 'Bob' };
const sdp = { type: 'offer', sdp: 'v=0' } as RTCSessionDescriptionInit;

describe('callReducer', () => {
  it('START 進入 calling 並記住對方', () => {
    const s = callReducer(initialCallState, { type: 'START', peer });
    expect(s.status).toBe('calling');
    expect(s.peer).toEqual(peer);
  });

  it('idle 收到 INCOMING 進入 incoming 並暫存 offer', () => {
    const s = callReducer(initialCallState, { type: 'INCOMING', peer, sdp });
    expect(s.status).toBe('incoming');
    expect(s.pendingOffer).toEqual(sdp);
  });

  it('忙線（非 idle）時 INCOMING 不改變狀態', () => {
    const calling = callReducer(initialCallState, { type: 'START', peer });
    const s = callReducer(calling, { type: 'INCOMING', peer: { id: 'x', display_name: 'X' }, sdp });
    expect(s).toBe(calling);
  });

  it('incoming 收到 ACCEPTED 進入 connected', () => {
    const incoming = callReducer(initialCallState, { type: 'INCOMING', peer, sdp });
    const s = callReducer(incoming, { type: 'ACCEPTED' });
    expect(s.status).toBe('connected');
  });

  it('calling 收到 CONNECTED（對方接聽）進入 connected', () => {
    const calling = callReducer(initialCallState, { type: 'START', peer });
    const s = callReducer(calling, { type: 'CONNECTED' });
    expect(s.status).toBe('connected');
  });

  it('END 一律回到 idle 並清空', () => {
    const calling = callReducer(initialCallState, { type: 'START', peer });
    const s = callReducer(calling, { type: 'END' });
    expect(s).toEqual(initialCallState);
  });
});
