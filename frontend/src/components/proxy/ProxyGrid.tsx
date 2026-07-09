"use client";

import { useState } from "react";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { EmptyState } from "@/components/shared/EmptyState";
import type { ProxyKeyState } from "@/types";

type ProxyGridProps = {
  keys: ProxyKeyState[];
};

const statusLabelMap: Record<string, string> = {
  ready: "Sẵn sàng",
  starting: "Đang khởi động",
  waiting: "Đang chờ",
  error: "Lỗi",
  "Đang chạy": "Đang chạy",
};

export function ProxyGrid({ keys }: ProxyGridProps) {
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);

  return (
    <div className="overflow-x-auto rounded-md border" style={{ borderColor: "var(--border)" }}>
      <table className="w-full text-[9pt]" style={{ borderCollapse: "collapse", minWidth: 760 }}>
        <thead>
          <tr
            style={{
              height: 32,
              backgroundColor: "var(--surface-dark)",
              color: "var(--surface-dark-fg)",
            }}
          >
            <th className="text-center font-semibold whitespace-nowrap px-2" style={{ width: 50 }}>
              STT
            </th>
            <th className="font-semibold whitespace-nowrap px-2" style={{ minWidth: 200 }}>
              Key
            </th>
            <th className="font-semibold whitespace-nowrap px-2" style={{ minWidth: 200 }}>
              Proxy
            </th>
            <th className="text-center font-semibold whitespace-nowrap px-2" style={{ width: 100 }}>
              Remaining
            </th>
            <th className="font-semibold whitespace-nowrap px-2" style={{ width: 130 }}>
              Trạng thái
            </th>
            <th className="font-semibold px-2" style={{ minWidth: 180 }}>
              Lỗi
            </th>
          </tr>
        </thead>
        <tbody>
          {keys.length === 0 ? (
            <tr>
              <td colSpan={6}>
                <EmptyState message="Chưa có proxy nào được cấu hình." />
              </td>
            </tr>
          ) : (
            keys.map((row, idx) => {
              const isEven = idx % 2 === 0;
              const bgColor = isEven ? "var(--card)" : "var(--surface-row)";
              const isHovered = hoveredRow === row.maskedApiKey;
              const statusLabel = statusLabelMap[row.status] ?? row.status;

              return (
                <tr
                  key={row.maskedApiKey + row.id}
                  style={{
                    height: 28,
                    backgroundColor: isHovered ? "var(--surface-row)" : bgColor,
                    borderBottom: "1px solid var(--divider)",
                    cursor: "default",
                  }}
                  onMouseEnter={() => setHoveredRow(row.maskedApiKey)}
                  onMouseLeave={() => setHoveredRow(null)}
                >
                  <td
                    className="text-center whitespace-nowrap px-2"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    {idx + 1}
                  </td>
                  <td
                    className="px-2 font-mono whitespace-nowrap"
                    style={{ fontFamily: "var(--font-mono)", fontSize: "9.5pt" }}
                  >
                    {row.maskedApiKey}
                  </td>
                  <td
                    className="px-2 font-mono"
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "9.5pt",
                      color: row.display ? "var(--foreground)" : "var(--muted-foreground)",
                      maxWidth: 200,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={row.display ?? ""}
                  >
                    {row.display || "—"}
                  </td>
                  <td
                    className="text-center whitespace-nowrap px-2 font-mono"
                    style={{ fontFamily: "var(--font-mono)", fontSize: "9.5pt" }}
                  >
                    {row.remainingUses}
                  </td>
                  <td className="px-2">
                    <StatusBadge status={statusLabel} />
                  </td>
                  <td
                    className="px-2"
                    style={{
                      maxWidth: 200,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      color: "var(--danger)",
                    }}
                    title={row.lastError ?? ""}
                  >
                    {row.lastError || "—"}
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
