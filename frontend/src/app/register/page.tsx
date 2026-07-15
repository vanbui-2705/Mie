"use client";

import Link from "next/link";
import { FormEvent, ReactNode, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiFetch, setAuthSession, type AuthUser } from "@/lib/api-client";

type Feedback = { type: "success" | "error"; message: string } | null;

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ full_name: "", username: "", email: "", password: "", confirm: "" });
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFeedback(null);

    if (form.password.length < 8) {
      const message = "Mật khẩu phải có ít nhất 8 ký tự.";
      setFeedback({ type: "error", message });
      toast.error(message);
      return;
    }
    if (form.password !== form.confirm) {
      const message = "Mật khẩu xác nhận không khớp.";
      setFeedback({ type: "error", message });
      toast.error(message);
      return;
    }

    setLoading(true);
    try {
      const result = await apiFetch<{ access_token: string; user: AuthUser }>("/api/auth/register", {
        method: "POST",
        body: form,
      });
      setAuthSession(result.access_token, result.user);
      const message = "Tạo tài khoản thành công. Đang chuyển đến trang quản lý...";
      setFeedback({ type: "success", message });
      toast.success("Tạo tài khoản thành công");
      await new Promise((resolve) => setTimeout(resolve, 900));
      router.replace("/accounts");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Đăng ký thất bại. Vui lòng thử lại.";
      setFeedback({ type: "error", message });
      toast.error(message);
      setLoading(false);
    }
  }

  const disabled = loading || feedback?.type === "success";

  return (
    <AuthPage title="Tạo tài khoản" subtitle="Bắt đầu sử dụng FlowMeta.">
      <form className="grid gap-4" onSubmit={submit} aria-busy={loading}>
        <Field label="Họ và tên" autoComplete="name" value={form.full_name} set={(value) => setForm({ ...form, full_name: value })} disabled={disabled} />
        <Field label="Tên đăng nhập" autoComplete="username" minLength={3} value={form.username} set={(value) => setForm({ ...form, username: value })} disabled={disabled} />
        <Field label="Email" type="email" autoComplete="email" value={form.email} set={(value) => setForm({ ...form, email: value })} disabled={disabled} />
        <Field label="Mật khẩu" type="password" autoComplete="new-password" minLength={8} value={form.password} set={(value) => setForm({ ...form, password: value })} disabled={disabled} />
        <Field label="Xác nhận mật khẩu" type="password" autoComplete="new-password" minLength={8} value={form.confirm} set={(value) => setForm({ ...form, confirm: value })} disabled={disabled} />

        {feedback && (
          <div
            role={feedback.type === "error" ? "alert" : "status"}
            aria-live="polite"
            className={`flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm ${
              feedback.type === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : "border-red-200 bg-red-50 text-red-700"
            }`}
          >
            {feedback.type === "success" && <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />}
            <span>{feedback.message}</span>
          </div>
        )}

        <Button type="submit" className="h-11" disabled={disabled}>
          {feedback?.type === "success" ? "Đã tạo tài khoản" : loading ? "Đang tạo tài khoản..." : "Đăng ký"}
        </Button>
      </form>
      <p className="mt-5 text-center text-sm text-slate-500">
        Đã có tài khoản? <Link className="font-semibold text-blue-600 hover:underline" href="/login">Đăng nhập</Link>
      </p>
    </AuthPage>
  );
}

function Field({ label, value, set, type = "text", autoComplete, minLength, disabled }: {
  label: string;
  value: string;
  set: (value: string) => void;
  type?: string;
  autoComplete?: string;
  minLength?: number;
  disabled?: boolean;
}) {
  const id = label.toLowerCase().replaceAll(" ", "-");
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type={type} autoComplete={autoComplete} minLength={minLength} value={value} onChange={(event) => set(event.target.value)} disabled={disabled} required />
    </div>
  );
}

function AuthPage({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-8">
      <section className="w-full max-w-md rounded-2xl bg-white p-7 shadow-2xl">
        <h1 className="text-2xl font-semibold text-slate-950">{title}</h1>
        <p className="mb-6 mt-1 text-sm text-slate-500">{subtitle}</p>
        {children}
      </section>
    </main>
  );
}
