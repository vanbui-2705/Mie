"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { EmptyState } from "@/components/shared/EmptyState";
import { TargetDeleteButton } from "@/components/shared/TargetDeleteButton";
import { Flag, ImagePlus, RefreshCw, Send, UsersRound, UserRound, X } from "lucide-react";
import { toast } from "sonner";
import { apiGet, apiPost } from "@/lib/api-client";

const DONE_STATUSES = new Set(["success", "failed", "canceled", "done", "error", "stopped"]);

type FacebookTarget = { id: string; type: "page" | "personal" | "group"; name: string; status: string; available: boolean; reason?: string; page_id?: string; group_id?: string; url?: string; uid?: string; };
type TaskSummary = { id: string; status: string; total: number; success: number; pending_review?: number; failed: number; };

export default function AutoPostPage() {
const [targets, setTargets] = useState<FacebookTarget[]>([]);
const [selected, setSelected] = useState<Set<string>>(new Set());
const [message, setMessage] = useState("");
const [link, setLink] = useState("");
const [mediaFiles, setMediaFiles] = useState<File[]>([]);
const [maxThreads, setMaxThreads] = useState(3);
const [loading, setLoading] = useState(true);
const [running, setRunning] = useState(false);
const [task, setTask] = useState<TaskSummary | null>(null);
const pollRef = useRef<number | null>(null);

const selectedTargets = useMemo(() => targets.filter((target) => selected.has(target.id)), [targets, selected]);

const stopPolling = useCallback(() => {
if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
setRunning(false);
}, []);

const loadTargets = useCallback(async () => {
setLoading(true);
try {
const data = await apiGet<FacebookTarget[]>(`/api/post-targets`);
setTargets(data);
setSelected((prev) => new Set(data.filter((target) => target.available && prev.has(target.id)).map((target) => target.id)));
} catch (error) {
toast.error(error instanceof Error ? error.message : "Không tải được nơi đăng");
} finally { setLoading(false); }
}, []);

const refreshTask = useCallback(async (taskId: string) => {
const data = await apiGet<TaskSummary>(`/api/page-post-tasks/${taskId}`);
setTask(data);
if (DONE_STATUSES.has(String(data.status))) stopPolling();
}, [stopPolling]);

const startTask = useCallback(async () => {
if (!message.trim() && !link.trim() && mediaFiles.length === 0) { toast.error("Nhập nội dung, link hoặc media trước khi đăng"); return; }
if (selectedTargets.length === 0) { toast.error("Chọn ít nhất một nơi đăng"); return; }
stopPolling(); setTask(null); setRunning(true);
try {
const data = await apiPost<{ task_id: string; total: number; status: string }>(
`/api/page-post-tasks`,
buildPostFormData(selectedTargets.map((target) => target.id), message, link, maxThreads, mediaFiles),
);
setTask({ id: data.task_id, status: data.status, total: data.total, success: 0, failed: 0 });
toast.success("Đã tạo tác vụ đăng bài");
pollRef.current = window.setInterval(() => {
void refreshTask(data.task_id).catch((error) => { toast.error(error instanceof Error ? error.message : "Không đọc được task"); stopPolling(); });
}, 1500);
await refreshTask(data.task_id);
} catch (error) {
toast.error(error instanceof Error ? error.message : "Không tạo được tác vụ");
stopPolling();
}
}, [link, maxThreads, mediaFiles, message, refreshTask, selectedTargets, stopPolling]);

useEffect(() => {
const timer = setTimeout(() => void loadTargets(), 0);
return () => { clearTimeout(timer); stopPolling(); };
}, [loadTargets, stopPolling]);

return (
<div className="space-y-5">
<div className="flex flex-wrap items-start justify-between gap-3">
<div className="min-w-0">
<h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>Auto Post Facebook</h1>
<p className="text-[9pt] mt-0.5" style={{ color: "var(--muted-foreground)" }}>Đăng text/link/ảnh/video lên Fanpage quản lý, Group và trang cá nhân đã login browser.</p>
</div>
<Button variant="outline" className="h-8 gap-1.5 text-[9pt]" onClick={loadTargets} disabled={loading || running}>
<RefreshCw className="h-3.5 w-3.5" /> Tải lại
</Button>
</div>

<div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_390px]">
<section className="space-y-4">
<SectionEyebrow label="Nội dung bài đăng" />
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Message</Label>
<Textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={7} disabled={running} className="max-h-[260px] overflow-auto text-[9pt]" placeholder="Nhập nội dung bài đăng" />
</div>
<div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_150px]">
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Link đính kèm</Label>
<Input value={link} onChange={(event) => setLink(event.target.value)} disabled={running} className="h-8 text-[9pt]" placeholder="https://..." />
</div>
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Threads</Label>
<Input type="number" min={1} max={20} value={maxThreads} onChange={(event) => setMaxThreads(Number(event.target.value) || 1)} disabled={running} className="h-8 text-[9pt]" />
</div>
</div>
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Ảnh / video</Label>
<div className="flex flex-wrap items-center gap-2">
<label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-3 text-[9pt]" style={{ borderColor: "var(--border)", color: "var(--foreground)" }}>
<ImagePlus className="h-3.5 w-3.5" /> Chọn file
<input type="file" multiple accept="image/*,video/*" className="hidden" disabled={running} onChange={(event) => { setMediaFiles((current) => mergeMediaFiles(current, Array.from(event.target.files ?? []))); event.target.value = ""; }} />
</label>
{mediaFiles.length > 0 && (
<Button variant="ghost" className="h-8 gap-1.5 text-[9pt]" onClick={() => setMediaFiles([])} disabled={running}>
<X className="h-3.5 w-3.5" /> Xóa media
</Button>
)}
</div>
{mediaFiles.length > 0 && (
<div className="max-h-[160px] overflow-auto rounded-md border p-2 text-[8pt]" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
{mediaFiles.map((file) => (
<div key={mediaFileKey(file)} className="flex justify-between gap-3 py-1">
<span className="min-w-0 truncate">{file.name}</span>
<span className="shrink-0" style={{ color: "var(--muted-foreground)" }}>{formatFileSize(file.size)}</span>
</div>
))}
</div>
)}
</div>

