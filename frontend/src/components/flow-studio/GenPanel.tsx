"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  createGenJob,
  describeFlowError,
  VOICE_OPTIONS,
  type VoiceId,
} from "@/lib/flow-api";
import { useFlowSettings } from "./useFlowSettings";

/**
 * Prompt -> vertical video. The server writes a scene script, reads it aloud
 * with the Vietnamese TTS voice, puts a stock still behind each scene and burns
 * the same subtitles reup uses — so the result lands in the same gallery.
 */
const SELECT_CLASS =
  "h-9 w-full rounded-md bg-foreground/5 px-3 text-sm text-foreground ring-1 ring-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const GEN_BACKENDS = ["gemini", "ollama", "claude"] as const;
const GEN_DURATIONS = [15, 30, 60, 90, 120] as const;
const MAX_IMAGES = 12;
const MAX_IMAGE_BYTES = 15 * 1024 * 1024;
type GenBackend = (typeof GEN_BACKENDS)[number];

export function GenPanel({ onJobStarted }: { onJobStarted: (jobId: string) => void }) {
  const { settings } = useFlowSettings();
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [images, setImages] = useState<File[]>([]);
  const [durationSec, setDurationSec] = useState(30);
  const [voice, setVoice] = useState<VoiceId>(VOICE_OPTIONS[0].id);
  const [scriptBackend, setScriptBackend] = useState<GenBackend>(
    GEN_BACKENDS.includes(settings.scoringBackend as GenBackend)
      ? settings.scoringBackend as GenBackend
      : "gemini",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (prompt.trim().length < 10) return setError("Prompt cần ít nhất 10 ký tự.");
    if (durationSec < 5 || durationSec > 120) return setError("Thời lượng nằm trong khoảng 5–120 giây.");

    setSubmitting(true);
    try {
      const result = await createGenJob({
        prompt: prompt.trim(),
        negativePrompt: negativePrompt.trim() || undefined,
        durationSec,
        voice,
        scoringBackend: scriptBackend,
        images,
      });
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
        <CardTitle>Gen video</CardTitle>
        <CardDescription>
          AI viết kịch bản, đọc bằng giọng Việt, ghép hình nền và phụ đề thành video dọc 9:16.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="gen-prompt">Prompt</Label>
            <Textarea
              id="gen-prompt"
              rows={4}
              placeholder="Chủ đề video: ví dụ 3 thói quen buổi sáng giúp tập trung cả ngày…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="gen-images">Ảnh sản phẩm (tùy chọn, tối đa 12 ảnh)</Label>
            <Input
              ref={imageInputRef}
              id="gen-images"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              onChange={(event) => {
                const selected = Array.from(event.target.files ?? []);
                if (selected.length > MAX_IMAGES) {
                  setImages([]);
                  setError(`Chỉ được tải tối đa ${MAX_IMAGES} ảnh.`);
                  event.target.value = "";
                  return;
                }
                if (selected.some((image) => image.size > MAX_IMAGE_BYTES)) {
                  setImages([]);
                  setError("Mỗi ảnh phải nhỏ hơn hoặc bằng 15 MB.");
                  event.target.value = "";
                  return;
                }
                setError(null);
                setImages(selected);
              }}
            />
            <p className="text-xs text-muted-foreground">
              Có ảnh: hệ thống dùng ảnh của bạn theo đúng thứ tự và tạo chuyển động pan/zoom.
              Không có ảnh: hệ thống tự tìm ảnh theo từng cảnh.
            </p>
            {images.length > 0 && (
              <div className="rounded-lg bg-foreground/5 px-3 py-2 text-xs text-muted-foreground">
                <p className="font-medium text-foreground">Đã chọn {images.length} ảnh</p>
                <p className="mt-1 truncate">{images.map((image) => image.name).join(" · ")}</p>
                <button
                  type="button"
                  className="mt-2 text-destructive underline-offset-2 hover:underline"
                  onClick={() => {
                    setImages([]);
                    if (imageInputRef.current) imageInputRef.current.value = "";
                  }}
                >
                  Bỏ toàn bộ ảnh
                </button>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="gen-negative">Tránh nhắc đến (tuỳ chọn)</Label>
            <Textarea
              id="gen-negative"
              rows={2}
              placeholder="Chủ đề, ví dụ hoặc cách nói không muốn xuất hiện"
              value={negativePrompt}
              onChange={(e) => setNegativePrompt(e.target.value)}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="gen-duration">Thời lượng (giây)</Label>
              <Input
                id="gen-duration"
                type="number"
                min={5}
                max={120}
                value={durationSec}
                onChange={(e) => setDurationSec(Number(e.target.value))}
              />
              <div className="flex flex-wrap gap-1 pt-1">
                {GEN_DURATIONS.map((seconds) => (
                  <button
                    key={seconds}
                    type="button"
                    className={`rounded px-2 py-1 text-[11px] ${
                      durationSec === seconds
                        ? "bg-primary text-primary-foreground"
                        : "bg-foreground/5 text-muted-foreground"
                    }`}
                    onClick={() => setDurationSec(seconds)}
                  >
                    {seconds}s
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="gen-voice">Giọng đọc</Label>
              <select
                id="gen-voice"
                className={SELECT_CLASS}
                value={voice}
                onChange={(e) => setVoice(e.target.value as VoiceId)}
              >
                {VOICE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="gen-backend">AI viết kịch bản</Label>
              <select
                id="gen-backend"
                className={SELECT_CLASS}
                value={scriptBackend}
                onChange={(e) => setScriptBackend(e.target.value as GenBackend)}
              >
                {GEN_BACKENDS.map((backend) => (
                  <option key={backend} value={backend}>
                    {backend}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <p className="rounded-lg bg-foreground/5 px-3 py-2 text-xs text-muted-foreground">
            Thời lượng thực tế do giọng đọc quyết định: mỗi cảnh dài đúng bằng câu đọc của nó, nên
            video có thể lệch vài giây so với con số bạn nhập.
          </p>

          {error && <p className="text-xs text-destructive">{error}</p>}

          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Đang gửi…" : "Tạo video"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
