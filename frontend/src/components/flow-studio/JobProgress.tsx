"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { getClipJob, type ClipJob } from "@/lib/flow-api";
import { useFlowJobStream } from "./useFlowJobStream";

const PHASES = ["queued", "analyzing", "scoring", "rendering", "done"] as const;

const LABELS: Record<string, string> = {
  queued: "Đang chờ đến lượt…",
  analyzing: "Đang bóc băng video…",
  scoring: "AI đang chấm điểm và dịch…",
  rendering: "Đang cắt và render…",
  done: "Hoàn tất",
  error: "Job lỗi",
};

const PERCENT: Record<string, number> = {
  queued: 5,
  analyzing: 30,
  scoring: 60,
  rendering: 85,
  done: 100,
  error: 100,
};

function phaseFromStatus(status: ClipJob["status"]): string {
  const map: Record<string, string> = {
    QUEUED: "queued",
    ANALYZING: "analyzing",
    SCORING: "scoring",
    RENDERING: "rendering",
    DONE: "done",
    ERROR: "error",
  };
  return map[status] ?? "queued";
}

export function JobProgress({ jobId, onFinished }: { jobId: string; onFinished: (job: ClipJob) => void }) {
  const [phase, setPhase] = useState("queued");
  const [readyCount, setReadyCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const finishedRef = useRef(false);

  const finish = useCallback(async () => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    try {
      onFinished(await getClipJob(jobId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không tải được kết quả");
    }
  }, [jobId, onFinished]);

  const { connected } = useFlowJobStream(jobId, (event) => {
    if (event.type === "phase") setPhase(event.phase);
    else if (event.type === "clip_ready") setReadyCount((n) => n + 1);
    else if (event.type === "done") {
      setPhase("done");
      void finish();
    } else {
      setPhase("error");
      setError(event.error);
      void finish();
    }
  });

  // A reconnect can land after the terminal event was published, and the bus
  // does not replay it — so poll the job as well and stop when it settles.
  // The parent mounts this with key={jobId}, so a new job gets fresh state and
  // this effect only has to own the timer.
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      if (cancelled || finishedRef.current) return;
      try {
        const job = await getClipJob(jobId);
        if (cancelled) return;
        setPhase(phaseFromStatus(job.status));
        if (job.status === "DONE" || job.status === "ERROR") {
          if (job.error) setError(job.error);
          if (!finishedRef.current) {
            finishedRef.current = true;
            onFinished(job);
          }
        }
      } catch {
        /* transient — the next tick retries */
      }
    };
    const timer = setInterval(() => void tick(), 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId, onFinished]);

  const percent = PERCENT[phase] ?? 5;
  const isError = phase === "error";

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium">{LABELS[phase] ?? "Đang xử lý…"}</span>
          <span className="text-xs text-muted-foreground">
            {connected ? "" : "mất kết nối realtime · "}
            {percent}%
          </span>
        </div>

        <div className="h-2 w-full overflow-hidden rounded-full bg-foreground/10">
          <div
            className={`h-full transition-[width] duration-500 ${isError ? "bg-destructive" : "bg-primary"}`}
            style={{ width: `${percent}%` }}
          />
        </div>

        <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          {PHASES.map((p) => (
            <span key={p} className={p === phase ? "text-foreground" : undefined}>
              {p}
            </span>
          ))}
          {readyCount > 0 && <span>· {readyCount} clip đã render</span>}
        </div>

        {error && (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>
        )}
      </CardContent>
    </Card>
  );
}
