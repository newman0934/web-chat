// auth remote 對外暴露的元件（shell 透過 Module Federation 載入）。
// 同一個元件用 mode 切換「登入 / 註冊」，成功後以 onAuthSuccess(token) 把 JWT 交回 shell。

import { useState } from 'react';

import type { AuthAppProps } from '../../contracts';

type Mode = 'login' | 'register';

// form：非欄位層級的整體錯誤（例如後端回的 detail 或連線失敗）。
interface FieldErrors {
  email?: string;
  display_name?: string;
  password?: string;
  form?: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** 前端先做基本驗證，避免無效請求；與後端 schema 規則一致（email 格式、密碼 ≥6）。 */
function validate(mode: Mode, email: string, displayName: string, password: string) {
  const errors: FieldErrors = {};
  if (!EMAIL_RE.test(email)) errors.email = '請輸入有效的 email';
  if (password.length < 6) errors.password = '密碼至少 6 碼';
  if (mode === 'register' && displayName.trim().length === 0) {
    errors.display_name = '請輸入顯示名稱';
  }
  return errors;
}

/** auth remote 主元件：登入 / 註冊表單，成功後以 callback 交回 JWT。 */
export default function AuthApp({ onAuthSuccess, apiBaseUrl }: AuthAppProps) {
  const [mode, setMode] = useState<Mode>('login');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});  
  const [submitting, setSubmitting] = useState(false);

  /** 提交表單：前端驗證 → 呼叫 /auth/login 或 /auth/register → 成功則 onAuthSuccess。 */
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // 先跑前端驗證；有錯就停在表單，不打 API。
    const found = validate(mode, email, displayName, password);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    try {
      // 登入 / 註冊端點與 body 形狀不同。
      const path = mode === 'login' ? '/auth/login' : '/auth/register';
      const body =
        mode === 'login'
          ? { email, password }
          : { email, display_name: displayName, password };
      const resp = await fetch(`${apiBaseUrl}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        // 後端錯誤訊息放在 detail（如 email 已註冊 / 密碼錯誤）。
        const data = await resp.json().catch(() => ({}));
        setErrors({ form: data.detail ?? '操作失敗，請稍後再試' });
        return;
      }
      // 成功：把 token 交回 shell，由 shell 保存並切換到聊天畫面。
      const data = (await resp.json()) as { access_token: string };
      onAuthSuccess(data.access_token);
    } catch {
      setErrors({ form: '無法連線到伺服器' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <form
        onSubmit={handleSubmit}
        noValidate
        className="w-full max-w-sm space-y-4 rounded-2xl bg-white p-8 shadow-lg"
      >
        <h1 className="text-2xl font-semibold text-slate-800">
          {mode === 'login' ? '登入' : '註冊'}
        </h1>

        <Field label="Email" error={errors.email}>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input"
            placeholder="you@example.com"
            aria-label="Email"
          />
        </Field>

        {mode === 'register' && (
          <Field label="顯示名稱" error={errors.display_name}>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="input"
              placeholder="你的名字"
              aria-label="顯示名稱"
            />
          </Field>
        )}

        <Field label="密碼" error={errors.password}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
            placeholder="至少 6 碼"
            aria-label="密碼"
          />
        </Field>

        {errors.form && (
          <p className="text-sm text-red-600" role="alert">
            {errors.form}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-indigo-600 py-2 font-medium text-white transition hover:bg-indigo-700 disabled:opacity-50"
        >
          {submitting ? '處理中…' : mode === 'login' ? '登入' : '註冊'}
        </button>

        <p className="text-center text-sm text-slate-500">
          {mode === 'login' ? '還沒有帳號？' : '已經有帳號了？'}{' '}
          <button
            type="button"
            className="font-medium text-indigo-600 hover:underline"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login');
              setErrors({});
            }}
          >
            {mode === 'login' ? '前往註冊' : '前往登入'}
          </button>
        </p>
      </form>
    </div>
  );
}

/** 表單欄位包裝：顯示 label、子 input 與欄位級錯誤訊息。 */
function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium text-slate-600">{label}</span>
      {children}
      {error && <span className="block text-sm text-red-600">{error}</span>}
    </label>
  );
}
