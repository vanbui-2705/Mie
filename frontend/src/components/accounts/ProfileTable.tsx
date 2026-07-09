"use client";

import { useState, useMemo } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { EmptyState } from "@/components/shared/EmptyState";
import { ProfileRow, maskToken, statusToVariant } from "@/types";

type ProfileTableProps = {
  profiles: ProfileRow[];
  selectedUids: Set<string>;
  onSelectionChange: (uids: Set<string>) => void;
};

export function ProfileTable({ profiles, selectedUids, onSelectionChange }: ProfileTableProps) {
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);

  const allChecked = profiles.length > 0 && selectedUids.size === profiles.length;
  const someChecked = selectedUids.size > 0 && !allChecked;

  const handleHeaderCheck = (checked: boolean) => {
    if (checked) {
      onSelectionChange(new Set(profiles.map((p) => p.uid)));
    } else {
      onSelectionChange(new Set());
    }
  };

  const handleRowCheck = (uid: string, checked: boolean) => {
    const next = new Set(selectedUids);
    if (checked) {
      next.add(uid);
    } else {
      next.delete(uid);
    }
    onSelectionChange(next);
  };

  const loading = profiles.length === 0;
  const error = null;

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-12">
        <p className="text-sm font-medium text-danger">{error}</p>
        <button className="btn-frost-primary h-8 px-4 rounded-md text-white text-xs font-medium"
          style={{ backgroundColor: "var(--accent)" }}>
          Thử lại
        </button>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border" style={{ borderColor: "var(--border)" }}>
      <table className="w-full text-[9pt]" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ height: 32, backgroundColor: "var(--surface-dark)", color: "var(--surface-dark-fg)" }}>
            <th className="text-center font-semibold whitespace-nowrap" style={{ width: 44, padding: "0 8px" }}>
              <Checkbox
                checked={allChecked}
                indeterminate={someChecked}
                onCheckedChange={(v) => handleHeaderCheck(Boolean(v))}
              />
            </th>
            <th className="text-center font-semibold whitespace-nowrap" style={{ width: 50 }}>STT</th>
            <th className="font-semibold whitespace-nowrap" style={{ minWidth: 150 }}>UID</th>
            <th className="font-semibold whitespace-nowrap" style={{ minWidth: 180 }}>Token</th>
            <th className="font-semibold whitespace-nowrap" style={{ width: 140 }}>Trạng thái</th>
            <th className="text-center font-semibold whitespace-nowrap" style={{ width: 70 }}>Tác vụ</th>
            <th className="font-semibold" style={{ minWidth: 200 }}>Lỗi gần nhất</th>
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: 5 }).map((_, i) => (
                <tr key={`skel-${i}`} style={{ height: 28 }}>
                  <td colSpan={7}>
                    <div className="skeleton-row w-full" />
                  </td>
                </tr>
              ))
            : profiles.length === 0
              ? (
                <tr>
                  <td colSpan={7}>
                    <EmptyState message="Nhấn chuột phải → Nhập dữ liệu để bắt đầu" />
                  </td>
                </tr>
              )
              : profiles.map((row, idx) => {
                  const isEven = idx % 2 === 0;
                  const isHovered = hoveredRow === row.uid;
                  return (
                    <tr
                      key={row.uid}
                      className="frost-table-row-hover"
                      style={{
                        height: 28,
                        backgroundColor: isEven ? "var(--card)" : "var(--surface-row)",
                        ...(isHovered ? { backgroundColor: "var(--surface-row)" } : {}),
                        borderBottom: "1px solid var(--divider)",
                      }}
                      onMouseEnter={() => setHoveredRow(row.uid)}
                      onMouseLeave={() => setHoveredRow(null)}
                    >
                      <td className="text-center whitespace-nowrap" style={{ padding: "0 8px" }}>
                        <Checkbox
                          checked={selectedUids.has(row.uid)}
                          onCheckedChange={(v) => handleRowCheck(row.uid, Boolean(v))}
                        />
                      </td>
                      <td className="text-center whitespace-nowrap" style={{ padding: "0 8px", color: "var(--muted-foreground)" }}>
                        {idx + 1}
                      </td>
                      <td className="whitespace-nowrap font-mono" style={{ padding: "0 8px", fontFamily: "var(--font-mono)", fontSize: "9.5pt", color: "var(--foreground)" }}>
                        {row.uid}
                      </td>
                      <td className="token-mask" style={{ padding: "0 8px" }}>
                        {maskToken(row.token)}
                      </td>
                      <td style={{ padding: "0 8px" }}>
                        <StatusBadge status={row.tokenStatus} />
                      </td>
                      <td className="text-center whitespace-nowrap" style={{ padding: "0 8px", color: "var(--foreground)" }}>
                        {row.taskCount}
                      </td>
                      <td
                        className="whitespace-normal"
                        style={{ padding: "0 8px", color: statusToVariant(row.tokenStatus) === "danger" ? "var(--danger)" : "var(--muted-foreground)", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}
                        title={row.lastError ?? undefined}
                      >
                        {row.lastError ?? "—"}
                      </td>
                    </tr>
                  );
                })}
        </tbody>
      </table>
      {profiles.length > 0 && (
        <div
          className="flex items-center justify-between text-[9pt]"
          style={{
            padding: "6px 16px",
            borderTop: "1px solid var(--divider)",
            backgroundColor: "color-mix(in srgb, var(--surface-row) 30%, transparent)",
            color: "var(--muted-foreground)",
          }}
        >
          <span>Tổng: {profiles.length}</span>
          <span>Tích chọn: {selectedUids.size}</span>
          <span>Hoạt động: {profiles.filter((p) => p.tokenStatus === "live").length}/{profiles.length}</span>
        </div>
      )}
    </div>
  );
}
