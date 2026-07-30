"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  createClipJob,
  describeFlowError,
  VOICE_OPTIONS,
  type VoiceId,
} from "@/lib/flow-api";
import { useFlowSettings } from "./useFlowSettings";
import type { FlowTab } from "./FlowSidebar";

/** Mirrors settings.CLIP_MAX_UPLOAD_BYTES — checked here so a 5 GB file fails
 * before it is uploaded, not after. */
const MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024;
const VIDEO_EXTENSION = /\.(mp4|mov|m4v|avi|wmv|mpeg|mpg|webm|mkv)$/i;

type Source = "file" | "link";

export function ReupPanel({
  onJobStarted,
  onGoTo,
}: {
  onJobStarted: (jobId: string) => void;
  onGoTo: (tab: FlowTab) => void;
}) {
  const { settings } = useFlowSettings();
  const [source, setSource] = useState<Source>("file");
  const [file, setFile] = useState<File | null>(null);
  const [link, setLink] = useState("");
  const [voiceover, setVoiceover] = useState(false);
  const [voice, setVoice] = useState<VoiceId>(VOICE_OPTIONS[0].id);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    if (source === "file") {
      if (!file) return setError("Chọn một file video.");
      if (file.size > MAX_UPLOAD_BYTES) return setError("File vượt quá giới hạn 4 GB.");
      if (!VIDEO_EXTENSION.test(file.name)) {
        return setError("Định dạng video chưa hỗ trợ. Nên dùng MP4, MOV, WebM hoặc MKV.");
      }
    } else if (!/^https?:\/\/.+/i.test(link.trim())) {
      return setError("Link phải là URL http(s).");
    }

    setSubmitting(true);
    try {
      const result = await createClipJob({
        file: source === "file" ? file : null,
        sourceLink: source === "link" ? link.trim() : undefined,
        topN: settings.topN,
        clipMinSec: settings.clipMinSec,
        clipMaxSec: settings.clipMaxSec,
        scoringBackend: settings.scoringBackend,
        voiceover,
        voice,
        editInstructions: settings.aiEditInstructions,
      });
      setFile(null);
      setLink("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      onJobStarted(result.job_id);
    } catch (err) {
      setError(describeFlowError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Reup / Edit video</CardTitle>
        <CardDescription>
          Đưa video gốc vào, AI cắt ra {settings.topN} clip dọc kèm phụ đề.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="flex gap-1 rounded-lg bg-foreground/5 p-1 text-[13px]">
            {(["file", "link"] as Source[]).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setSource(option)}
                className={cn(
                  "flex-1 rounded-md px-3 py-1.5 transition-colors",
                  source === option ? "bg-background text-foreground" : "text-muted-foreground",
                )}
              >
                {option === "file" ? "Tải file lên" : "Dán link"}
              </button>
            ))}
          </div>

          {source === "file" ? (
            <div className="space-y-2">
              <Label htmlFor="flow-file">File video</Label>
              <Input
                id="flow-file"
                ref={fileInputRef}
                type="file"
                accept="video/*"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {file && (
                <p className="text-xs text-muted-foreground">
                  {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="flow-link">Link video</Label>
              <Input
                id="flow-link"
                type="url"
                placeholder="https://www.youtube.com/watch?v=…"
                value={link}
                onChange={(e) => setLink(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">Tải bằng yt-dlp ở phía server.</p>
            </div>
          )}

          <div className="space-y-2 rounded-lg bg-foreground/5 px-3 py-2.5">
            <label className="flex items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                checked={voiceover}
                onChange={(e) => setVoiceover(e.target.checked)}
                className="h-4 w-4 accent-[var(--primary)]"
              />
              Lồng tiếng Việt (thay tiếng gốc)
            </label>
            {voiceover && (
              <div className="space-y-1.5">
                <Label htmlFor="flow-voice" className="text-xs">
                  Giọng đọc
                </Label>
                <select
                  id="flow-voice"
                  className="h-9 w-full rounded-md bg-background px-3 text-sm ring-1 ring-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  value={voice}
                  onChange={(e) => setVoice(e.target.value as VoiceId)}
                >
                  {VOICE_OPTIONS.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-muted-foreground">
                  Đọc đúng bản dịch đang chạy trên phụ đề. Nếu dịch vụ giọng nói lỗi, clip vẫn ra
                  với tiếng gốc.
                </p>
              </div>
            )}
          </div>

          <div className="rounded-lg bg-foreground/5 px-3 py-2 text-xs text-muted-foreground">
            <span className="text-foreground">{settings.topN} clip</span> ·{" "}
            {settings.clipMinSec}–{settings.clipMaxSec}s · chấm điểm bằng{" "}
            <span className="text-foreground">{settings.scoringBackend}</span>{" "}
            <button type="button" className="underline" onClick={() => onGoTo("settings")}>
              đổi ở Cài đặt
            </button>
            <p className="mt-2">
              Lần xử lý đầu tiên trên máy chủ mới có thể lâu hơn do hệ thống tải model nhận dạng
              giọng nói; các lần sau dùng lại model đã lưu.
            </p>
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}

          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Đang gửi…" : "Tạo clip"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
