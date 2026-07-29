"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { FlowSidebar, FLOW_TABS, type FlowTab } from "@/components/flow-studio/FlowSidebar";
import { ReupPanel } from "@/components/flow-studio/ReupPanel";
import { GenPanel } from "@/components/flow-studio/GenPanel";
import { HistoryPanel } from "@/components/flow-studio/HistoryPanel";
import { SettingsPanel } from "@/components/flow-studio/SettingsPanel";
import { JobProgress } from "@/components/flow-studio/JobProgress";
import { ResultGallery } from "@/components/flow-studio/ResultGallery";
import { getClipJob, type ClipJob } from "@/lib/flow-api";

function isTab(value: string | null): value is FlowTab {
  return FLOW_TABS.some((tab) => tab.id === value);
}

function FlowStudio() {
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: FlowTab = isTab(raw) ? raw : "reup";

  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [job, setJob] = useState<ClipJob | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);

  const selectTab = useCallback(
    (next: FlowTab) => {
      // Shallow URL update so the tab survives a refresh and can be linked to.
      router.replace(next === "reup" ? "/flow-studio" : `/flow-studio?tab=${next}`, { scroll: false });
    },
    [router],
  );

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
        if (result.status === "DONE" || result.status === "ERROR") setJob(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setJobError(err instanceof Error ? err.message : "Không tải được job.");
      });
    return () => {
      cancelled = true;
    };
  }, [activeJobId]);

  const isFinished = job?.status === "DONE" || job?.status === "ERROR";

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
          {tab === "reup" && <ReupPanel onJobStarted={startJob} onGoTo={selectTab} />}
          {tab === "gen" && <GenPanel />}
          {tab === "history" && <HistoryPanel onOpenJob={openJob} />}
          {tab === "settings" && <SettingsPanel />}

          {activeJobId && tab !== "settings" && tab !== "gen" && (
            <div className="space-y-4">
              {!isFinished && <JobProgress key={activeJobId} jobId={activeJobId} onFinished={setJob} />}
              {jobError && <p className="text-xs text-destructive">{jobError}</p>}
              {job?.status === "ERROR" && (
                <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {job.error || "Job lỗi."}
                </p>
              )}
              {job && job.clips.length > 0 && <ResultGallery clips={job.clips} />}
              {job?.status === "DONE" && job.clips.length === 0 && (
                <p className="text-sm text-muted-foreground">Job xong nhưng không có clip nào.</p>
              )}
            </div>
          )}
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
