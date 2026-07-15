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
import { ExternalLink, Flag, RefreshCw, SearchCheck, Share2, UsersRound } from "lucide-react";
import { toast } from "sonner";
import { apiGet, apiPost } from "@/lib/api-client";

const DONE_STATUSES = new Set(["success", "failed", "canceled", "done", "error", "stopped"]);

type FacebookAccount = { id: string; uid: string; name: string; browser_status: string; };
type ShareTarget = { id: string; type: "page" | "group" | "external_page"; name: string; url: string; status: string; available: boolean; reason?: string; };
type TaskSummary = { id: string; status: string; total: number; success: number; pending_review?: number; failed: number; errors?: TaskError[]; };
type TaskError = { index: number; uid: string; target_link: string; action: string; status: string; error: string; output_link?: string; };

export default function AutoSharePage() {
const [accounts, setAccounts] = useState<FacebookAccount[]>([]);
const [targets, setTargets] = useState<ShareTarget[]>([]);
const [selected, setSelected] = useState<Set<string>>(new Set());
const [selectedAccountId, setSelectedAccountId] = useState("");
const [groupText, setGroupText] = useState("");
const [externalPageText, setExternalPageText] = useState("");
const [campaignName, setCampaignName] = useState("Share campaign");
const [sourceUrl, setSourceUrl] = useState("");
const [customMessage, setCustomMessage] = useState("");
const [mode, setMode] = useState<"share_link" | "custom_content">("share_link");
const [loading, setLoading] = useState(true);
const [running, setRunning] = useState(false);
const [task, setTask] = useState<TaskSummary | null>(null);
const pollRef = useRef<number | null>(null);

const selectedTargets = useMemo(() => targets.filter((target) => selected.has(target.id)), [targets, selected]);

const stopPolling = useCallback(() => {
if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
setRunning(false);
}, []);

const loadData = useCallback(async () => {
setLoading(true);
try {
const [accountData, targetData] = await Promise.all([
apiGet<FacebookAccount[]>(`/api/facebook-accounts`),
apiGet<ShareTarget[]>(`/api/share-targets`),
]);
const supportedTargets = targetData.filter((target) => target.type !== "page");
setAccounts(accountData);
setTargets(supportedTargets);
setSelectedAccountId((prev) => prev || accountData[0]?.id || "");
setSelected((prev) => new Set(supportedTargets.filter((target) => target.available && prev.has(target.id)).map((target) => target.id)));
} catch (error) {
toast.error(error instanceof Error ? error.message : "Không tải được target share");
} finally { setLoading(false); }
}, []);

const refreshTask = useCallback(async (taskId: string) => {
const data = await apiGet<TaskSummary>(`/api/page-post-tasks/${taskId}`);
setTask(data);
if (DONE_STATUSES.has(String(data.status))) stopPolling();
}, [stopPolling]);

const importTargets = useCallback(async (kind: "group" | "external_page") => {
const rawText = kind === "group" ? groupText : externalPageText;
if (!selectedAccountId) { toast.error("Chọn Facebook Account trước"); return; }
if (!rawText.trim()) { toast.error(kind === "group" ? "Nhập danh sách group URL" : "Nhập danh sách page URL"); return; }
const endpoint = kind === "group" ? "/api/facebook-groups/import" : "/api/external-pages/import";
try {
const data = await apiPost<{ created: number; updated: number }>(endpoint, {
facebook_account_id: selectedAccountId, raw_text: rawText,
});
toast.success(`Đã import ${data.created} mới, cập nhật ${data.updated}`);
if (kind === "group") setGroupText(""); else setExternalPageText("");
await loadData();
} catch (error) {
toast.error(error instanceof Error ? error.message : "Import thất bại");
}
}, [externalPageText, groupText, loadData, selectedAccountId]);

const checkTarget = useCallback(async (target: ShareTarget) => {
if (target.type === "page") return;
const endpoint = target.type === "group"
? `/api/facebook-groups/${target.id.replace("group:", "")}/check`
: `/api/external-pages/${target.id.replace("external_page:", "")}/check`;
try {
await apiPost(endpoint, {});
toast.success("Đã check target");
await loadData();
} catch (error) {
toast.error(error instanceof Error ? error.message : "Check target thất bại");
}
}, [loadData]);

const startCampaign = useCallback(async () => {
if (!sourceUrl.trim()) { toast.error("Nhập link bài nguồn trước"); return; }
if (selectedTargets.length === 0) { toast.error("Chọn ít nhất một target share"); return; }
stopPolling(); setTask(null); setRunning(true);
try {
const campaign = await apiPost<{ id: string; targets: number }>(`/api/share-campaigns`, {
name: campaignName, mode, source_type: "public_url", source_post_url: sourceUrl,
custom_message: customMessage, message_snapshot: customMessage,
targets: selectedTargets.map((target) => target.id),
});
const data = await apiPost<{ task_id: string; targets: number; status: string }>(`/api/share-campaigns/${campaign.id}/start`, {});
setTask({ id: data.task_id, status: data.status, total: data.targets, success: 0, failed: 0 });
toast.success(`Đã bắt đầu campaign ${campaign.id.slice(0, 8)}`);
pollRef.current = window.setInterval(() => {
void refreshTask(data.task_id).catch((error) => { toast.error(error instanceof Error ? error.message : "Không đọc được task"); stopPolling(); });
}, 1500);
await refreshTask(data.task_id);
} catch (error) {
toast.error(error instanceof Error ? error.message : "Không tạo được campaign");
stopPolling();
}
}, [campaignName, customMessage, mode, refreshTask, selectedTargets, sourceUrl, stopPolling]);

useEffect(() => {
const timer = setTimeout(() => void loadData(), 0);
return () => { clearTimeout(timer); stopPolling(); };
}, [loadData, stopPolling]);

return (
<div className="space-y-5">
<div className="flex flex-wrap items-start justify-between gap-3">
<div className="min-w-0">
<h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>Auto Share Facebook</h1>
<p className="text-[9pt] mt-0.5" style={{ color: "var(--muted-foreground)" }}>Native Share bài nguồn sang Group hoặc Page nhập từ bên ngoài; không dùng Fanpage đã đồng bộ/quản lý.</p>
</div>
<Button variant="outline" className="h-8 gap-1.5 text-[9pt]" onClick={loadData} disabled={loading || running}>
<RefreshCw className="h-3.5 w-3.5" /> Tải lại
</Button>
</div>

<div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
<section className="space-y-4">
<SectionEyebrow label="Nguồn và nội dung share" />
<div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_190px]">
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Tên campaign</Label>
<Input value={campaignName} onChange={(event) => setCampaignName(event.target.value)} disabled={running} className="h-8 text-[9pt]" />
</div>
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Mode</Label>
<select value={mode} disabled={running} onChange={(event) => setMode(event.target.value as "share_link" | "custom_content")} className="h-8 w-full rounded-md border px-2 text-[9pt]" style={{ borderColor: "var(--border)", backgroundColor: "var(--background)" }}>
<option value="share_link">Share link</option>
<option value="custom_content">Custom content + link</option>
</select>
</div>
</div>
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Link bài nguồn</Label>
<Input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} disabled={running} className="h-8 text-[9pt]" placeholder="https://facebook.com/..." />
</div>
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Caption tùy chỉnh</Label>
<Textarea value={customMessage} onChange={(event) => setCustomMessage(event.target.value)} rows={6} disabled={running} className="max-h-[240px] overflow-auto text-[9pt]" placeholder="Nhập caption đăng kèm link nguồn" />
</div>

