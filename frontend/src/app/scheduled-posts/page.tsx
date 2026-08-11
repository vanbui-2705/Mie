"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/shared/EmptyState";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { TargetDeleteButton } from "@/components/shared/TargetDeleteButton";
import { CalendarClock, Flag, ImagePlus, Pause, Play, Plus, RefreshCw, Trash2, UserRound, UsersRound, X, Zap } from "lucide-react";
import { toast } from "sonner";
import { apiDelete, apiGet, apiPost } from "@/lib/api-client";

type PostTarget = { id: string; type: "page" | "personal" | "group"; name: string; status: string; available: boolean; reason?: string; page_id?: string; group_id?: string; url?: string; uid?: string; };
type ScheduledPost = { id: string; name: string; targets: string[]; target_count: number; message: string; link: string; media_count: number; post_count: number; next_item_index: number; post_items?: Array<{ message: string; link: string; media_count: number }>; max_threads: number; interval_seconds: number | null; next_fire_at: string | null; last_fired_at: string | null; stop_at: string | null; status: string; last_error?: string; };
type DraftPost = { id: string; message: string; link: string; files: File[]; };

export default function ScheduledPostsPage() {
const [items, setItems] = useState<ScheduledPost[]>([]);
const [targets, setTargets] = useState<PostTarget[]>([]);
const [selected, setSelected] = useState<Set<string>>(new Set());
const [name, setName] = useState("Lịch đăng mới");
const [posts, setPosts] = useState<DraftPost[]>([emptyDraftPost()]);
const [startAt, setStartAt] = useState("");
const [repeatMode, setRepeatMode] = useState<"once" | "minutes" | "hours" | "days">("once");
const [repeatValue, setRepeatValue] = useState(1);
const [stopAt, setStopAt] = useState("");
const [loading, setLoading] = useState(true);
const [saving, setSaving] = useState(false);

const selectedTargets = useMemo(() => targets.filter((target) => selected.has(target.id)), [targets, selected]);

const loadData = useCallback(async () => {
setLoading(true);
try {
const [itemsRaw, rows] = await Promise.all([
apiGet<ScheduledPost[]>(`/api/scheduled-posts`),
apiGet<PostTarget[]>(`/api/post-targets`),
]);
setItems(itemsRaw);
setTargets(rows);
setSelected((prev) => new Set(rows.filter((target) => target.available && prev.has(target.id)).map((target) => target.id)));
} catch (error) {
toast.error(error instanceof Error ? error.message : "Không tải được lịch đăng");
} finally { setLoading(false); }
}, []);

useEffect(() => {
const timer = setTimeout(() => void loadData(), 0);
return () => clearTimeout(timer);
}, [loadData]);

const createSchedule = useCallback(async () => {
if (selectedTargets.length === 0) { toast.error("Chọn ít nhất một nơi đăng"); return; }
const validPosts = posts.filter((post) => post.message.trim() || post.link.trim() || post.files.length > 0);
if (validPosts.length === 0) { toast.error("Thêm ít nhất một bài có nội dung, liên kết hoặc ảnh/video"); return; }
setSaving(true);
try {
const formData = new FormData();
formData.append("name", name.trim() || "Lịch đăng");
formData.append("targets", JSON.stringify(selectedTargets.map((target) => target.id)));
formData.append("message", validPosts[0]?.message ?? "");
formData.append("link", validPosts[0]?.link ?? "");
formData.append("post_items", JSON.stringify(validPosts.map((post) => ({ message: post.message, link: post.link, }))));
formData.append("max_threads", "3");
formData.append("start_at", startAt ? new Date(startAt).toISOString() : "");
const interval = intervalSeconds(repeatMode, repeatValue);
formData.append("interval_seconds", interval ? String(interval) : "");
formData.append("stop_at", stopAt ? new Date(stopAt).toISOString() : "");
validPosts.forEach((post, index) => {
for (const file of post.files) formData.append(`media_files_${index}`, file);
});
await apiPost(`/api/scheduled-posts`, formData);
toast.success("Đã tạo lịch đăng");
setPosts([emptyDraftPost()]);
await loadData();
} catch (error) {
toast.error(error instanceof Error ? error.message : "Không tạo được lịch đăng");
} finally { setSaving(false); }
}, [loadData, name, posts, repeatMode, repeatValue, selectedTargets, startAt, stopAt]);

const action = useCallback(async (id: string, kind: "pause" | "resume" | "fire-now" | "delete") => {
try {
const endpoint = kind === "delete" ? `/api/scheduled-posts/${id}` : `/api/scheduled-posts/${id}/${kind}`;
if (kind === "delete") {
await apiDelete(endpoint);
} else {
await apiPost(endpoint, {});
}
toast.success(kind === "fire-now" ? "Đã gửi yêu cầu chạy ngay" : "Đã cập nhật lịch đăng");
await loadData();
} catch (error) {
toast.error(error instanceof Error ? error.message : "Thao tác thất bại");
}
}, [loadData]);

return (
<div className="space-y-5">
<div className="flex flex-wrap items-start justify-between gap-3">
<div className="min-w-0">
<h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>Lịch đăng</h1>
<p className="mt-0.5 text-[9pt]" style={{ color: "var(--muted-foreground)" }}>Tạo gói bài đăng để hệ thống tự chạy khi đến giờ.</p>
</div>
<Button variant="outline" className="h-8 gap-1.5 text-[9pt]" onClick={loadData} disabled={loading || saving}>
<RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Tải lại
</Button>
</div>

<div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
<section className="space-y-4">
<SectionEyebrow label="Tạo lịch mới" />
<div className="grid gap-3 md:grid-cols-2">
<div className="space-y-2">
<Label className="text-[9pt]">Tên lịch</Label>
<Input className="h-8 text-[9pt]" value={name} onChange={(event) => setName(event.target.value)} disabled={saving} />
</div>
<div className="space-y-2">
<Label className="text-[9pt]">Bắt đầu lúc</Label>
<Input className="h-8 text-[9pt]" type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} disabled={saving} />
</div>
</div>

<div className="space-y-3">
<div className="flex flex-wrap items-center justify-between gap-2">
<Label className="text-[9pt]">Danh sách bài đăng</Label>
<Button variant="outline" className="h-8 gap-1.5 text-[8pt]" onClick={() => setPosts((current) => [...current, emptyDraftPost()])} disabled={saving}>
<Plus className="h-3.5 w-3.5" /> Thêm bài
</Button>
</div>
{posts.map((post, index) => (
<div key={post.id} className="space-y-3 rounded-md border p-3" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
<div className="flex items-center justify-between gap-2">
<span className="text-[9pt] font-semibold">Bài {index + 1}</span>
{posts.length > 1 && (
<Button variant="ghost" className="h-7 gap-1 px-2 text-[8pt]" onClick={() => setPosts((current) => current.filter((item) => item.id !== post.id))} disabled={saving}>
<X className="h-3.5 w-3.5" /> Xóa
</Button>
)}
</div>
<div className="space-y-2">
<Label className="text-[9pt]">Nội dung</Label>
<Textarea className="max-h-[220px] overflow-auto text-[9pt]" rows={5} value={post.message} onChange={(event) => updateDraftPost(setPosts, post.id, { message: event.target.value })} disabled={saving} placeholder="Nhập nội dung riêng cho bài này" />
</div>
<div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(220px,280px)]">
<div className="space-y-2">
<Label className="text-[9pt]">Liên kết đính kèm</Label>
<Input className="h-8 text-[9pt]" value={post.link} onChange={(event) => updateDraftPost(setPosts, post.id, { link: event.target.value })} disabled={saving} placeholder="https://..." />
</div>
<div className="space-y-2">
<Label className="text-[9pt]">Ảnh/video của bài này</Label>
<div className="flex flex-wrap items-center gap-2">
<label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border px-3 text-[9pt]" style={{ borderColor: "var(--border)" }}>
<ImagePlus className="h-3.5 w-3.5" /> Chọn tệp
<input className="hidden" type="file" multiple accept="image/*,video/*" disabled={saving} onChange={(event) => { const incoming = Array.from(event.target.files ?? []); setPosts((current) => current.map((item) => item.id === post.id ? { ...item, files: mergeFiles(item.files, incoming) } : item)); event.target.value = ""; }} />
</label>
{post.files.length > 0 && (
<Button variant="ghost" className="h-8 text-[8pt]" onClick={() => updateDraftPost(setPosts, post.id, { files: [] })} disabled={saving}>Xóa tệp</Button>
)}
</div>
{post.files.length > 0 && (
<div className="max-h-[94px] overflow-auto rounded-md border p-2 text-[8pt]" style={{ borderColor: "var(--border)" }}>
{post.files.map((file) => <div key={fileKey(file)} className="truncate">{file.name}</div>)}
</div>
)}
</div>
</div>
</div>
))}
</div>

