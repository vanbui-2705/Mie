"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Building2, CalendarClock, Clapperboard, FileSpreadsheet, Globe2, ListChecks, Menu, MessageSquare, Send, Settings, Share2, UserCog, Users, X } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/lib/auth-context";

const navItems = [
  { name: "Accounts & Pages", href: "/accounts", icon: Users, permission: "facebook_account:read" },
  { name: "Auto Comment", href: "/auto-comment", icon: MessageSquare, permission: "task:create" },
  { name: "Auto Post", href: "/auto-post", icon: Send, permission: "facebook_page:post" },
  { name: "Lịch đăng", href: "/scheduled-posts", icon: CalendarClock, permission: "scheduled_post:read" },
  { name: "Nguồn Sheets", href: "/google-sheets", icon: FileSpreadsheet, permission: "google_sheet:read" },
  { name: "Chiến dịch Sheets", href: "/sheet-campaigns", icon: ListChecks, permission: "google_sheet:read" },
  { name: "Đăng trọ tự động", href: "/tro", icon: Building2, permission: "rental:read" },
  { name: "Auto Share", href: "/auto-share", icon: Share2, permission: "facebook_group:share" },
  { name: "Flow Studio", href: "/flow-studio", icon: Clapperboard, permission: "clip:create" },
  { name: "Proxy", href: "/proxy", icon: Globe2, permission: "proxy:read" },
  { name: "Users", href: "/users", icon: UserCog, permission: "user:read" },
  { name: "Cài đặt", href: "/settings", icon: Settings, permission: "settings:read" },
];

export function SideNav() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { can, user } = useAuth();

  return (
    <aside
      className="z-20 flex w-full shrink-0 flex-col border-b md:h-screen md:w-[var(--sidebar-width,250px)] md:border-b-0 md:border-r"
      style={{
        backgroundColor: "var(--surface-dark)",
        borderColor: "rgba(255,255,255,0.08)",
      }}
    >
      <div
        className="flex h-12 shrink-0 items-center justify-between px-4 md:h-14 md:px-6"
        style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}
      >
        <div className="flex flex-col">
          <span className="text-base font-bold tracking-tight text-white">FlowMeta</span>
          <span className="text-[10px] font-medium" style={{ color: "var(--accent)" }}>
            Automation Console
          </span>
        </div>
        <button
          type="button"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border text-white/80 transition hover:bg-white/10 hover:text-white md:hidden"
          style={{ borderColor: "rgba(255,255,255,0.14)" }}
          onClick={() => setMobileOpen((open) => !open)}
          aria-label={mobileOpen ? "Đóng menu" : "Mở menu"}
          aria-expanded={mobileOpen}
        >
          {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
        </button>
      </div>

      <nav
        className={cn(
          "grid gap-1 overflow-hidden px-2 transition-[max-height,padding] duration-150 md:block md:max-h-none md:flex-1 md:overflow-visible md:px-3 md:py-4 md:[&>*+*]:mt-1",
          mobileOpen ? "max-h-[420px] py-2" : "max-h-0 py-0 md:py-4",
        )}
      >
        {navItems.filter((item) => can(item.permission)).map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              className={cn(
                "flex min-h-10 items-center gap-3 px-3 py-2 text-[13px] font-medium transition-all duration-100 md:min-h-0 md:py-2.5",
                isActive ? "text-white" : "text-white/60 hover:bg-white/8 hover:text-white",
              )}
              style={
                isActive
                  ? {
                      backgroundColor: "rgba(255,255,255,0.08)",
                      borderLeft: "3px solid var(--accent)",
                      borderRadius: "0 6px 6px 0",
                    }
                  : {
                      borderLeft: "3px solid transparent",
                      borderRadius: "0 6px 6px 0",
                    }
              }
            >
              <Icon className="h-4 w-4" style={{ color: isActive ? "#fff" : "rgba(255,255,255,0.55)" }} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className="hidden p-4 md:block" style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="flex items-center gap-3">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-md text-xs font-semibold text-white"
            style={{ background: "var(--accent)" }}
          >
            {(user?.username || "U").slice(0, 2).toUpperCase()}
          </div>
          <div className="flex flex-col">
            <span className="text-[12px] font-medium text-white">{user?.username || "User"}</span>
            <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.45)" }}>
              {user?.roles?.join(", ") || user?.role || "user"}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
