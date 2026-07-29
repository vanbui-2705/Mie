"use client";

import React, { useEffect, useState } from "react";
import { Card, CardContent } from "../ui/card";

interface ProgressTrackerProps {
  jobId: string;
  onComplete?: () => void;
}

export function ProgressTracker({ jobId, onComplete }: ProgressTrackerProps) {
  const [phase, setPhase] = useState<string>("queued");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    // Connect to Backend SSE endpoint
    // Assuming backend is running on /api/events/stream
    const eventSource = new EventSource(`/api/events/stream?channel=clip`);

    eventSource.addEventListener("phase", (e: any) => {
      const data = JSON.parse(e.data);
      if (data.job_id === jobId) {
        setPhase(data.phase);
      }
    });

    eventSource.addEventListener("done", (e: any) => {
      const data = JSON.parse(e.data);
      if (data.job_id === jobId) {
        setPhase("done");
        if (onComplete) onComplete();
        eventSource.close();
      }
    });

    eventSource.addEventListener("error", (e: any) => {
      const data = JSON.parse(e.data);
      if (data.job_id === jobId) {
        setPhase("error");
        setError(data.error);
        eventSource.close();
      }
    });

    return () => {
      eventSource.close();
    };
  }, [jobId, onComplete]);

  // Calculate percentage
  let percentage = 0;
  if (phase === "queued") percentage = 5;
  if (phase === "analyzing") percentage = 30;
  if (phase === "scoring") percentage = 60;
  if (phase === "rendering") percentage = 90;
  if (phase === "done") percentage = 100;
  if (phase === "error") percentage = 100; // full bar but red

  // Descriptions
  const descriptions: Record<string, string> = {
    queued: "Đang chờ đến lượt...",
    analyzing: "🎧 Đang nghe và bóc băng video...",
    scoring: "🧠 AI đang chấm điểm và dịch thuật...",
    rendering: "✂️ Đang cắt video siêu tốc...",
    done: "✅ Hoàn tất!",
    error: "❌ Đã xảy ra lỗi"
  };

  return (
    <Card className="w-full bg-slate-900 border-slate-800 text-white mt-8">
      <CardContent className="p-6">
        <div className="flex justify-between items-center mb-2">
          <span className="font-medium">{descriptions[phase] || "Đang xử lý..."}</span>
          <span className="text-sm text-slate-400">{percentage}%</span>
        </div>
        
        {/* Custom Progress Bar since Shadcn Progress isn't easily colorable without extra config */}
        <div className="w-full bg-slate-800 h-3 rounded-full overflow-hidden">
          <div 
            className={`h-full transition-all duration-500 ease-in-out ${phase === 'error' ? 'bg-red-500' : 'bg-blue-500'}`}
            style={{ width: `${percentage}%` }}
          />
        </div>

        {error && (
          <div className="mt-4 p-3 bg-red-900/50 border border-red-500/50 rounded text-red-200 text-sm">
            {error}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