<div className="flex flex-wrap items-center gap-3">
<Button className="btn-frost-primary h-9 gap-1.5 text-[9pt] text-white" style={{ backgroundColor: "var(--accent)" }} onClick={startCampaign} disabled={running}>
<Share2 className="h-3.5 w-3.5" /> Share sang {selectedTargets.length} target
</Button>
{task && (
<div className="text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
Task {task.id.slice(0, 8)}: {task.status} · success {task.success}/{task.total} · pending review {task.pending_review ?? 0} · failed {task.failed}
</div>
)}
</div>
{task?.errors?.length ? (
<div className="rounded-md border p-3 text-[9pt]" style={{ borderColor: "var(--danger)", backgroundColor: "var(--danger-soft)", color: "var(--danger-fg-on-soft)" }}>
<div className="mb-2 font-semibold">Lỗi target share</div>
<div className="space-y-2">
{task.errors.slice(0, 5).map((item) => (
<div key={`${item.index}-${item.target_link}`} className="space-y-0.5">
<div className="font-mono text-[8pt]">{item.action} · {item.uid || item.target_link}</div>
<div>{item.error || "Target share thất bại."}</div>
</div>
))}
</div>
</div>
) : null}
</section>

<aside className="space-y-4">
<section className="space-y-3">
<SectionEyebrow label="Import Group / Page ngoài" />
<div className="space-y-3 rounded-md border p-3" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
<div className="space-y-2">
<Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Facebook Account dùng để share</Label>
<select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value)} className="h-8 w-full rounded-md border px-2 text-[9pt]" style={{ borderColor: "var(--border)", backgroundColor: "var(--background)" }} disabled={running || accounts.length === 0}>
{accounts.length === 0 ? <option value="">Chưa có account</option> : accounts.map((account) => (
<option key={account.id} value={account.id}>{account.name || "Chưa lấy tên"} · UID {account.uid} · {account.browser_status}</option>
))}
</select>
</div>
<div className="space-y-2">
<Label className="text-[9pt] font-medium">Group URLs</Label>
<Textarea value={groupText} onChange={(event) => setGroupText(event.target.value)} rows={4} className="max-h-[140px] overflow-auto text-[9pt]" placeholder={"Tên Group|https://facebook.com/groups/...\nHoặc chỉ nhập link Group"} disabled={running} />
<Button variant="outline" className="h-8 gap-1.5 text-[9pt]" onClick={() => void importTargets("group")} disabled={running || !selectedAccountId}>
<UsersRound className="h-3.5 w-3.5" /> Import group
</Button>
</div>
<div className="space-y-2">
<Label className="text-[9pt] font-medium">Page public / page đang follow URLs</Label>
<Textarea value={externalPageText} onChange={(event) => setExternalPageText(event.target.value)} rows={4} className="max-h-[140px] overflow-auto text-[9pt]" placeholder={"Tên Page|https://facebook.com/ten-page\nHoặc chỉ nhập link Page"} disabled={running} />
<Button variant="outline" className="h-8 gap-1.5 text-[9pt]" onClick={() => void importTargets("external_page")} disabled={running || !selectedAccountId}>
<ExternalLink className="h-3.5 w-3.5" /> Import page ngoài
</Button>
<p className="text-[8pt] leading-relaxed" style={{ color: "var(--muted-foreground)" }}>Extension dùng ID/slug trong URL để chọn đúng Page trong hộp native Share; không dán link bài nguồn và không tìm Page theo tên.</p>
</div>
</div>
</section>

