"use client";

import { Button } from "@/components/ui/button";
import { clearAuthSession } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { useHealthCheck } from "@/lib/sse-client";
import { LogOut, UserRound } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

const sectionLabels: Record<string, string> = {
  "/accounts": "Quản lý Facebook",
  "/auto-comment": "Auto Comment",
  "/auto-post": "Auto Post Facebook",
  "/auto-share": "Auto Share Facebook",
  "/scheduled-posts": "Lịch đăng bài",
  "/proxy": "Quản lý Proxy",
  "/users": "Quản lý người dùng",
  "/settings": "Cài đặt",
};

export function TopBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { status } = useHealthCheck({ interval: 30000 });
  const { user } = useAuth();
  const label = sectionLabels[pathname] ?? "FlowMeta";

  const statusColor =
    status === "online"
      ? "var(--success)"
      : status === "checking"
        ? "var(--warning)"
        : "var(--danger)";
  const statusLabel = status === "online" ? "Trực tuyến" : status === "checking" ? "Đang kiểm tra..." : "Ngoại tuyến";

  function handleLogout() {
    clearAuthSession();
    router.push("/login");
  }

  return (
    <header
      className="sticky top-0 z-10 flex h-12 shrink-0 items-center justify-between gap-3 px-3 sm:px-4 md:h-14 md:px-6"
      style={{
        backgroundColor: "var(--panel)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div className="min-w-0">
        <span className="truncate text-[9pt] font-medium" style={{ color: "var(--text-sub)" }}>
          {label}
        </span>
      </div>
      <div className="flex min-w-0 shrink-0 items-center gap-2">
        <div className="hidden items-center gap-1.5 rounded-md border px-2 py-1 sm:flex" style={{ borderColor: "var(--border)" }}>
          <UserRound className="h-3.5 w-3.5" style={{ color: "var(--text-sub)" }} />
          <span className="max-w-36 truncate text-[9pt] font-medium" style={{ color: "var(--text-main)" }}>
            {user?.username ?? "guest"}
          </span>
          {user?.role && (
            <span className="text-[8pt]" style={{ color: "var(--text-sub)" }}>
              {user.role}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: statusColor }} />
          <span className="hidden text-[9pt] font-medium sm:inline" style={{ color: statusColor }}>
            {statusLabel}
          </span>
        </div>
        <Button type="button" variant="outline" size="icon-sm" onClick={handleLogout} title="Đăng xuất">
          <LogOut className="h-3.5 w-3.5" />
        </Button>
      </div>
    </header>
  );
}
