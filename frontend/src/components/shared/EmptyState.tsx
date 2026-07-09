"use client";

import { LucideIcon } from "lucide-react";

type EmptyStateProps = {
  message: string;
  icon?: LucideIcon;
};

export function EmptyState({ message, icon: Icon }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16">
      {Icon && <Icon className="w-8 h-8" style={{ color: "var(--muted-foreground)", opacity: 0.5 }} strokeWidth={1.5} />}
      <p className="text-sm italic" style={{ color: "var(--muted-foreground)" }}>{message}</p>
    </div>
  );
}
