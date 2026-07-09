"use client";

import { useHealthCheck } from "@/lib/sse-client";
import { usePathname } from "next/navigation";

const sectionLabels: Record<string, string> = {
  "/accounts": "Quản lý hồ sơ",
  "/auto-comment": "Tương tác tự động",
  "/proxy": "Quản lý Proxy",
  "/settings": "Cài đặt",
};

export function TopBar() {
  const pathname = usePathname();
  const { status } = useHealthCheck({ interval: 30000 });
  const label = sectionLabels[pathname] ?? "FlowMeta";

  const statusColor =
    status === "online"
      ? "var(--success)"
      : status === "checking"
        ? "var(--warning)"
        : "var(--danger)";
  const statusLabel =
    status === "online" ? "Online" : status === "checking" ? "Đang kiểm tra..." : "Offline";

  return (
    <header
      className="sticky top-0 z-10 flex h-12 shrink-0 items-center justify-between gap-3 px-3 sm:px-4 md:h-14 md:px-6"
      style={{
        backgroundColor: "var(--panel)",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div className="min-w-0">
        <span className="text-[9pt] font-medium" style={{ color: "var(--text-sub)" }}>
          {label}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: statusColor }}
        />
        <span className="text-[9pt] font-medium" style={{ color: statusColor }}>
          {statusLabel}
        </span>
      </div>
    </header>
  );
}