<div className="grid gap-3 md:grid-cols-[180px_180px_minmax(0,1fr)]">
<div className="space-y-2">
<Label className="text-[9pt]">Lặp lại</Label>
<select className="h-8 w-full rounded-md border bg-transparent px-2 text-[9pt]" style={{ borderColor: "var(--border)" }} value={repeatMode} onChange={(event) => setRepeatMode(event.target.value as typeof repeatMode)} disabled={saving}>
<option value="once">Một lần</option>
<option value="minutes">Mỗi N phút</option>
<option value="hours">Mỗi N giờ</option>
<option value="days">Mỗi N ngày</option>
</select>
</div>
<div className="space-y-2">
<Label className="text-[9pt]">Giá trị</Label>
<Input className="h-8 text-[9pt]" type="number" min={1} value={repeatValue} onChange={(event) => setRepeatValue(Number(event.target.value) || 1)} disabled={saving || repeatMode === "once"} />
</div>
<div className="space-y-2">
<Label className="text-[9pt]">Dừng sau lúc</Label>
<Input className="h-8 text-[9pt]" type="datetime-local" value={stopAt} onChange={(event) => setStopAt(event.target.value)} disabled={saving || repeatMode === "once"} />
</div>
</div>

<Button className="btn-frost-primary h-9 gap-1.5 text-[9pt] text-white" style={{ backgroundColor: "var(--accent)" }} onClick={createSchedule} disabled={saving}>
<CalendarClock className="h-3.5 w-3.5" /> Tạo lịch {posts.length} bài cho {selectedTargets.length} nơi
</Button>
</section>

