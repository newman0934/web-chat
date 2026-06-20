import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CallOverlay } from './CallOverlay';

const base = {
  peerName: 'Bob',
  localStream: null,
  remoteStream: null,
  micOn: true,
  cameraOn: true,
  onAccept: vi.fn(),
  onReject: vi.fn(),
  onHangup: vi.fn(),
  onToggleMic: vi.fn(),
  onToggleCamera: vi.fn(),
};

describe('CallOverlay', () => {
  it('idle 時不渲染', () => {
    const { container } = render(<CallOverlay status="idle" {...base} />);
    expect(container.firstChild).toBeNull();
  });

  it('incoming 顯示來電者與接聽/拒接', () => {
    render(<CallOverlay status="incoming" {...base} />);
    expect(screen.getByText(/Bob/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '接聽' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '拒接' })).toBeInTheDocument();
  });

  it('calling 顯示撥號中與取消', () => {
    render(<CallOverlay status="calling" {...base} />);
    expect(screen.getByText(/撥號中/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument();
  });

  it('connected 顯示靜音/鏡頭/掛斷控制', () => {
    render(<CallOverlay status="connected" {...base} />);
    expect(screen.getByRole('button', { name: '靜音' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '關閉鏡頭' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '掛斷' })).toBeInTheDocument();
  });
});
