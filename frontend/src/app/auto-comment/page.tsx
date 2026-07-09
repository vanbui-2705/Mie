"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { TaskConfigForm } from "@/components/auto-comment/TaskConfigForm";
import { LogConsole } from "@/components/auto-comment/LogConsole";
import { StatsBar } from "@/components/auto-comment/StatsBar";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { toast } from "sonner";
import type { LogEntry, TaskStats, TaskConfig } from "@/types";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const DONE_STATUSES = new Set(["success", "failed", "canceled", "done", "error", "stopped"]);

export default function AutoCommentPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [stats, setStats] = useState<TaskStats | null>(null);
  const [running, setRunning] = useState(false);
  const [connected, setConnected] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setRunning(false);
    setConnected(false);
  }, []);

  const refreshTask = useCallback(async (id: string) => {
    const [taskRes, logsRes] = await Promise.all([
      fetch(`${API_BASE}/api/tasks/${id}`),
      fetch(`${API_BASE}/api/tasks/${id}/logs`),
    ]);
    if (!taskRes.ok) throw new Error(`Task HTTP ${taskRes.status}`);
    if (!logsRes.ok) throw new Error(`Logs HTTP ${logsRes.status}`);

    const task = await taskRes.json() as Record<string, unknown>;
    const rawLogs = await logsRes.json() as Array<Record<string, unknown>>;
    setStats({
      total: Number(task.total ?? 0),
      processed: Number(task.processed ?? 0),
      success: Number(task.success ?? 0),
      failed: Number(task.failed ?? 0),
      waitingProxy: Number(task.waiting_proxy ?? task.waitingProxy ?? 0),
    });
    setLogs(rawLogs.map((raw) => ({
      index: Number(raw.log_index ?? raw.id ?? 0),
      uid: String(raw.uid ?? ""),
      link: String(raw.comment_link ?? ""),
      action: String(raw.action ?? ""),
      proxy: String(raw.proxy ?? ""),
      status: String(raw.status ?? ""),
      error: String(raw.error ?? ""),
      timestamp: raw.created_at ? new Date(String(raw.created_at)).getTime() : Date.now(),
    })));

    const status = String(task.status ?? "");
    if (DONE_STATUSES.has(status)) {
      stopPolling();
      setTaskId(null);
    }
  }, [stopPolling]);

  const handleStart = useCallback(async (config: TaskConfig) => {
    setLogs([]);
    setStats(null);
    setTaskId(null);
    stopPolling();

    try {
      const res = await fetch(`${API_BASE}/api/comment-tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: config.action,
          raw_uid_text: config.uids,
          raw_link_text: config.links,
          raw_post_text: config.action === "new_comment" ? config.links : "",
          max_threads: config.threads,
          new_text_input: config.content,
          image_input: config.imagePath,
          delay: {
            min_seconds: config.delayMin,
            max_seconds: config.delayMax,
            every_rounds: config.delayEveryRounds,
          },
        }),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `HTTP ${res.status}`);
      }

      const data = await res.json() as { task_id?: string; total?: number };
      if (!data.task_id) throw new Error("Backend did not return task_id");

      setTaskId(data.task_id);
      setRunning(true);
      setConnected(true);
      setStats({
        total: Number(data.total ?? 0),
        processed: 0,
        success: 0,
        failed: 0,
        waitingProxy: 0,
      });
      toast.success("Đã đưa tác vụ vào hàng đợi worker");

      await refreshTask(data.task_id);
      pollRef.current = window.setInterval(() => {
        void refreshTask(data.task_id as string).catch(() => setConnected(false));
      }, 1500);
    } catch (e) {
      if (e instanceof Error) toast.error(e.message);
      stopPolling();
    }
  }, [refreshTask, stopPolling]);

  const handleStop = useCallback(async () => {
    const currentTaskId = taskId;
    try {
      if (currentTaskId) {
        await fetch(`${API_BASE}/api/tasks/${currentTaskId}/cancel`, { method: "POST" });
      } else {
        await fetch(`${API_BASE}/api/tasks/stop`, { method: "POST" });
      }
    } catch {
      // Ignore cancel errors; the next poll or page refresh will show persisted state.
    } finally {
      setTaskId(null);
      stopPolling();
    }
  }, [taskId, stopPolling]);

  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>
          Tương tác tự động
        </h1>
        <p className="text-[9pt] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
          Chỉnh sửa / xóa / tạo comment qua queue worker production
        </p>
      </div>

      {running && (
        <div
          className="flex items-center gap-2 px-3 py-1.5 rounded text-[9pt] w-fit"
          style={{
            backgroundColor: connected ? "var(--success-soft)" : "var(--warning-soft)",
            color: connected ? "var(--success-fg-on-soft)" : "var(--warning-fg-on-soft)",
          }}
        >
          <span
            className="h-2 w-2 rounded-full"
            style={{
              backgroundColor: connected ? "var(--success)" : "var(--warning)",
              animation: connected ? "pulse 2s cubic-bezier(0.4,0,0.6,1) infinite" : "none",
            }}
          />
          {connected ? "Đang đọc log từ worker..." : "Đang kết nối lại..."}
        </div>
      )}

      <SectionEyebrow label="Cấu hình tác vụ" />
      <TaskConfigForm onStart={handleStart} onStop={handleStop} running={running} />

      {stats && <StatsBar stats={stats} />}
      <SectionEyebrow label="Nhật ký" />
      <LogConsole logs={logs} running={running} />
    </div>
  );
}
