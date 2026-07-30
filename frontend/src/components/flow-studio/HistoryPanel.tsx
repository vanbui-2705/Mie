"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { describeFlowError, listClipJobs, type ClipJobSummary } from "@/lib/flow-api";
import { RefreshCw } from "lucide-react";

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  DONE: "default",
  ERROR: "destructive",
  CANCELLED: "outline",
};

const SOURCE_LABEL: Record<string, string> = {
  UPLOAD: "upload",
  LINK: "link",
  PROMPT: "gen",
};

function when(iso: string | null) {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("vi-VN");
}

export function HistoryPanel({ onOpenJob }: { onOpenJob: (jobId: string) => void }) {
  const [jobs, setJobs] = useState<ClipJobSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setJobs(await listClipJobs(30));
      setError(null);
    } catch (err) {
      setError(describeFlowError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Deferred by a tick so the first paint is not blocked by a state update
    // inside the effect body — the idiom the other pages use.
    const timer = setTimeout(() => void load(), 0);
    return () => clearTimeout(timer);
  }, [load]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Lịch sử job</CardTitle>
        <CardDescription>30 job gần nhất của bạn.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
          <RefreshCw className="h-4 w-4" />
          {loading ? "Đang tải…" : "Tải lại"}
        </Button>

        {error && <p className="text-xs text-destructive">{error}</p>}

        {!loading && !error && jobs.length === 0 && (
          <p className="text-sm text-muted-foreground">Chưa có job nào.</p>
        )}

        <ul className="divide-y divide-foreground/10">
          {jobs.map((job) => (
            <li key={job.id} className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-[13px] font-medium">{job.source_name}</p>
                <p className="text-[11px] text-muted-foreground">
                  {when(job.created_at)} · {SOURCE_LABEL[job.source_type] ?? "upload"} ·{" "}
                  {job.clip_count} clip
                </p>
                {job.error && (
                  <p className="mt-1 text-[11px] text-destructive">
                    {describeFlowError(job.error)}
                  </p>
                )}
                {job.purged_at && (
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    File đã dọn khỏi máy chủ · {when(job.purged_at)}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Badge variant={STATUS_VARIANT[job.status] ?? "secondary"}>{job.status}</Badge>
                <Button size="xs" variant="outline" onClick={() => onOpenJob(job.id)}>
                  Mở
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