<aside className="space-y-3">
<SectionEyebrow label="Nơi đăng mục tiêu" />
<div className="overflow-hidden rounded-md border" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
<div className="flex items-center justify-between border-b p-3" style={{ borderColor: "var(--border)" }}>
<span className="text-[9pt] font-semibold">Đã chọn {selectedTargets.length}</span>
<Button variant="ghost" className="h-7 px-2 text-[8pt]" onClick={() => setSelected(new Set(targets.filter((target) => target.available).map((target) => target.id)))} disabled={saving}>Chọn tất cả</Button>
</div>
<div className="max-h-[440px] overflow-auto">
{targets.length === 0 ? <EmptyState message="Chưa có mục tiêu khả dụng." /> : targets.map((target) => (
<div key={target.id} className={`flex items-start gap-3 border-b p-3 ${target.available ? "" : "opacity-60"}`} style={{ borderColor: "var(--border)" }} title={target.reason || ""}>
<Checkbox checked={selected.has(target.id)} disabled={!target.available || saving} onCheckedChange={(checked) => {
setSelected((prev) => { const next = new Set(prev); if (checked) next.add(target.id); else next.delete(target.id); return next; });
}} />
{target.type === "personal" ? <UserRound className="h-4 w-4 shrink-0" /> : target.type === "group" ? <UsersRound className="h-4 w-4 shrink-0" /> : <Flag className="h-4 w-4 shrink-0" />}
<div className="min-w-0 flex-1">
<div className="truncate text-[9pt] font-semibold">{target.name}</div>
<div className="truncate text-[8pt]" style={{ color: "var(--muted-foreground)" }}>{target.uid || target.url || target.page_id || target.group_id}</div>
</div>
<Badge variant="outline" className="shrink-0 text-[8pt]">{target.available ? "ready" : target.status}</Badge>
<TargetDeleteButton target={target} disabled={saving} onDeleted={loadData} />
</div>
))}
</div>
</div>
</aside>
</div>

