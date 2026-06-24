import { describe, expect, it } from 'vitest';

import { validateAttachments } from './attachments';

const MB = 1024 * 1024;

describe('validateAttachments', () => {
  it('合規 → ok', () => {
    expect(validateAttachments([0.5 * MB], [0.5 * MB]).ok).toBe(true);
  });

  it('單檔 > 1MB → 擋', () => {
    const r = validateAttachments([], [1.5 * MB]);
    expect(r.ok).toBe(false);
    expect(r.error).toContain('1MB');
  });

  it('數量 > 5 → 擋', () => {
    const sizes = Array(5).fill(0.1 * MB);
    const r = validateAttachments(sizes, [0.1 * MB]); // 5 + 1 = 6
    expect(r.ok).toBe(false);
    expect(r.error).toContain('5');
  });

  it('剛好 5 個 → ok', () => {
    expect(validateAttachments([0.1 * MB, 0.1 * MB], [0.1 * MB, 0.1 * MB, 0.1 * MB]).ok).toBe(true);
  });

  it('總量 > 10MB → 擋（以中繼大小模擬）', () => {
    // 每檔 1MB(合規)、4 現有 + 1 新 = 5 個,但總量需 > 10MB:用各 2.5MB? 會先被單檔擋。
    // 改以「未超單檔但總和超標」不可能(5×1MB=5MB),故總量上限實務上由數量上限保證。
    // 此處驗證函式對「總量」分支本身正確:直接給超標 currentSizes(繞過單檔/數量先決條件不成立時)。
    const r = validateAttachments([6 * MB, 5 * MB], []); // 2 個、各超 1MB 但 incoming 空 → 不觸發單檔檢查
    expect(r.ok).toBe(false);
    expect(r.error).toContain('10MB');
  });
});
