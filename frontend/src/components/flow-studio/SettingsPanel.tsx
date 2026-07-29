"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useFlowSettings, type FlowSettings } from "./useFlowSettings";

const BACKENDS = ["gemini", "ollama", "claude", "heuristic"];

export function SettingsPanel() {
  const { settings, save, reset } = useFlowSettings();
  // An overlay instead of a copy: the stored value stays the source of truth,
  // so nothing has to be synced back into state when the store changes.
  const [edits, setEdits] = useState<Partial<FlowSettings>>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const draft: FlowSettings = { ...settings, ...edits };

  const update = (patch: Partial<FlowSettings>) => {
    setEdits((current) => ({ ...current, ...patch }));
    setSaved(false);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (draft.topN < 1 || draft.topN > 10) return setError("Số clip nằm trong khoảng 1–10.");
    if (draft.clipMinSec < 5 || draft.clipMaxSec > 600) return setError("Độ dài clip nằm trong khoảng 5–600 giây.");
    if (draft.clipMinSec >= draft.clipMaxSec) return setError("Độ dài tối thiểu phải nhỏ hơn tối đa.");
    setError(null);
    save(draft);
    setEdits({});
    setSaved(true);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cài đặt xử lý</CardTitle>
        <CardDescription>Áp dụng cho mọi job Reup mới. Lưu trong trình duyệt này.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="set-topn">Số clip mỗi video</Label>
              <Input
                id="set-topn"
                type="number"
                min={1}
                max={10}
                value={draft.topN}
                onChange={(e) => update({ topN: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="set-min">Độ dài tối thiểu (giây)</Label>
              <Input
                id="set-min"
                type="number"
                min={5}
                max={600}
                value={draft.clipMinSec}
                onChange={(e) => update({ clipMinSec: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="set-max">Độ dài tối đa (giây)</Label>
              <Input
                id="set-max"
                type="number"
                min={5}
                max={600}
                value={draft.clipMaxSec}
                onChange={(e) => update({ clipMaxSec: Number(e.target.value) })}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="set-backend">Bộ chấm điểm</Label>
            <select
              id="set-backend"
              className="h-9 w-full rounded-md bg-foreground/5 px-3 text-sm text-foreground ring-1 ring-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={draft.scoringBackend}
              onChange={(e) => update({ scoringBackend: e.target.value })}
            >
              {BACKENDS.map((backend) => (
                <option key={backend} value={backend}>
                  {backend}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              heuristic chạy offline, không gọi LLM — dùng khi thiếu API key.
            </p>
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
          {saved && <p className="text-xs text-muted-foreground">Đã lưu.</p>}

          <div className="flex gap-2">
            <Button type="submit">Lưu</Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                reset();
                setEdits({});
                setSaved(false);
                setError(null);
              }}
            >
              Mặc định
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
