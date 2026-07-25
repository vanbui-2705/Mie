"use client";

import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  cancelSheetSource,
  createSheetCampaign,
  deleteSheetCampaign,
  getPublicationHealth,
  listFacebookPostTargets,
  listGoogleSheetConnections,
  listSheetCampaigns,
  listSheetPublicationJobs,
  listSheetSourceItems,
  pauseSheetCampaign,
  publishSheetSourceNow,
  resumeSheetCampaign,
  syncSheetCampaign,
  updateSheetCampaign,
} from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/utils";
import type {
  FacebookPostTarget,
  GoogleSheetConnection,
  PublicationHealth,
  PublicationJob,
  SheetCampaign,
  SheetCampaignInput,
  SheetScheduleMode,
  SheetSourceItem,
} from "@/types";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  ExternalLink,
  FileSpreadsheet,
  LoaderCircle,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Rows3,
  Send,
  Trash2,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

const ACTIVE_JOB_STATUSES = new Set(["pending", "dispatching", "queued", "running"]);
const TERMINAL_ITEM_STATUSES = new Set(["completed", "posted", "canceled", "invalid"]);
const WEEKDAYS = [
  { value: 0, label: "T2" },
  { value: 1, label: "T3" },
  { value: 2, label: "T4" },
  { value: 3, label: "T5" },
  { value: 4, label: "T6" },
  { value: 5, label: "T7" },
  { value: 6, label: "CN" },
];
const STATUS_FILTERS = [
  ["all", "Tất cả"],
  ["queued", "Chờ xử lý"],
  ["completed", "Hoàn tất"],
  ["invalid", "Không hợp lệ"],
  ["canceled", "Đã hủy"],
] as const;

type CampaignFormState = SheetCampaignInput & { slotsText: string };

const EMPTY_FORM: CampaignFormState = {
  connection_id: "",
  name: "",
  default_targets: [],
  default_schedule_mode: "NOW",
  schedule_slots: [],
  slotsText: "08:00, 12:00, 19:30",
  active_weekdays: [0, 1, 2, 3, 4, 5, 6],
  timezone: "Asia/Ho_Chi_Minh",
  max_posts_per_day: 20,
  min_post_gap_seconds: 300,
  late_policy: "publish_now",
  max_retries: 3,
  enabled: true,
};

