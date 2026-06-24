// 多附件的純驗證邏輯(抽離 React,便於單元測試):數量 / 單檔 / 總量上限。

import {
  MAX_ATTACHMENTS,
  MAX_ATTACHMENTS_TOTAL_BYTES,
  MAX_FILE_BYTES,
} from '../../contracts';

export interface AttachmentValidation {
  ok: boolean;
  error?: string;
}

/**
 * 驗證「目前待送附件 + 新加入檔案」是否合規。
 * @param currentSizes 已在待送區的附件大小（bytes）
 * @param incomingSizes 新選取檔案的大小（bytes）
 */
export function validateAttachments(
  currentSizes: number[],
  incomingSizes: number[],
): AttachmentValidation {
  if (incomingSizes.some((s) => s > MAX_FILE_BYTES)) {
    return { ok: false, error: '單一檔案不可超過 1MB' };
  }
  if (currentSizes.length + incomingSizes.length > MAX_ATTACHMENTS) {
    return { ok: false, error: `一則訊息最多 ${MAX_ATTACHMENTS} 個附件` };
  }
  const total = [...currentSizes, ...incomingSizes].reduce((a, b) => a + b, 0);
  if (total > MAX_ATTACHMENTS_TOTAL_BYTES) {
    return { ok: false, error: '附件總量不可超過 10MB' };
  }
  return { ok: true };
}
