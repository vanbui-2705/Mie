"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { setAuthSession, type AuthUser } from "@/lib/api-client";

export default function OAuthCallback() {
  const router = useRouter();

  useEffect(() => {
    const fail = (message: string) => router.replace(`/login?oauth_error=${encodeURIComponent(message)}`);
    const params = new URLSearchParams(window.location.hash.slice(1));
    const token = params.get("token");
    const encoded = params.get("user");
    if (!token || !encoded) {
      fail("Phản hồi đăng nhập OAuth không hợp lệ.");
      return;
    }
    try {
      const normalized = encoded.replace(/-/g, "+").replace(/_/g, "/");
      const user = JSON.parse(atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="))) as AuthUser;
      if (!user.id || !user.username) throw new Error("Invalid OAuth user");
      setAuthSession(token, user);
      window.history.replaceState(null, "", window.location.pathname);
      router.replace("/accounts");
    } catch {
      fail("Không thể hoàn tất đăng nhập OAuth. Vui lòng thử lại.");
    }
  }, [router]);

  return <main className="flex min-h-screen items-center justify-center bg-slate-950 text-sm text-white">Đang hoàn tất đăng nhập...</main>;
}
