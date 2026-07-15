"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { TableBody, TableCell, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { EmptyState } from "@/components/shared/EmptyState";
import type { LogEntry, LogLevel } from "@/types";
import { logLevelFromStatus, taskStatusLabel } from "@/types";

type LogConsoleProps = {
  logs: LogEntry[];
  running: boolean;
};

const logRowClass: Record<LogLevel, string> = {
  info: "log-row--info",
  success: "log-row--success",
  warning: "log-row--warning",
  error: "log-row--error",
};

export function LogConsole({ logs, running }: LogConsoleProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (autoScroll && scrollRef.current && running) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, running, autoScroll]);

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  }, []);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[9pt] font-semibold" style={{ color: "var(--muted-foreground)" }}>Nhật ký</span>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setAutoScroll(!autoScroll)}>
          {autoScroll
            ? <span className="text-[8pt]" style={{ color: "var(--muted-foreground)" }}>Tự cuộn</span>
            : <span className="text-[8pt]" style={{ color: "var(--muted-foreground)" }}>Dừng cuộn</span>}
        </Button>
      </div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="overflow-auto rounded-md border"
        style={{ height: 340, borderColor: "var(--border)", backgroundColor: "var(--card)" }}
      >
        {logs.length === 0 ? (
          <EmptyState message="Nhật ký trống..." />
        ) : (
          <table className="w-full text-[9pt]" style={{ borderCollapse: "collapse", minWidth: 720 }}>
            <thead>
              <tr style={{ height: 32, backgroundColor: "var(--surface-dark)", color: "var(--surface-dark-fg)" }}>
                <th className="text-center font-semibold whitespace-nowrap px-2" style={{ width: 50 }}>STT</th>
                <th className="font-semibold whitespace-nowrap px-2" style={{ minWidth: 130 }}>UID</th>
                <th className="font-semibold px-2" style={{ minWidth: 200 }}>Link</th>
                <th className="font-semibold whitespace-nowrap px-2" style={{ width: 90 }}>Hành động</th>
                <th className="font-semibold whitespace-nowrap px-2" style={{ width: 140 }}>Proxy</th>
                <th className="font-semibold whitespace-nowrap px-2" style={{ width: 120 }}>Trạng thái</th>
                <th className="font-semibold px-2">Lỗi</th>
              </tr>
            </thead>
            <TableBody>
              {logs.map((entry) => {
                const level = logLevelFromStatus(entry.status) as LogLevel;
                return (
                  <TableRow key={entry.index} className={logRowClass[level]}>
                    <TableCell className="text-center whitespace-nowrap px-2" style={{ color: "var(--muted-foreground)" }}>{entry.index}</TableCell>
                    <TableCell className="whitespace-nowrap px-2" style={{ fontFamily: "var(--font-mono)", fontSize: "9.5pt" }}>{entry.uid}</TableCell>
                    <TableCell className="px-2 truncate" style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={entry.link}>{entry.link}</TableCell>
                    <TableCell className="whitespace-nowrap px-2">{entry.action}</TableCell>
                    <TableCell className="whitespace-nowrap px-2" style={{ fontFamily: "var(--font-mono)", fontSize: "9.5pt", color: "var(--muted-foreground)" }}>{entry.proxy}</TableCell>
                    <TableCell className="px-2"><StatusBadge status={taskStatusLabel(entry.status)} className="text-[8pt]" /></TableCell>
                    <TableCell className="px-2 truncate" style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: level === "error" ? "var(--danger)" : level === "warning" ? "var(--warning)" : "var(--muted-foreground)" }} title={entry.error}>{entry.error}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </table>
        )}
      </div>
    </div>
  );
}