<section className="space-y-3">
<SectionEyebrow label="Target share" />
<div className="overflow-hidden rounded-md border" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
<div className="flex flex-wrap items-center justify-between gap-2 border-b p-3" style={{ borderColor: "var(--border)" }}>
<span className="text-[9pt] font-semibold">Đã chọn {selectedTargets.length}</span>
<Button variant="ghost" className="h-7 px-2 text-[8pt]" onClick={() => setSelected(new Set(targets.filter((target) => target.available).map((target) => target.id)))} disabled={running || targets.every((target) => !target.available)}>
Chọn tất cả available
</Button>
</div>
<div className="max-h-[520px] overflow-auto">
{loading ? <EmptyState message="Đang tải target..." /> : targets.length === 0 ? (
<EmptyState message="Chưa có target. Hãy import Group hoặc Page bên ngoài." />
) : (targets.map((target) => (
<div key={target.id} className={`flex flex-wrap items-start gap-3 border-b p-3 sm:flex-nowrap ${target.available ? "" : "opacity-80"}`} style={{ borderColor: "var(--border)" }} title={target.reason || ""}>
<Checkbox checked={selected.has(target.id)} disabled={running || !target.available} onCheckedChange={(checked) => {
setSelected((prev) => { const next = new Set(prev); if (checked) next.add(target.id); else next.delete(target.id); return next; });
}} />
{target.type === "page" ? <Flag className="h-4 w-4 shrink-0" style={{ color: "var(--muted-foreground)" }} /> : target.type === "group" ? <UsersRound className="h-4 w-4 shrink-0" style={{ color: "var(--muted-foreground)" }} /> : <ExternalLink className="h-4 w-4 shrink-0" style={{ color: "var(--muted-foreground)" }} />}
<div className="min-w-0 flex-1">
<div className="truncate text-[9pt] font-semibold">{target.name}</div>
<div className="truncate text-[8pt]" style={{ color: "var(--muted-foreground)" }}>{target.url}</div>
{target.reason && (<div className="truncate text-[8pt]" style={{ color: "var(--muted-foreground)" }}>{target.reason}</div>)}
</div>
{target.type !== "page" && (
<Button variant="ghost" className="h-7 w-7 p-0" type="button" onClick={(event) => { event.preventDefault(); void checkTarget(target); }} disabled={running} title="Check browser target">
<SearchCheck className="h-3.5 w-3.5" />
</Button>
)}
<Badge variant="outline" className="shrink-0 text-[8pt]">{target.status || "active"}</Badge>
<TargetDeleteButton target={target} disabled={running} onDeleted={loadData} />
</div>
)))}
</div>
</div>
</section>
</aside>
</div>
</div>
);
}
