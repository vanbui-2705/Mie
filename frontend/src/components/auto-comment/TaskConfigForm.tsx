"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { ImagePlus, LoaderCircle, Play, Square } from "lucide-react";
import type { TaskConfig } from "@/types";
import { apiPost } from "@/lib/api-client";
import { toast } from "sonner";

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
  const [uploading, setUploading] = useState(false);

  const update = (patch: Partial<TaskConfig>) => {
    setCfg((p) => ({ ...p, ...patch }));
  };

  const handleStart = () => {
    const links = cfg.links.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const uids = cfg.uids.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (links.length === 0) {
      toast.error(cfg.action === "new_comment" ? "Hãy nhập ít nhất một link bài viết" : "Hãy nhập ít nhất một link comment");
      return;
    }
    if (cfg.action !== "new_comment" && (uids.length === 0 || uids.length !== links.length)) {
      toast.error("Số dòng UID phải bằng số dòng link comment");
      return;
    }
    if (cfg.action !== "delete" && !cfg.content.trim() && !cfg.imagePath.trim()) {
      toast.error("Hãy nhập nội dung hoặc chọn một ảnh");
      return;
    }
    onStart(cfg);
  };

  const uploadImage = async (file: File | undefined) => {
    if (!file) return;
    const formData = new FormData();
    formData.append("image", file);
    setUploading(true);
    try {
      const result = await apiPost<{ path: string; filename: string }>("/api/comment-tasks/upload", formData);
      update({ imagePath: result.path });
      toast.success(`Đã tải ảnh ${result.filename}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Không tải được ảnh");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-5">
      <SectionEyebrow label="Cấu hình luồng" />
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-[190px] flex-col gap-1">
          <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
            Hành động
          </Label>
          <select
            className="h-8 rounded-md border bg-transparent px-2 text-[9pt]"
            style={{ borderColor: "var(--border)" }}
            value={cfg.action}
            onChange={(event) => update({ action: event.target.value as TaskConfig["action"] })}
            disabled={running}
          >
            <option value="edit">Chỉnh sửa comment</option>
            <option value="delete">Xóa comment</option>
            <option value="new_comment">Tạo comment mới</option>
          </select>
        </div>
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

      <SectionEyebrow label={cfg.action === "new_comment" ? "Danh sách bài viết" : "UID Profile & Link comment"} />
      <div className={`grid gap-3 ${cfg.action === "new_comment" ? "" : "md:grid-cols-2"}`}>
        {cfg.action !== "new_comment" && (
          <div className="flex flex-col gap-1.5">
            <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
              UID Profile
            </Label>
            <Textarea value={cfg.uids} onChange={(e) => update({ uids: e.target.value })} placeholder="Mỗi dòng 1 UID, khớp với từng link" rows={3} className="text-[9pt]" disabled={running} />
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
            {cfg.action === "new_comment" ? "Link bài viết" : "Link comment"}
          </Label>
          <Textarea value={cfg.links} onChange={(e) => update({ links: e.target.value })} placeholder="Mỗi dòng 1 link" rows={3} className="text-[9pt]" disabled={running} />
        </div>
      </div>

      {cfg.action !== "delete" && (
        <>
      <SectionEyebrow label={cfg.action === "edit" ? "Nội dung comment mới" : "Nội dung comment"} />
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
            <Input value={cfg.imagePath} onChange={(e) => update({ imagePath: e.target.value })} placeholder="Đường dẫn ảnh trên server hoặc tải tệp" className="h-8 min-w-[220px] flex-1 text-[9pt]" disabled={running || uploading} />
            <label className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border px-3 text-[9pt] transition hover:bg-muted">
              {uploading ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />}
              {uploading ? "Đang tải..." : "Chọn ảnh"}
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif"
                className="hidden"
                disabled={running || uploading}
                onChange={(event) => {
                  void uploadImage(event.target.files?.[0]);
                  event.target.value = "";
                }}
              />
            </label>
          </div>
        </div>
      </div>
        </>
      )}

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