<div className="flex flex-wrap items-center gap-3">
<Button className="btn-frost-primary h-9 gap-1.5 text-[9pt] text-white" style={{ backgroundColor: "var(--accent)" }} onClick={startTask} disabled={running}>
<Send className="h-3.5 w-3.5" /> Đăng lên {selectedTargets.length} nơi
</Button>
{task && (
<div className="text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
Task {task.id.slice(0, 8)}: {task.status} · success {task.success}/{task.total} · pending review {task.pending_review ?? 0} · failed {task.failed}
</div>
)}
</div>
</section>

<aside className="space-y-3">
<SectionEyebrow label="Nơi đăng mục tiêu" />
<div className="overflow-hidden rounded-md border" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
<div className="flex flex-wrap items-center justify-between gap-2 border-b p-3" style={{ borderColor: "var(--border)" }}>
<span className="text-[9pt] font-semibold">Đã chọn {selectedTargets.length}</span>
<Button variant="ghost" className="h-7 px-2 text-[8pt]" onClick={() => setSelected(new Set(targets.filter((target) => target.available).map((target) => target.id)))} disabled={running || targets.every((target) => !target.available)}>
Chọn tất cả
</Button>
</div>
<div className="max-h-[520px] overflow-auto">
{loading ? <EmptyState message="Đang tải nơi đăng..." /> : targets.length === 0 ? (
<EmptyState message="Chưa có account/page/group. Hãy import account, sync pages hoặc import group ở Auto Share." />
) : (targets.map((target) => (
<div key={target.id} className={`flex flex-wrap items-start gap-3 border-b p-3 sm:flex-nowrap ${target.available ? "" : "opacity-70"}`} style={{ borderColor: "var(--border)" }} title={target.reason || ""}>
<Checkbox checked={selected.has(target.id)} disabled={running || !target.available} onCheckedChange={(checked) => {
setSelected((prev) => { const next = new Set(prev); if (checked) next.add(target.id); else next.delete(target.id); return next; });
}} />
{target.type === "personal" ? (
<UserRound className="h-4 w-4 shrink-0" style={{ color: "var(--muted-foreground)" }} />
) : target.type === "group" ? (
<UsersRound className="h-4 w-4 shrink-0" style={{ color: "var(--muted-foreground)" }} />
) : (
<Flag className="h-4 w-4 shrink-0" style={{ color: "var(--muted-foreground)" }} />
)}
<div className="min-w-0 flex-1">
<div className="truncate text-[9pt] font-semibold">{target.name}</div>
<div className="truncate font-mono text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
{target.type === "personal" ? target.uid : target.type === "group" ? target.url || target.group_id : target.page_id}
</div>
{target.reason && (<div className="truncate text-[8pt]" style={{ color: "var(--muted-foreground)" }}>{target.reason}</div>)}
</div>
<Badge variant="outline" className="shrink-0 text-[8pt]">
{target.type === "page" ? target.status || "active" : "Browser"}
</Badge>
<TargetDeleteButton target={target} disabled={running} onDeleted={loadTargets} />
</div>
)))}
</div>
</div>
</aside>
</div>
</div>
);
}

function buildPostFormData(targets: string[], message: string, link: string, maxThreads: number, files: File[]) {
const formData = new FormData();
formData.append("targets", JSON.stringify(targets));
formData.append("message", message);
formData.append("link", link);
formData.append("max_threads", String(maxThreads));
for (const file of files) { formData.append("media_files", file); }
return formData;
}

function formatFileSize(size: number) {
if (size < 1024) return `${size} B`;
if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function mergeMediaFiles(current: File[], incoming: File[]) {
if (incoming.length === 0) return current;
const seen = new Set(current.map(mediaFileKey));
const merged = [...current];
for (const file of incoming) { const key = mediaFileKey(file); if (!seen.has(key)) { seen.add(key); merged.push(file); } }
return merged;
}

function mediaFileKey(file: File) { return `${file.name}:${file.size}:${file.lastModified}`; }
