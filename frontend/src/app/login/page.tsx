"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, LockKeyhole, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_BASE, apiFetch, apiGet, getApiBase, setAuthSession, type AuthUser } from "@/lib/api-client";

type Feedback = { type: "success" | "error"; message: string } | null;
type ProviderStatus = { google: boolean; facebook: boolean };

export default function LoginPage() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [providers, setProviders] = useState<ProviderStatus | null>(null);

  useEffect(() => {
    const oauthError = new URLSearchParams(window.location.search).get("oauth_error");
    if (oauthError) {
      window.history.replaceState(null, "", window.location.pathname);
      queueMicrotask(() => {
        setFeedback({ type: "error", message: oauthError });
        toast.error(oauthError);
      });
    }
    apiGet<ProviderStatus>("/api/auth/oauth/status/providers")
      .then(setProviders)
      .catch(() => setProviders({ google: false, facebook: false }));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFeedback(null);
    setLoading(true);
    try {
      const result = await apiFetch<{ access_token: string; user: AuthUser }>("/api/auth/login", {
        method: "POST",
        body: { username: identifier, password },
      });
      setAuthSession(result.access_token, result.user);
      setFeedback({ type: "success", message: "Đăng nhập thành công. Đang chuyển trang..." });
      toast.success("Đăng nhập thành công");
      await new Promise((resolve) => setTimeout(resolve, 500));
      router.replace("/accounts");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Đăng nhập thất bại. Vui lòng thử lại.";
      setFeedback({ type: "error", message });
      toast.error(message);
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-8">
      <div className="grid w-full max-w-5xl overflow-hidden rounded-2xl border border-white/10 bg-white shadow-2xl md:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden min-h-[580px] flex-col justify-between bg-slate-900 p-10 text-white md:flex">
          <div>
            <div className="mb-8 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-600"><ShieldCheck className="h-5 w-5" /></div>
            <h1 className="text-3xl font-semibold">FlowMeta</h1>
            <p className="mt-3 max-w-md text-sm leading-6 text-slate-300">Đăng nhập để quản lý tài khoản Facebook, tác vụ và lịch đăng trong một không gian bảo mật.</p>
          </div>
          <p className="text-xs text-slate-500">Automation Console · Secure access</p>
        </section>

        <section className="p-6 sm:p-10">
          <div className="mb-7">
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-white"><LockKeyhole className="h-4 w-4" /></div>
            <h2 className="text-2xl font-semibold text-slate-950">Chào mừng trở lại</h2>
            <p className="mt-1 text-sm text-slate-500">Đăng nhập bằng tài khoản FlowMeta hoặc tài khoản liên kết.</p>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <OAuthButton provider="google" label="Google" enabled={providers?.google} />
            <OAuthButton provider="facebook" label="Facebook" enabled={providers?.facebook} />
          </div>
          <div className="my-6 flex items-center gap-3 text-xs text-slate-400"><span className="h-px flex-1 bg-slate-200" />hoặc đăng nhập thường<span className="h-px flex-1 bg-slate-200" /></div>

          <form className="grid gap-4" onSubmit={submit} aria-busy={loading}>
            <div className="grid gap-1.5">
              <Label htmlFor="identifier">Email hoặc tên đăng nhập</Label>
              <Input id="identifier" autoComplete="username" value={identifier} onChange={(event) => setIdentifier(event.target.value)} disabled={loading} required />
            </div>
            <div className="grid gap-1.5">
              <div className="flex justify-between"><Label htmlFor="password">Mật khẩu</Label><Link href="/forgot-password" className="text-xs font-medium text-blue-600 hover:underline">Quên mật khẩu?</Link></div>
              <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={loading} required />
            </div>

            {feedback && (
              <div role={feedback.type === "error" ? "alert" : "status"} aria-live="polite" className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm ${feedback.type === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-red-200 bg-red-50 text-red-700"}`}>
                {feedback.type === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />}
                <span>{feedback.message}</span>
              </div>
            )}

            <Button type="submit" className="h-11" disabled={loading}>{feedback?.type === "success" ? "Đã đăng nhập" : loading ? "Đang đăng nhập..." : "Đăng nhập"}</Button>
          </form>
          <p className="mt-6 text-center text-sm text-slate-500">Chưa có tài khoản? <Link href="/register" className="font-semibold text-blue-600 hover:underline">Đăng ký</Link></p>
        </section>
      </div>
    </main>
  );
}

function OAuthButton({ provider, label, enabled }: { provider: "google" | "facebook"; label: string; enabled?: boolean }) {
  const className = "inline-flex h-11 items-center justify-center rounded-lg border border-slate-200 px-3 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500";
  if (!enabled) {
    return <button type="button" className={`${className} cursor-not-allowed bg-slate-50 text-slate-400`} disabled>{enabled === undefined ? `Đang kiểm tra ${label}...` : `${label} chưa cấu hình`}</button>;
  }
  const oauthPath = `/api/auth/oauth/${provider}/start`;
  return (
    <a
      className={`${className} text-slate-800 hover:bg-slate-50`}
      href={`${API_BASE}${oauthPath}`}
      onClick={(event) => {
        event.preventDefault();
        window.location.assign(`${getApiBase()}${oauthPath}`);
      }}
    >
      Tiếp tục với {label}
    </a>
  );
}
