"use client";

import { SideNav } from "./SideNav";
import { TopBar } from "./TopBar";
import { usePathname } from "next/navigation";
import { AuthProvider, useAuth } from "@/lib/auth-context";

const PUBLIC_PATHS = new Set(["/login", "/register", "/forgot-password", "/reset-password", "/auth/callback"]);

export function DashboardShell({ children }: { children: React.ReactNode }) {
  return <AuthProvider><AuthenticatedShell>{children}</AuthenticatedShell></AuthProvider>;
}

function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { loading } = useAuth();
  if (PUBLIC_PATHS.has(pathname)) {
    return <>{children}</>;
  }
  if (loading) {
    return <main className="flex min-h-screen items-center justify-center text-sm" style={{ color: "var(--text-sub)" }}>Đang xác thực...</main>;
  }
  return (
    <div className="flex min-h-screen w-full flex-col md:h-screen md:flex-row md:overflow-hidden">
      <SideNav />
      <div className="flex min-h-0 flex-1 flex-col md:overflow-hidden">
        <TopBar />
        <main className="min-h-0 flex-1 p-3 scroll-smooth sm:p-4 md:overflow-auto md:p-5">
          {children}
        </main>
      </div>
    </div>
  );
}
