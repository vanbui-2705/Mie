"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { describeFlowError, getClipJob, type ClipJob } from "@/lib/flow-api";
import { useFlowJobStream } from "./useFlowJobStream";

const LABELS: Record<string, string> = {
  queued: "Đang chờ đến lượt…",
  analyzing: "Đang bóc băng video…",
  scoring: "AI đang chấm điểm và dịch…",
  rendering: "Đang cắt và render…",
  // Gen video reports its own phases through the same stream.
  scripting: "AI đang viết kịch bản…",
  gathering: "Đang thu giọng đọc và hình nền…",
  done: "Hoàn tất",
  error: "Job lỗi",
  cancelled: "Đã dừng (phiên đóng)",
};

const PERCENT: Record<string, number> = {
  queued: 5,
  analyzing: 30,
  scripting: 25,
  scoring: 60,
  gathering: 55,
  rendering: 85,
  done: 100,
  error: 100,
  cancelled: 100,
};

// Where each phase ends, so an in-phase fraction can be interpolated instead of
// leaving the bar frozen for the ten minutes a long job spends in ASR.
const PHASE_END: Record<string, number> = {
  queued: 30,
  analyzing: 60,
  scripting: 55,
  scoring: 85,
  gathering: 85,
  rendering: 100,
};

const TERMINAL: ClipJob["status"][] = ["DONE", "ERROR", "CANCELLED"];

function phaseFromStatus(status: ClipJob["status"]): string {
  const map: Record<string, string> = {
    QUEUED: "queued",
    ANALYZING: "analyzing",
    SCORING: "scoring",
    RENDERING: "rendering",
    DONE: "done",
    ERROR: "error",
    CANCELLED: "cancelled",
  };
  return map[status] ?? "queued";
}

export function JobProgress({ jobId, onFinished }: { jobId: string; onFinished: (job: ClipJob) => void }) {
  const [phase, setPhase] = useState("queued");
  const [progress, setProgress] = useState(0);
  const [readyCount, setReadyCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const finishedRef = useRef(false);

  // The latch closes only after the job actually came back. Closing it first
  // meant one failed fetch (API restarting, network blip) left the card stuck
  // on "Hoàn tất" forever: the parent never got a job, so it never swapped this
  // card for the result gallery, and the poll below skipped every retry.
  const finish = useCallback(async () => {
    if (finishedRef.current) return;
    try {
      const job = await getClipJob(jobId);
      finishedRef.current = true;
      onFinished(job);
    } catch (err) {
      setError(describeFlowError(err));
    }
  }, [jobId, onFinished]);

  const { connected } = useFlowJobStream(jobId, (event) => {
    if (event.type === "phase") {
      setPhase(event.phase);
      setProgress(typeof event.progress === "number" ? event.progress : 0);
    } else if (event.type === "clip_ready") setReadyCount((n) => n + 1);
    else if (event.type === "done") {
      setPhase("done");
      void finish();
    } else {
      setPhase("error");
      setError(describeFlowError(event.error));
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
        // The poll knows the phase, never the fraction inside it.
        setProgress(0);
        if (TERMINAL.includes(job.status)) {
          if (job.error) setError(describeFlowError(job.error));
          if (!finishedRef.current) {
            finishedRef.current = true;
            onFinished(job);
          }
        }
      } catch {
        /* transient — the next tick retries */
      }
    };
    // Tick once right away: if the stream never connects (API down, proxy in
    // the way) the card would otherwise sit on "Đang chờ" for 15s.
    void tick();
    const timer = setInterval(() => void tick(), 15000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId, onFinished]);

  const floor = PERCENT[phase] ?? 5;
  const ceiling = PHASE_END[phase] ?? floor;
  const percent = Math.round(floor + (ceiling - floor) * progress);
  const isError = phase === "error" || phase === "cancelled";

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

        {/* The raw phase names used to be listed here; next to "Hoàn tất" they
            read like the job was still working. Only the real counter stays. */}
        {readyCount > 0 && (
          <p className="text-[11px] text-muted-foreground">{readyCount} clip đã render</p>
        )}

        {error && (
          <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>
        )}
      </CardContent>
    </Card>
  );
}
