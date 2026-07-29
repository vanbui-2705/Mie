"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

/**
 * The generation engine is not chosen yet, so this panel stops at the payload:
 * it validates the form and shows exactly what would be POSTed. Nothing here
 * calls the backend — there is no endpoint to call.
 */
const SELECT_CLASS =
  "h-9 w-full rounded-md bg-foreground/5 px-3 text-sm text-foreground ring-1 ring-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const ASPECTS = ["9:16", "1:1", "16:9"];
const VOICES = [
  { id: "none", label: "Không lồng tiếng" },
  { id: "vi-female", label: "Nữ (tiếng Việt)" },
  { id: "vi-male", label: "Nam (tiếng Việt)" },
];
const SUBTITLE_LANGS = [
  { id: "none", label: "Không phụ đề" },
  { id: "vi", label: "Tiếng Việt" },
  { id: "en", label: "English" },
];

export function GenPanel() {
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [durationSec, setDurationSec] = useState(15);
  const [aspectRatio, setAspectRatio] = useState(ASPECTS[0]);
  const [variants, setVariants] = useState(1);
  const [voice, setVoice] = useState(VOICES[0].id);
  const [subtitleLang, setSubtitleLang] = useState(SUBTITLE_LANGS[1].id);
  const [referenceImage, setReferenceImage] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [payload, setPayload] = useState<string | null>(null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setPayload(null);
    if (prompt.trim().length < 10) return setError("Prompt cần ít nhất 10 ký tự.");
    if (durationSec < 3 || durationSec > 120) return setError("Thời lượng nằm trong khoảng 3–120 giây.");
    if (variants < 1 || variants > 4) return setError("Số biến thể nằm trong khoảng 1–4.");
    setError(null);
    setPayload(
      JSON.stringify(
        {
          prompt: prompt.trim(),
          negative_prompt: negativePrompt.trim() || null,
          duration_sec: durationSec,
          aspect_ratio: aspectRatio,
          variants,
          voice: voice === "none" ? null : voice,
          subtitle_lang: subtitleLang === "none" ? null : subtitleLang,
          reference_image: referenceImage ? referenceImage.name : null,
        },
        null,
        2,
      ),
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Gen video</CardTitle>
        <CardDescription>
          Chưa chốt engine sinh video — form này kiểm tra dữ liệu và hiện payload sẽ gửi.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="gen-prompt">Prompt</Label>
            <Textarea
              id="gen-prompt"
              rows={4}
              placeholder="Mô tả cảnh, nhân vật, không khí, chuyển động camera…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="gen-negative">Negative prompt</Label>
            <Textarea
              id="gen-negative"
              rows={2}
              placeholder="Thứ không muốn xuất hiện: chữ, watermark, méo mặt…"
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
                min={3}
                max={120}
                value={durationSec}
                onChange={(e) => setDurationSec(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="gen-aspect">Tỉ lệ khung</Label>
              <select
                id="gen-aspect"
                className={SELECT_CLASS}
                value={aspectRatio}
                onChange={(e) => setAspectRatio(e.target.value)}
              >
                {ASPECTS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="gen-variants">Số biến thể</Label>
              <Input
                id="gen-variants"
                type="number"
                min={1}
                max={4}
                value={variants}
                onChange={(e) => setVariants(Number(e.target.value))}
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="gen-voice">Giọng đọc</Label>
              <select id="gen-voice" className={SELECT_CLASS} value={voice} onChange={(e) => setVoice(e.target.value)}>
                {VOICES.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="gen-subtitle">Ngôn ngữ phụ đề</Label>
              <select
                id="gen-subtitle"
                className={SELECT_CLASS}
                value={subtitleLang}
                onChange={(e) => setSubtitleLang(e.target.value)}
              >
                {SUBTITLE_LANGS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="gen-reference">Ảnh tham chiếu (tuỳ chọn)</Label>
            <Input
              id="gen-reference"
              type="file"
              accept="image/*"
              onChange={(e) => setReferenceImage(e.target.files?.[0] ?? null)}
            />
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}

          <Button type="submit" className="w-full">
            Xem payload
          </Button>

          {payload && (
            <pre className="max-h-72 overflow-auto rounded-lg bg-foreground/5 p-3 text-[11px] leading-relaxed">
              {payload}
            </pre>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
