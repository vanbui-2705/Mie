"use client";

import { cn } from "@/lib/utils";
import { History, Scissors, Settings, Sparkles } from "lucide-react";

export type FlowTab = "reup" | "gen" | "history" | "settings";

export const FLOW_TABS: { id: FlowTab; label: string; hint: string; icon: typeof Scissors }[] = [
  { id: "reup", label: "Reup / Edit video", hint: "Cắt clip từ video có sẵn", icon: Scissors },
  { id: "gen", label: "Gen video", hint: "Tạo video từ prompt", icon: Sparkles },
  { id: "history", label: "Lịch sử", hint: "Job đã chạy", icon: History },
  { id: "settings", label: "Cài đặt", hint: "Tham số xử lý", icon: Settings },
];

export function FlowSidebar({ active, onSelect }: { active: FlowTab; onSelect: (tab: FlowTab) => void }) {
  return (
    <nav className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible" aria-label="Flow Studio">
      {FLOW_TABS.map((tab) => {
        const Icon = tab.icon;
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => onSelect(tab.id)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[13px] transition-colors",
              isActive ? "bg-foreground/10 text-foreground" : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="flex flex-col">
              <span className="font-medium">{tab.label}</span>
              <span className="hidden text-[11px] text-muted-foreground lg:block">{tab.hint}</span>
            </span>
          </button>
        );
      })}
    </nav>
  );
}
