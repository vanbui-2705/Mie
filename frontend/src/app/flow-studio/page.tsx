"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import {
  FLOW_TABS,
  FlowSidebar,
  GenPanel,
  HistoryPanel,
  JobProgress,
  ResultGallery,
  ReupPanel,
  SettingsPanel,
  useSessionHeartbeat,
  type FlowTab,
} from "@/features/flow-studio";
import { describeFlowError, getClipJob, type ClipJob } from "@/lib/flow-api";

function isTab(value: string | null): value is FlowTab {
  return FLOW_TABS.some((tab) => tab.id === value);
}

function FlowStudio() {
  const params = useSearchParams();
  const raw = params.get("tab");
  // The tab lives in React state, not in the router: `router.replace` only
  // swaps the query string and a page loaded straight into `?tab=history`
  // then refuses to move off it. The URL is kept in sync for refresh/linking
  // through the History API, which Next syncs back into useSearchParams.
  const [tab, setTab] = useState<FlowTab>(isTab(raw) ? raw : "reup");

  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [job, setJob] = useState<ClipJob | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);

  // While this page is open the job's files stay; two minutes after it is gone
  // the server deletes them (see backend/app/services/clip_retention.py).
  useSessionHeartbeat([activeJobId]);

  const selectTab = useCallback((next: FlowTab) => {
    setTab(next);
    // Shallow URL update so the tab survives a refresh and can be linked to.
    window.history.replaceState(null, "", next === "reup" ? "/flow-studio" : `/flow-studio?tab=${next}`);
  }, []);

  const startJob = useCallback((jobId: string) => {
    setActiveJobId(jobId);
    setJob(null);
    setJobError(null);
  }, []);

  const openJob = useCallback((jobId: string) => {
    setActiveJobId(jobId);
    setJob(null);
    setJobError(null);
  }, []);

  // A job opened from the history list is usually already finished, so there is
  // nothing to stream — fetch it once and let JobProgress handle the live ones.
  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    getClipJob(activeJobId)
      .then((result) => {
        if (cancelled) return;
        if (result.status !== "QUEUED" && result.status !== "ANALYZING"
          && result.status !== "SCORING" && result.status !== "RENDERING") setJob(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setJobError(describeFlowError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [activeJobId]);

  const isFinished =
    job?.status === "DONE" || job?.status === "ERROR" || job?.status === "CANCELLED";

  const result = activeJobId && tab !== "settings" && (
    <div className="space-y-4">
      {!isFinished && <JobProgress key={activeJobId} jobId={activeJobId} onFinished={setJob} />}
      {jobError && (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          Không mở được job: {jobError}
        </p>
      )}
      {job?.status === "ERROR" && (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {describeFlowError(job.error || "Job lỗi.")}
        </p>
      )}
      {job?.status === "CANCELLED" && (
        <p className="rounded-md bg-foreground/5 px-3 py-2 text-xs text-muted-foreground">
          Job đã dừng vì phiên làm việc bị đóng quá lâu. Tạo lại để chạy tiếp.
        </p>
      )}
      {job?.purged_at && (
        <p className="rounded-md bg-foreground/5 px-3 py-2 text-xs text-muted-foreground">
          File của job này đã được dọn khỏi máy chủ để tiết kiệm dung lượng, không xem lại được.
          Tạo job mới và tải clip về máy trước khi rời trang.
        </p>
      )}
      {job && job.clips.length > 0 && !job.purged_at && (
        <p className="text-xs text-muted-foreground">
          Tải clip về máy trước khi rời trang: file trên máy chủ tự xoá khoảng 2 phút sau khi bạn
          đóng tab.
        </p>
      )}
      {job && job.clips.length > 0 && <ResultGallery clips={job.clips} />}
      {job?.status === "DONE" && job.clips.length === 0 && (
        <p className="text-sm text-muted-foreground">Job xong nhưng không có clip nào.</p>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div>
        <SectionEyebrow label="Flow Studio" />
        <h1 className="font-heading text-xl font-semibold">Flow Studio</h1>
        <p className="text-sm text-muted-foreground">
          Cắt clip từ video có sẵn hoặc sinh video mới từ prompt.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
        <FlowSidebar active={tab} onSelect={selectTab} />

        <div className="space-y-4">
          {/* Opened from the list, the result goes above it — under a 30-row
              history nothing visible happened when you pressed "Mở". */}
          {tab === "history" && result}

          {tab === "reup" && <ReupPanel onJobStarted={startJob} onGoTo={selectTab} />}
          {tab === "gen" && <GenPanel onJobStarted={startJob} />}
          {tab === "history" && <HistoryPanel onOpenJob={openJob} />}
          {tab === "settings" && <SettingsPanel />}

          {tab !== "history" && result}
        </div>
      </div>
    </div>
  );
}

export default function FlowStudioPage() {
  // useSearchParams needs a Suspense boundary during prerender.
  return (
    <Suspense fallback={null}>
      <FlowStudio />
    </Suspense>
  );
}
