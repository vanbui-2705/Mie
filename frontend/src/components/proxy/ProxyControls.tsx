"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { EmptyState } from "@/components/shared/EmptyState";
import type { ProxyKeyState, AppSettings } from "@/types";

type ProxyControlsProps = {
  config: AppSettings;
  onConfigChange: (patch: Partial<AppSettings>) => void;
  onSave: () => void;
  saving: boolean;
  running: boolean;
  onStart: () => void;
  onStop: () => void;
  onDelete: () => void;
  deleting: boolean;
};

export function ProxyControls({
  config,
  onConfigChange,
  onSave,
  saving,
  running,
  onStart,
  onStop,
  onDelete,
  deleting,
}: ProxyControlsProps) {
  return (
    <div
      className="rounded-lg border"
      style={{ backgroundColor: "var(--card)", borderColor: "var(--border)" }}
    >
      <div className="p-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                Token Kiot
              </Label>
              <Input
                type="password"
                value={config.kiotAuthToken}
                onChange={(e) => onConfigChange({ kiotAuthToken: e.target.value })}
                className="h-8 text-[9pt]"
                disabled={running}
                placeholder="Nhập token KiotProxy..."
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                API key proxy (mỗi dòng 1 key)
              </Label>
              <Textarea
                value={config.proxyApiKeys}
                onChange={(e) => onConfigChange({ proxyApiKeys: e.target.value })}
                rows={4}
                className="text-[9pt]"
                disabled={running}
                placeholder="Mỗi dòng 1 key"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                Lượt mỗi IP
              </Label>
              <Input
                type="number"
                value={config.usesPerProxy}
                onChange={(e) => onConfigChange({ usesPerProxy: parseInt(e.target.value) || 1 })}
                className="h-8 w-24 text-[9pt]"
                disabled={running}
                min={1}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                Kiểm tra mỗi (giây)
              </Label>
              <Input
                type="number"
                value={config.checkInterval}
                onChange={(e) => onConfigChange({ checkInterval: parseInt(e.target.value) || 5 })}
                className="h-8 w-24 text-[9pt]"
                disabled={running}
                min={5}
              />
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
              URL lấy IP mới
            </Label>
            <Input
              value={config.getNewProxyUrl}
              onChange={(e) => onConfigChange({ getNewProxyUrl: e.target.value })}
              className="h-8 text-[9pt]"
              style={{ fontFamily: "var(--font-mono)" }}
              disabled={running}
            />
            <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
              URL IP hiện tại
            </Label>
            <Input
              value={config.getCurrentProxyUrl}
              onChange={(e) => onConfigChange({ getCurrentProxyUrl: e.target.value })}
              className="h-8 text-[9pt]"
              style={{ fontFamily: "var(--font-mono)" }}
              disabled={running}
            />
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button
                onClick={onSave}
                disabled={saving}
                className="h-8 flex-1 px-4 text-[9pt] text-white sm:flex-none"
                style={{ backgroundColor: "var(--accent)" }}
              >
                {saving ? "Đang lưu..." : "Lưu cấu hình"}
              </Button>
              <Button
                onClick={running ? onStop : onStart}
                className="h-8 flex-1 px-4 text-[9pt] text-white sm:flex-none"
                style={{ backgroundColor: running ? "var(--danger)" : "var(--success)" }}
              >
                {running ? "Dừng" : "Bắt đầu"}
              </Button>
              <Button
                onClick={onDelete}
                disabled={deleting || running}
                variant="ghost"
                className="h-8 flex-1 px-3 text-[9pt] sm:flex-none"
                style={{ color: "var(--danger)" }}
              >
                Xóa tất cả
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