export default function SheetCampaignsPage() {
  const { can } = useAuth();
  const [campaigns, setCampaigns] = useState<SheetCampaign[]>([]);
  const [connections, setConnections] = useState<GoogleSheetConnection[]>([]);
  const [targets, setTargets] = useState<FacebookPostTarget[]>([]);
  const [health, setHealth] = useState<PublicationHealth | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [items, setItems] = useState<SheetSourceItem[]>([]);
  const [jobs, setJobs] = useState<PublicationJob[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<SheetCampaign | null>(null);

  const selected = useMemo(
    () => campaigns.find((campaign) => campaign.id === selectedId) ?? null,
    [campaigns, selectedId],
  );
  const targetNames = useMemo(
    () => new Map(targets.map((target) => [target.id, target.name])),
    [targets],
  );
  const jobsBySource = useMemo(() => {
    const grouped = new Map<string, PublicationJob[]>();
    for (const job of jobs) {
      if (!job.source_item_id) continue;
      grouped.set(job.source_item_id, [...(grouped.get(job.source_item_id) ?? []), job]);
    }
    return grouped;
  }, [jobs]);
  const hasActiveJobs = jobs.some((job) => ACTIVE_JOB_STATUSES.has(job.status));

  const loadOverview = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [campaignData, connectionData, targetData, healthData] = await Promise.all([
        listSheetCampaigns(),
        listGoogleSheetConnections(),
        listFacebookPostTargets(),
        getPublicationHealth().catch(() => null),
      ]);
      setCampaigns(campaignData);
      setConnections(connectionData);
      setTargets(targetData);
      setHealth(healthData);
      setSelectedId((current) => (
        current && campaignData.some((campaign) => campaign.id === current)
          ? current
          : campaignData[0]?.id ?? ""
      ));
    } catch (error) {
      if (!quiet) toast.error(errorMessage(error, "Không tải được chiến dịch Google Sheets"));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (campaignId: string, filter: string, quiet = false) => {
    if (!campaignId) {
      setItems([]);
      setJobs([]);
      return;
    }
    if (!quiet) setDetailLoading(true);
    try {
      const [itemData, jobData] = await Promise.all([
        listSheetSourceItems(campaignId, filter),
        listSheetPublicationJobs(campaignId),
      ]);
      setItems(itemData);
      setJobs(jobData);
    } catch (error) {
      if (!quiet) toast.error(errorMessage(error, "Không tải được hàng đợi chiến dịch"));
    } finally {
      if (!quiet) setDetailLoading(false);
    }
  }, []);

  const refreshSelected = useCallback(async (quiet = false) => {
    await Promise.all([
      loadOverview(true),
      loadDetail(selectedId, statusFilter, quiet),
    ]);
  }, [loadDetail, loadOverview, selectedId, statusFilter]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadOverview(), 0);
    return () => window.clearTimeout(timer);
  }, [loadOverview]);

  useEffect(() => {
    const timer = window.setTimeout(
      () => void loadDetail(selectedId, statusFilter),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [loadDetail, selectedId, statusFilter]);

  useEffect(() => {
    if (!selectedId || (!hasActiveJobs && selected?.status !== "syncing")) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshSelected(true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [hasActiveJobs, refreshSelected, selected?.status, selectedId]);

  const runAction = useCallback(async (
    key: string,
    action: () => Promise<unknown>,
    success: string,
  ) => {
    setBusyAction(key);
    try {
      await action();
      toast.success(success);
      await refreshSelected(true);
    } catch (error) {
      toast.error(errorMessage(error, "Thao tác không thành công"));
    } finally {
      setBusyAction("");
    }
  }, [refreshSelected]);

  const summary = useMemo(() => ({
    ready: items.filter((item) => ["ready", "pending", "queued"].includes(item.status)).length,
    active: jobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status)).length,
    posted: jobs.filter((job) => job.status === "succeeded").length,
    attention: jobs.filter((job) => ["failed", "pending_review"].includes(job.status)).length
      + items.filter((item) => item.status === "invalid").length,
  }), [items, jobs]);

  const openCreate = () => {
    setEditing(null);
    setFormOpen(true);
  };
  const openEdit = () => {
    if (!selected) return;
    setEditing(selected);
    setFormOpen(true);
  };

  const handleSave = async (body: SheetCampaignInput) => {
    setBusyAction("save");
    try {
      const saved = editing
        ? await updateSheetCampaign(editing.id, withoutConnection(body))
        : await createSheetCampaign(body);
      toast.success(editing ? "Đã cập nhật chiến dịch" : "Đã tạo chiến dịch");
      setFormOpen(false);
      await loadOverview(true);
      setSelectedId(saved.id);
    } catch (error) {
      toast.error(errorMessage(error, "Không lưu được chiến dịch"));
      throw error;
    } finally {
      setBusyAction("");
    }
  };

  const handleDelete = async () => {
    if (!selected || !window.confirm(`Xóa chiến dịch “${selected.name}”?`)) return;
    await runAction(
      `delete:${selected.id}`,
      () => deleteSheetCampaign(selected.id),
      "Đã xóa chiến dịch",
    );
    setSelectedId("");
    await loadOverview(true);
  };

  return (
    <div className="mx-auto grid w-full max-w-[1600px] gap-4">
      <section className="flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="section-eyebrow">
            <span className="section-eyebrow__bar" />
            <span className="section-eyebrow__label">Google Sheets Publishing</span>
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Chiến dịch đăng bài</h1>
          <p className="mt-1 max-w-3xl text-[9pt] leading-5 text-muted-foreground text-pretty">
            Đồng bộ dòng READY, phân phối theo lịch và ghi kết quả Facebook ngược về Google Sheets.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refreshSelected()}
            disabled={loading || Boolean(busyAction)}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            Làm mới
          </Button>
          {can("google_sheet:create") && (
            <Button size="sm" className="btn-frost-primary" onClick={openCreate}>
              <Plus className="h-3.5 w-3.5" />
              Tạo chiến dịch
            </Button>
          )}
        </div>
      </section>

      {health && (
        <HealthStrip health={health} />
      )}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCell icon={Rows3} label="Dòng sẵn sàng" value={summary.ready} tone="var(--info)" />
        <SummaryCell icon={CircleDashed} label="Đang xử lý" value={summary.active} tone="var(--accent)" />
        <SummaryCell icon={CheckCircle2} label="Đã đăng" value={summary.posted} tone="var(--success)" />
        <SummaryCell icon={AlertTriangle} label="Cần kiểm tra" value={summary.attention} tone="var(--warning)" />
      </section>

      <section className="grid min-h-[520px] overflow-hidden rounded-lg border bg-card lg:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="border-b lg:border-b-0 lg:border-r">
          <div className="flex h-11 items-center justify-between border-b px-3">
            <span className="text-[9pt] font-semibold">Danh sách chiến dịch</span>
            <span className="text-[8pt] text-muted-foreground">{campaigns.length} chiến dịch</span>
          </div>
          <div className="max-h-72 overflow-auto p-2 lg:max-h-[700px]">
            {loading ? (
              <LoadingState label="Đang tải chiến dịch..." />
            ) : campaigns.length === 0 ? (
              <EmptyState
                icon={FileSpreadsheet}
                title="Chưa có chiến dịch"
                description="Kết nối một Google Sheet rồi tạo chiến dịch để bắt đầu."
              />
            ) : (
              <div className="grid gap-1">
                {campaigns.map((campaign) => (
                  <button
                    key={campaign.id}
                    type="button"
                    onClick={() => setSelectedId(campaign.id)}
                    className={cn(
                      "grid w-full grid-cols-[1fr_auto] items-center gap-2 rounded-md px-3 py-2.5 text-left transition-colors duration-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      selectedId === campaign.id ? "bg-secondary" : "hover:bg-secondary/70",
                    )}
                  >
                    <span>
                      <span className="flex items-center gap-2">
                        <span className="block truncate text-[9pt] font-semibold">{campaign.name}</span>
                        <span className={cn("status-badge", statusClass(campaign.status))}>
                          {statusLabel(campaign.status)}
                        </span>
                      </span>
                      <span className="mt-1 block truncate text-[8pt] text-muted-foreground">
                        Đồng bộ {formatDate(campaign.last_synced_at)}
                      </span>
                    </span>
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>

        <div className="min-w-0">
          {!selected ? (
            <EmptyState
              icon={FileSpreadsheet}
              title="Chọn một chiến dịch"
              description="Thông tin cấu hình và hàng đợi sẽ xuất hiện tại đây."
            />
          ) : (
            <>
              <div className="flex min-h-14 flex-col gap-2 border-b px-4 py-3 xl:flex-row xl:items-center xl:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold">{selected.name}</h2>
                    <span className={cn("status-badge", statusClass(selected.status))}>
                      {statusLabel(selected.status)}
                    </span>
                  </div>
                  {selected.last_error && (
                    <p className="mt-1 max-w-2xl text-[8pt] text-danger">{selected.last_error}</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  {can("google_sheet:update") && (
                    <>
                      <Button variant="outline" size="xs" onClick={openEdit} disabled={Boolean(busyAction)}>
                        <Pencil />
                        Chỉnh sửa
                      </Button>
                      <Button
                        variant="outline"
                        size="xs"
                        onClick={() => void runAction(
                          `toggle:${selected.id}`,
                          () => selected.enabled
                            ? pauseSheetCampaign(selected.id)
                            : resumeSheetCampaign(selected.id),
                          selected.enabled ? "Đã tạm dừng chiến dịch" : "Đã tiếp tục chiến dịch",
                        )}
                        disabled={Boolean(busyAction)}
                      >
                        {selected.enabled ? <Pause /> : <Play />}
                        {selected.enabled ? "Tạm dừng" : "Tiếp tục"}
                      </Button>
                      <Button
                        size="xs"
                        onClick={() => void runAction(
                          `sync:${selected.id}`,
                          () => syncSheetCampaign(selected.id),
                          "Đồng bộ Google Sheets hoàn tất",
                        )}
                        disabled={Boolean(busyAction)}
                      >
                        <RefreshCw className={cn(busyAction === `sync:${selected.id}` && "animate-spin")} />
                        Đồng bộ ngay
                      </Button>
                    </>
                  )}
                  {can("google_sheet:delete") && (
                    <Button variant="destructive" size="icon-xs" onClick={() => void handleDelete()} disabled={Boolean(busyAction)} title="Xóa chiến dịch">
                      <Trash2 />
                    </Button>
                  )}
                </div>
              </div>

              <div className="grid gap-4 p-4">
                <dl className="grid gap-3 rounded-md bg-secondary/60 p-3 sm:grid-cols-2 xl:grid-cols-4">
                  <Meta label="Chế độ lịch" value={selected.default_schedule_mode} icon={CalendarClock} />
                  <Meta label="Mục tiêu mặc định" value={`${selected.default_targets.length} nơi đăng`} icon={Send} />
                  <Meta label="Giới hạn ngày" value={`${selected.max_posts_per_day} bài`} icon={Rows3} />
                  <Meta label="Khoảng cách" value={formatDuration(selected.min_post_gap_seconds)} icon={CircleDashed} />
                </dl>

                <div>
                  <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <h3 className="text-[9pt] font-semibold">Hàng đợi nguồn</h3>
                      <p className="mt-0.5 text-[8pt] text-muted-foreground">
                        {items.length} dòng · {jobs.length} publication job
                      </p>
                    </div>
                    <select
                      className="h-8 rounded-md border bg-background px-2 text-[9pt]"
                      value={statusFilter}
                      onChange={(event) => setStatusFilter(event.target.value)}
                      aria-label="Lọc trạng thái dòng nguồn"
                    >
                      {STATUS_FILTERS.map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </div>
                  <SourceTable
                    items={items}
                    jobsBySource={jobsBySource}
                    targetNames={targetNames}
                    loading={detailLoading}
                    busyAction={busyAction}
                    canUpdate={can("google_sheet:update")}
                    onPublish={(item) => runAction(
                      `publish:${item.id}`,
                      () => publishSheetSourceNow(item.id),
                      "Đã đưa dòng vào hàng đợi đăng",
                    )}
                    onCancel={(item) => runAction(
                      `cancel:${item.id}`,
                      () => cancelSheetSource(item.id),
                      "Đã hủy dòng nguồn và các job chưa hoàn tất",
                    )}
                  />
                </div>
              </div>
            </>
          )}
        </div>
      </section>

      <CampaignFormDialog
        key={`${editing?.id ?? "new"}:${formOpen ? "open" : "closed"}`}
        open={formOpen}
        campaign={editing}
        connections={connections}
        targets={targets}
        saving={busyAction === "save"}
        onOpenChange={setFormOpen}
        onSave={handleSave}
      />
    </div>
  );
}

function CampaignFormDialog({
  open,
  campaign,
  connections,
  targets,
  saving,
  onOpenChange,
  onSave,
}: {
  open: boolean;
  campaign: SheetCampaign | null;
  connections: GoogleSheetConnection[];
  targets: FacebookPostTarget[];
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (body: SheetCampaignInput) => Promise<void>;
}) {
  const [form, setForm] = useState<CampaignFormState>(() => (
    campaign ? formFromCampaign(campaign) : {
      ...EMPTY_FORM,
      connection_id: connections.find((connection) => connection.status === "connected")?.id ?? "",
    }
  ));

  const update = <K extends keyof CampaignFormState>(key: K, value: CampaignFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const submit = async () => {
    const name = form.name.trim();
    const slots = parseSlots(form.slotsText);
    if (!name || !form.connection_id) {
      toast.error("Nhập tên chiến dịch và chọn Google Sheet");
      return;
    }
    if (form.default_targets.length === 0) {
      toast.error("Chọn ít nhất một nơi đăng mặc định");
      return;
    }
    if (form.active_weekdays.length === 0) {
      toast.error("Chọn ít nhất một ngày hoạt động");
      return;
    }
    if (slots.invalid.length > 0) {
      toast.error(`Khung giờ không hợp lệ: ${slots.invalid.join(", ")}`);
      return;
    }
    if (form.default_schedule_mode === "AUTO" && slots.values.length === 0) {
      toast.error("Chế độ AUTO cần ít nhất một khung giờ");
      return;
    }
    await onSave({
      connection_id: form.connection_id,
      name,
      default_targets: form.default_targets,
      default_schedule_mode: form.default_schedule_mode,
      schedule_slots: slots.values,
      active_weekdays: [...form.active_weekdays].sort(),
      timezone: form.timezone,
      max_posts_per_day: form.max_posts_per_day,
      min_post_gap_seconds: form.min_post_gap_seconds,
      late_policy: form.late_policy,
      max_retries: form.max_retries,
      enabled: form.enabled,
    });
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{campaign ? "Chỉnh sửa chiến dịch" : "Tạo chiến dịch Google Sheets"}</DialogTitle>
          <DialogDescription className="text-[9pt]">
            Chọn nguồn, nơi đăng và quy tắc phân phối cho các dòng READY.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Tên chiến dịch">
              <Input value={form.name} onChange={(event) => update("name", event.target.value)} disabled={saving} />
            </Field>
            <Field label="Nguồn Google Sheets">
              <select
                className="h-8 rounded-md border bg-background px-2 text-[9pt]"
                value={form.connection_id}
                onChange={(event) => update("connection_id", event.target.value)}
                disabled={saving || Boolean(campaign)}
              >
                <option value="">Chọn Google Sheet</option>
                {connections.map((connection) => (
                  <option key={connection.id} value={connection.id} disabled={connection.status !== "connected"}>
                    {connection.name} · {connection.sheet_name}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Nơi đăng mặc định">
            <div className="grid max-h-44 gap-1 overflow-auto rounded-md border p-2 sm:grid-cols-2">
              {targets.length === 0 ? (
                <p className="p-3 text-[9pt] text-muted-foreground">Chưa có Page, Group hoặc profile.</p>
              ) : targets.map((target) => {
                const checked = form.default_targets.includes(target.id);
                return (
                  <label key={target.id} className={cn("flex items-start gap-2 rounded-md p-2 text-[9pt]", checked && "bg-secondary")}>
                    <Checkbox
                      checked={checked}
                      disabled={saving || (!target.available && !checked)}
                      onCheckedChange={(value) => update(
                        "default_targets",
                        Boolean(value)
                          ? [...form.default_targets, target.id]
                          : form.default_targets.filter((id) => id !== target.id),
                      )}
                    />
                    <span>
                      <span className="block font-medium">{target.name}</span>
                      <span className="text-[8pt] text-muted-foreground">
                        {target.type} · {target.available ? "sẵn sàng" : target.reason || target.status}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </Field>

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Chế độ mặc định">
              <select
                className="h-8 rounded-md border bg-background px-2 text-[9pt]"
                value={form.default_schedule_mode}
                onChange={(event) => update("default_schedule_mode", event.target.value as SheetScheduleMode)}
                disabled={saving}
              >
                <option value="NOW">NOW · đăng ngay</option>
                <option value="EXACT">EXACT · theo giờ trong Sheet</option>
                <option value="AUTO">AUTO · tự xếp lịch</option>
              </select>
            </Field>
            <Field label="Khung giờ AUTO">
              <Input
                value={form.slotsText}
                onChange={(event) => update("slotsText", event.target.value)}
                placeholder="08:00, 12:00, 19:30"
                disabled={saving}
              />
            </Field>
            <Field label="Timezone">
              <Input value={form.timezone} onChange={(event) => update("timezone", event.target.value)} disabled={saving} />
            </Field>
          </div>

          <Field label="Ngày hoạt động">
            <div className="flex flex-wrap gap-2">
              {WEEKDAYS.map((day) => {
                const checked = form.active_weekdays.includes(day.value);
                return (
                  <label key={day.value} className={cn("flex h-8 items-center gap-2 rounded-md border px-3 text-[9pt]", checked && "bg-secondary")}>
                    <Checkbox
                      checked={checked}
                      disabled={saving}
                      onCheckedChange={(value) => update(
                        "active_weekdays",
                        Boolean(value)
                          ? [...form.active_weekdays, day.value]
                          : form.active_weekdays.filter((item) => item !== day.value),
                      )}
                    />
                    {day.label}
                  </label>
                );
              })}
            </div>
          </Field>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <NumberField
              label="Bài tối đa/ngày"
              value={form.max_posts_per_day}
              min={1}
              max={200}
              disabled={saving}
              onChange={(value) => update("max_posts_per_day", value)}
            />
            <NumberField
              label="Khoảng cách (giây)"
              value={form.min_post_gap_seconds}
              min={30}
              max={86400}
              disabled={saving}
              onChange={(value) => update("min_post_gap_seconds", value)}
            />
            <NumberField
              label="Số lần thử"
              value={form.max_retries}
              min={1}
              max={10}
              disabled={saving}
              onChange={(value) => update("max_retries", value)}
            />
            <Field label="Khi lịch đã trễ">
              <select
                className="h-8 rounded-md border bg-background px-2 text-[9pt]"
                value={form.late_policy}
                onChange={(event) => update("late_policy", event.target.value as "publish_now" | "miss")}
                disabled={saving}
              >
                <option value="publish_now">Đăng ngay</option>
                <option value="miss">Đánh dấu bỏ lỡ</option>
              </select>
            </Field>
          </div>

          <label className="flex items-center gap-2 text-[9pt]">
            <Checkbox checked={form.enabled} onCheckedChange={(value) => update("enabled", Boolean(value))} disabled={saving} />
            Kích hoạt chiến dịch sau khi lưu
          </label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Hủy</Button>
          <Button onClick={() => void submit()} disabled={saving}>
            {saving && <LoaderCircle className="animate-spin" />}
            {campaign ? "Lưu thay đổi" : "Tạo chiến dịch"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SourceTable({
  items,
  jobsBySource,
  targetNames,
  loading,
  busyAction,
  canUpdate,
  onPublish,
  onCancel,
}: {
  items: SheetSourceItem[];
  jobsBySource: Map<string, PublicationJob[]>;
  targetNames: Map<string, string>;
  loading: boolean;
  busyAction: string;
  canUpdate: boolean;
  onPublish: (item: SheetSourceItem) => Promise<unknown>;
  onCancel: (item: SheetSourceItem) => Promise<unknown>;
}) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full min-w-[940px] border-collapse text-left">
        <thead className="frost-grid-header">
          <tr>
            <th className="px-3 py-2">Dòng</th>
            <th className="px-3 py-2">Nội dung</th>
            <th className="px-3 py-2">Lịch đăng</th>
            <th className="px-3 py-2">Kết quả theo nơi đăng</th>
            <th className="px-3 py-2">Trạng thái</th>
            <th className="px-3 py-2 text-right">Thao tác</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr><td colSpan={6}><LoadingState label="Đang tải hàng đợi..." /></td></tr>
          ) : items.length === 0 ? (
            <tr>
              <td colSpan={6} className="px-3 py-12 text-center text-[9pt] text-muted-foreground">
                Chưa có dòng phù hợp. Chạy đồng bộ để đọc các dòng READY.
              </td>
            </tr>
          ) : items.map((item, index) => {
            const sourceJobs = jobsBySource.get(item.id) ?? [];
            const active = sourceJobs.some((job) => ACTIVE_JOB_STATUSES.has(job.status));
            return (
              <tr key={item.id} className={cn(index % 2 ? "frost-table-row-odd" : "frost-table-row-even", "border-t align-top")}>
                <td className="px-3 py-2 text-[8pt] font-medium">#{item.sheet_row_number}</td>
                <td className="max-w-sm px-3 py-2 text-[8pt]">
                  <p className="line-clamp-3 whitespace-pre-wrap">{item.content}</p>
                  <p className="mt-1 text-muted-foreground">ID: {item.external_id} · v{item.source_version}</p>
                  {item.validation_error && <p className="mt-1 text-danger">{item.validation_error}</p>}
                </td>
                <td className="px-3 py-2 text-[8pt] text-muted-foreground">
                  {item.schedule_mode}<br />{formatDate(item.scheduled_at)}
                </td>
                <td className="max-w-sm px-3 py-2">
                  {sourceJobs.length === 0 ? (
                    <span className="text-[8pt] text-muted-foreground">Chưa tạo job</span>
                  ) : (
                    <div className="grid gap-1.5">
                      {sourceJobs.map((job) => (
                        <div key={job.id} className="flex items-center justify-between gap-2 text-[8pt]">
                          <span className="truncate">
                            {targetNames.get(`${job.target_type}:${job.target_id}`) ?? job.target_type}
                            {job.attempt_count > 0 && ` · thử ${job.attempt_count}`}
                          </span>
                          <span className="flex items-center gap-1">
                            <span className={cn("status-badge", statusClass(job.status))}>{statusLabel(job.status)}</span>
                            {job.facebook_url && (
                              <a href={job.facebook_url} target="_blank" rel="noreferrer" className="text-primary" title="Mở bài Facebook">
                                <ExternalLink className="h-3.5 w-3.5" />
                              </a>
                            )}
                          </span>
                          {job.error && <span className="sr-only">{job.error}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2">
                  <span className={cn("status-badge", statusClass(item.status))}>{statusLabel(item.status)}</span>
                </td>
                <td className="px-3 py-2">
                  {canUpdate && (
                    <div className="flex justify-end gap-1">
                      {!TERMINAL_ITEM_STATUSES.has(item.status) && (
                        <Button
                          variant="outline"
                          size="xs"
                          disabled={Boolean(busyAction) || active}
                          onClick={() => void onPublish(item)}
                          title={active ? "Dòng đang có job chạy" : "Đăng ngay"}
                        >
                          <Send />
                          Đăng ngay
                        </Button>
                      )}
                      {!TERMINAL_ITEM_STATUSES.has(item.status) && (
                        <Button
                          variant="destructive"
                          size="icon-xs"
                          disabled={Boolean(busyAction)}
                          onClick={() => void onCancel(item)}
                          title="Hủy dòng"
                        >
                          <XCircle />
                        </Button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HealthStrip({ health }: { health: PublicationHealth }) {
  const pending = Object.entries(health.publication_jobs)
    .filter(([status]) => ACTIVE_JOB_STATUSES.has(status))
    .reduce((total, [, count]) => total + count, 0);
  const hasWarning = health.stale_jobs > 0
    || health.sheet_campaign_errors > 0
    || health.rental_config_errors > 0;
  return (
    <section className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-md border bg-card px-3 py-2 text-[8pt]">
      <span className="font-semibold">Vận hành</span>
      <span>Job đang xử lý: <strong>{pending}</strong></span>
      <span>Job treo: <strong className={health.stale_jobs ? "text-warning" : ""}>{health.stale_jobs}</strong></span>
      <span>Lỗi Sheet: <strong className={health.sheet_campaign_errors ? "text-danger" : ""}>{health.sheet_campaign_errors}</strong></span>
      <span>Lỗi phòng trọ: <strong className={health.rental_config_errors ? "text-danger" : ""}>{health.rental_config_errors}</strong></span>
      <span className={cn("ml-auto status-badge", hasWarning ? "status-badge--warning" : "status-badge--success")}>
        {hasWarning ? "Cần kiểm tra" : "Ổn định"}
      </span>
    </section>
  );
}

function SummaryCell({ icon: Icon, label, value, tone }: {
  icon: typeof Rows3;
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-md bg-secondary">
        <Icon className="h-4 w-4" style={{ color: tone }} />
      </div>
      <div>
        <div className="text-lg font-semibold leading-none">{value}</div>
        <div className="mt-1 text-[8pt] text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

function Meta({ icon: Icon, label, value }: {
  icon: typeof Rows3;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" />
      <div>
        <dt className="text-[8pt] text-muted-foreground">{label}</dt>
        <dd className="text-[9pt] font-medium">{value}</dd>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label className="text-[9pt]">{label}</Label>
      {children}
    </div>
  );
}

function NumberField({ label, value, min, max, disabled, onChange }: {
  label: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={label}>
      <Input
        type="number"
        value={value}
        min={min}
        max={max}
        disabled={disabled}
        onChange={(event) => onChange(Math.min(max, Math.max(min, Number(event.target.value) || min)))}
      />
    </Field>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex min-h-32 items-center justify-center gap-2 text-[9pt] text-muted-foreground">
      <LoaderCircle className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

function EmptyState({ icon: Icon, title, description }: {
  icon: typeof FileSpreadsheet;
  title: string;
  description: string;
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center px-6 text-center">
      <Icon className="h-7 w-7 text-muted-foreground" strokeWidth={1.5} />
      <div className="mt-3 text-[9pt] font-semibold">{title}</div>
      <p className="mt-1 max-w-sm text-[8pt] leading-5 text-muted-foreground text-pretty">{description}</p>
    </div>
  );
}

function statusClass(status: string) {
  const normalized = status.toLowerCase();
  if (["posted", "succeeded", "completed", "active", "ready"].includes(normalized)) return "status-badge--success";
  if (["failed", "invalid", "error"].includes(normalized)) return "status-badge--danger";
  if (["pending_review", "paused", "missed"].includes(normalized)) return "status-badge--warning";
  if (ACTIVE_JOB_STATUSES.has(normalized) || normalized === "syncing") return "status-badge--info";
  return "status-badge--default";
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    active: "Đang chạy",
    paused: "Tạm dừng",
    syncing: "Đang đồng bộ",
    ready: "Sẵn sàng",
    pending: "Chờ xử lý",
    dispatching: "Đang phân phối",
    queued: "Đã vào hàng đợi",
    running: "Đang đăng",
    posted: "Đã đăng",
    succeeded: "Đã đăng",
    completed: "Hoàn tất",
    failed: "Thất bại",
    invalid: "Không hợp lệ",
    canceled: "Đã hủy",
    pending_review: "Chờ kiểm tra",
    missed: "Bỏ lỡ lịch",
  };
  return labels[status.toLowerCase()] ?? status;
}

function formatDate(value: string | null) {
  if (!value) return "Chưa có";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDuration(seconds: number) {
  if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600} giờ`;
  if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60} phút`;
  return `${seconds} giây`;
}

function formFromCampaign(campaign: SheetCampaign): CampaignFormState {
  return {
    connection_id: campaign.connection_id,
    name: campaign.name,
    default_targets: campaign.default_targets,
    default_schedule_mode: campaign.default_schedule_mode,
    schedule_slots: campaign.schedule_slots,
    slotsText: campaign.schedule_slots.join(", "),
    active_weekdays: campaign.active_weekdays,
    timezone: campaign.timezone,
    max_posts_per_day: campaign.max_posts_per_day,
    min_post_gap_seconds: campaign.min_post_gap_seconds,
    late_policy: campaign.late_policy,
    max_retries: campaign.max_retries,
    enabled: campaign.enabled,
  };
}

function parseSlots(raw: string) {
  const entries = raw.split(/[\s,;]+/).map((value) => value.trim()).filter(Boolean);
  const invalid = entries.filter((value) => !/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value));
  return { values: [...new Set(entries)].sort(), invalid };
}

function withoutConnection(body: SheetCampaignInput): Omit<SheetCampaignInput, "connection_id"> {
  const result: Partial<SheetCampaignInput> = { ...body };
  delete result.connection_id;
  return result as Omit<SheetCampaignInput, "connection_id">;
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}
