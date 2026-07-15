"use client";

import { useEffect } from "react";
import { getAuthToken } from "@/lib/api-client";

export default function RootPage() {
  useEffect(() => {
    window.location.replace(getAuthToken() ? "/accounts" : "/login");
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center text-sm" style={{ color: "var(--text-sub)" }}>
      Đang chuyển trang...
    </main>
  );
}
