"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { Play, Square } from "lucide-react";
import type { TaskConfig } from "@/types";

type TaskConfigFormProps = {
  onStart: (config: TaskConfig) => void;
  onStop: () => void;
  running: boolean;
};

const INITIAL: TaskConfig = {
  threads: 5,
  uids: "",
  links: "",
  content: "",
  imagePath: "",
  delayMin: 0,
  delayMax: 0,
  delayEveryRounds: 1,
  action: "edit",
};

export function TaskConfigForm({ onStart, onStop, running }: TaskConfigFormProps) {
  const [cfg, setCfg] = useState<TaskConfig>(INITIAL);

  const update = (patch: Partial<TaskConfig>) => {
    setCfg((p) => ({ ...p, ...patch }));
  };

  const handleStart = () => {
    onStart(cfg);
  };

  return (
    <div className="space-y-5">
      <SectionEyebrow label="Cấu hình luồng" />
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1" style={{ maxWidth: 200 }}>
          <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
            Số luồng
          </Label>
          <Input type="number" value={cfg.threads} onChange={(e) => update({ threads: parseInt(e.target.value) || 0 })} className="h-8 text-[9pt]" disabled={running} min={1} max={200} />
        </div>
        <div className="sm:ml-auto">
          {!running ? (
            <Button onClick={handleStart} className="btn-frost-primary h-9 px-5 text-[9pt] font-semibold gap-1.5 text-white" style={{ backgroundColor: "var(--accent)", minWidth: 110 }}>
              <Play className="w-3.5 h-3.5" /> Bắt đầu
            </Button>
          ) : (
            <Button onClick={onStop} variant="outline" className="h-9 px-5 text-[9pt] font-semibold gap-1.5" style={{ borderColor: "var(--danger)", color: "var(--danger)", minWidth: 110 }}>
              <Square className="w-3.5 h-3.5" /> Dừng
            </Button>
          )}
        </div>
      </div>

      <SectionEyebrow label="UID Profile & Link bài viết" />
      <div className="grid gap-3 md:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
            UID Profile (để trống = tự động kiểm tra)
          </Label>
          <Textarea value={cfg.uids} onChange={(e) => update({ uids: e.target.value })} placeholder="Mỗi dòng 1 UID" rows={3} className="text-[9pt]" disabled={running} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
            Link bài viết
          </Label>
          <Textarea value={cfg.links} onChange={(e) => update({ links: e.target.value })} placeholder="Mỗi dòng 1 link" rows={3} className="text-[9pt]" disabled={running} />
        </div>
      </div>

      <SectionEyebrow label="Nội dung comment" />
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
            Nội dung
          </Label>
          <Textarea value={cfg.content} onChange={(e) => update({ content: e.target.value })} placeholder="Nhập nội dung comment. Dùng \n\n để ngăn các biến thể." rows={4} className="text-[9pt]" disabled={running} />
        </div>
        <div className="flex flex-col gap-1.5" style={{ maxWidth: 500 }}>
          <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
            Đường dẫn ảnh (tùy chọn)
          </Label>
          <div className="flex flex-wrap gap-2">
            <Input value={cfg.imagePath} onChange={(e) => update({ imagePath: e.target.value })} placeholder="/path/to/images/" className="h-8 min-w-[220px] flex-1 text-[9pt]" disabled={running} />
            <Button type="button" variant="outline" className="h-8 px-3 text-[9pt] shrink-0" disabled={running}>Chọn thư mục</Button>
          </div>
        </div>
      </div>

      <SectionEyebrow label="Delay giữa các vòng" />
      <div className="flex flex-wrap items-center gap-3 text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
        <span>Delay từ</span>
        <Input type="number" value={cfg.delayMin} onChange={(e) => update({ delayMin: parseInt(e.target.value) || 0 })} className="h-8 w-20 text-[9pt]" disabled={running} />
        <span>đến</span>
        <Input type="number" value={cfg.delayMax} onChange={(e) => update({ delayMax: parseInt(e.target.value) || 0 })} className="h-8 w-20 text-[9pt]" disabled={running} />
        <span>sau mỗi vòng: mỗi</span>
        <Input type="number" value={cfg.delayEveryRounds} onChange={(e) => update({ delayEveryRounds: parseInt(e.target.value) || 1 })} className="h-8 w-20 text-[9pt]" disabled={running} />
        <span>vòng</span>
      </div>
    </div>
  );
}
