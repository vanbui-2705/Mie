"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { Globe2, Menu, MessageSquare, Send, Settings, Share2, Users, X } from "lucide-react";
import { useEffect, useState } from "react";

const navItems = [
  { name: "Accounts & Pages", href: "/accounts", icon: Users },
  { name: "Auto Comment", href: "/auto-comment", icon: MessageSquare },
  { name: "Auto Post", href: "/auto-post", icon: Send },
  { name: "Auto Share", href: "/auto-share", icon: Share2 },
  { name: "Proxy", href: "/proxy", icon: Globe2 },
  { name: "Cài đặt", href: "/settings", icon: Settings },
];

export function SideNav() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

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
          <span className="text-white font-bold text-base tracking-tight">FlowMeta</span>
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
          mobileOpen ? "max-h-80 py-2" : "max-h-0 py-0 md:py-4",
        )}
      >
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex min-h-10 items-center gap-3 px-3 py-2 text-[13px] font-medium transition-all duration-100 md:min-h-0 md:py-2.5",
                isActive ? "text-white" : "text-white/60 hover:bg-white/8 hover:text-white"
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
              <Icon className="w-4 h-4" style={{ color: isActive ? "#fff" : "rgba(255,255,255,0.55)" }} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      <div className="hidden p-4 md:block" style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-md flex items-center justify-center text-white font-semibold text-xs"
            style={{ background: "var(--accent)" }}
          >
            OP
          </div>
          <div className="flex flex-col">
            <span className="text-white text-[12px] font-medium">Operator</span>
            <span className="text-[10px]" style={{ color: "rgba(255,255,255,0.45)" }}>
              Multi-user ready
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