<section className="space-y-3">
<SectionEyebrow label="Danh sách lịch" />
{items.length === 0 ? <EmptyState message="Chưa có lịch đăng nào." /> : (
<div className="grid gap-2">
{items.map((item) => (
<div key={item.id} className="grid gap-3 rounded-md border p-3 md:grid-cols-[minmax(0,1fr)_auto]" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
<div className="min-w-0 space-y-1">
<div className="flex flex-wrap items-center gap-2">
<span className="truncate text-[10pt] font-semibold">{item.name}</span>
<Badge variant="outline" className="text-[8pt]">{item.status}</Badge>
<Badge variant="outline" className="text-[8pt]">{item.post_count || 1} bài</Badge>
<Badge variant="outline" className="text-[8pt]">{item.target_count} mục tiêu</Badge>
{item.media_count > 0 && <Badge variant="outline" className="text-[8pt]">{item.media_count} media</Badge>}
</div>
<div className="truncate text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
Bài tiếp theo #{((item.next_item_index || 0) % Math.max(item.post_count || 1, 1)) + 1}: {item.post_items?.[item.next_item_index || 0]?.message || item.message || item.link || "Nội dung trống"}
</div>
<div className="text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
Tiếp theo: {formatDate(item.next_fire_at)} · Lần cuối: {formatDate(item.last_fired_at)} · Lặp lại: {formatInterval(item.interval_seconds)}
</div>
{item.last_error ? (
<div className="text-[8pt]" style={{ color: "var(--destructive)" }}>{item.last_error}</div>
) : null}
</div>
<div className="flex flex-wrap items-center gap-2 md:justify-end">
<Button variant="outline" className="h-8 gap-1.5 text-[8pt]" onClick={() => action(item.id, "fire-now")}><Zap className="h-3.5 w-3.5" /> Chạy ngay</Button>
{item.status === "paused" ? (
<Button variant="outline" className="h-8 gap-1.5 text-[8pt]" onClick={() => action(item.id, "resume")}><Play className="h-3.5 w-3.5" /> Tiếp tục</Button>
) : (
<Button variant="outline" className="h-8 gap-1.5 text-[8pt]" onClick={() => action(item.id, "pause")}><Pause className="h-3.5 w-3.5" /> Tạm dừng</Button>
)}
<Button variant="ghost" className="h-8 gap-1.5 text-[8pt]" onClick={() => action(item.id, "delete")}><Trash2 className="h-3.5 w-3.5" /> Xóa</Button>
</div>
</div>
))}
</div>
)}
</section>
</div>
);
}

function intervalSeconds(mode: "once" | "minutes" | "hours" | "days", value: number) {
const amount = Math.max(1, value);
if (mode === "minutes") return amount * 60;
if (mode === "hours") return amount * 3600;
if (mode === "days") return amount * 86400;
return null;
}

function formatInterval(value: number | null) {
if (!value) return "Một lần";
if (value % 86400 === 0) return `${value / 86400} ngày`;
if (value % 3600 === 0) return `${value / 3600} giờ`;
return `${Math.round(value / 60)} phút`;
}

function formatDate(value: string | null) {
if (!value) return "-";
return new Date(value).toLocaleString("vi-VN");
}

function fileKey(file: File) { return `${file.name}:${file.size}:${file.lastModified}`; }

function emptyDraftPost(): DraftPost {
return { id: crypto.randomUUID(), message: "", link: "", files: [] };
}

function updateDraftPost(setPosts: Dispatch<SetStateAction<DraftPost[]>>, id: string, patch: Partial<DraftPost>) {
setPosts((current) => current.map((post) => post.id === id ? { ...post, ...patch } : post));
}

function mergeFiles(current: File[], incoming: File[]) {
if (incoming.length === 0) return current;
const seen = new Set(current.map(fileKey));
const merged = [...current];
for (const file of incoming) { const key = fileKey(file); if (!seen.has(key)) { seen.add(key); merged.push(file); } }
return merged;
}
