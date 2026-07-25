"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  ChevronDown,
  ChevronUp,
  Clock3,
  ExternalLink,
  Images,
  KeyRound,
  LoaderCircle,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  Trash2,
  UsersRound,
} from "lucide-react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/EmptyState";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  apiGet,
  assignRoomGroups,
  createRentalConfig,
  deleteRentalConfig,
  listRentalConfigs,
  listRentalRoomJobs,
  listRentalRooms,
  postRentalNow,
  retryRoom,
  skipRoom,
  syncRentalNow,
  testRentalLogin,
  updateRentalConfig,
} from "@/lib/api-client";
import type { RentalConfig, RentalConfigInput, RentalPublicationJob, RentalRoom } from "@/types";

type SheetConnection = {
  id: string;
  name: string;
  sheet_name: string;
  status: string;
};

type FacebookGroup = {
  id: string;
  group_id: string;
  group_name: string;
  group_url: string;
  status: string;
};

type RentalForm = {
  name: string;
  username: string;
  password: string;
  province_code: string;
  province_name: string;
  district_code: string;
  district_name: string;
  ward_code: string;
  ward_name: string;
  caption_template: string;
  contact_phone: string;
  post_spacing_seconds: string;
  post_delay_seconds: string;
  poll_interval_seconds: string;
  auto_post: boolean;
  google_sheet_connection_id: string;
  timezone: string;
};

const HCM_DISTRICTS = [
  ["760", "Quận 1"],
  ["769", "Thành phố Thủ Đức"],
  ["770", "Quận 3"],
  ["773", "Quận 4"],
  ["774", "Quận 5"],
  ["775", "Quận 6"],
  ["778", "Quận 7"],
  ["776", "Quận 8"],
  ["771", "Quận 10"],
  ["772", "Quận 11"],
  ["761", "Quận 12"],
  ["765", "Quận Bình Thạnh"],
  ["777", "Quận Bình Tân"],
  ["764", "Quận Gò Vấp"],
  ["768", "Quận Phú Nhuận"],
  ["766", "Quận Tân Bình"],
  ["767", "Quận Tân Phú"],
  ["785", "Huyện Bình Chánh"],
  ["787", "Huyện Cần Giờ"],
  ["783", "Huyện Củ Chi"],
  ["784", "Huyện Hóc Môn"],
  ["786", "Huyện Nhà Bè"],
] as const;

const DEFAULT_CAPTION =
  "{title}\n{address} · {price} · {area_text}\n{description}\nLiên hệ: {contact_phone}\n#phongtro #{district_slug}";

const INITIAL_FORM: RentalForm = {
  name: "",
  username: "",
  password: "",
  province_code: "79",
  province_name: "TP. Hồ Chí Minh",
  district_code: "",
  district_name: "",
  ward_code: "",
  ward_name: "",
  caption_template: DEFAULT_CAPTION,
  contact_phone: "",
  post_spacing_seconds: "480",
  post_delay_seconds: "0",
  poll_interval_seconds: "300",
  auto_post: true,
  google_sheet_connection_id: "",
  timezone: "Asia/Ho_Chi_Minh",
};

export default function RentalAutomationPage() {
  const [configs, setConfigs] = useState<RentalConfig[]>([]);
  const [rooms, setRooms] = useState<RentalRoom[]>([]);
  const [sheets, setSheets] = useState<SheetConnection[]>([]);
  const [groups, setGroups] = useState<FacebookGroup[]>([]);
  const [selectedConfigId, setSelectedConfigId] = useState("");
  const [form, setForm] = useState<RentalForm>(INITIAL_FORM);
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [roomsLoading, setRoomsLoading] = useState(false);
  const [busyAction, setBusyAction] = useState("");
  const [assigningRoom, setAssigningRoom] = useState<RentalRoom | null>(null);
  const [selectedGroupIds, setSelectedGroupIds] = useState<Set<string>>(new Set());

  const selectedConfig = useMemo(
    () => configs.find((config) => config.id === selectedConfigId) ?? null,
    [configs, selectedConfigId],
  );
  const filteredRooms = useMemo(
    () => rooms.filter((room) => statusFilter === "all" || room.status === statusFilter),
    [rooms, statusFilter],
  );

  const loadRooms = useCallback(async (configId: string, quiet = false) => {
    if (!configId) {
      setRooms([]);
      return;
    }
    if (!quiet) setRoomsLoading(true);
    try {
      setRooms(await listRentalRooms(configId));
    } catch (error) {
      setRooms([]);
      if (!quiet) toast.error(errorMessage(error, "Không tải được danh sách phòng"));
    } finally {
      if (!quiet) setRoomsLoading(false);
    }
  }, []);

  const loadPage = useCallback(async () => {
    setLoading(true);
    try {
      const [configData, sheetData, groupData] = await Promise.all([
        listRentalConfigs(),
        apiGet<SheetConnection[]>("/api/google-sheets/connections").catch(() => []),
        apiGet<FacebookGroup[]>("/api/facebook-groups").catch(() => []),
      ]);
      setConfigs(configData);
      setSheets(sheetData);
      setGroups(groupData);
      const nextId = selectedConfigId && configData.some((item) => item.id === selectedConfigId)
        ? selectedConfigId
        : configData[0]?.id ?? "";
      setSelectedConfigId(nextId);
      if (nextId) {
        const nextConfig = configData.find((item) => item.id === nextId);
        if (nextConfig) setForm(formFromConfig(nextConfig));
      } else {
        setForm(INITIAL_FORM);
      }
    } catch (error) {
      toast.error(errorMessage(error, "Không tải được cấu hình đăng trọ"));
    } finally {
      setLoading(false);
    }
  }, [selectedConfigId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadPage(), 0);
    return () => window.clearTimeout(timer);
  }, [loadPage]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadRooms(selectedConfigId), 0);
    return () => window.clearTimeout(timer);
  }, [loadRooms, selectedConfigId]);

  useEffect(() => {
    if (!selectedConfigId || !rooms.some((room) => ["new", "posting", "pending_review"].includes(room.status))) {
      return;
    }
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadRooms(selectedConfigId, true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [loadRooms, rooms, selectedConfigId]);

  const chooseConfig = (configId: string) => {
    setSelectedConfigId(configId);
    const config = configs.find((item) => item.id === configId);
    setForm(config ? formFromConfig(config) : INITIAL_FORM);
  };

  const startNewConfig = () => {
    setSelectedConfigId("");
    setForm(INITIAL_FORM);
    setRooms([]);
    setStatusFilter("all");
  };

  const saveConfig = async () => {
    if (!form.name.trim() || !form.district_code || !form.district_name) {
      toast.error("Nhập tên cấu hình và chọn quận/huyện");
      return;
    }
    if (!selectedConfigId && (!form.username.trim() || !form.password)) {
      toast.error("Nhập tài khoản và mật khẩu NhatroVN cho cấu hình mới");
      return;
    }
    if ((form.username.trim() && !form.password) || (!form.username.trim() && form.password)) {
      toast.error("Nhập đủ tài khoản và mật khẩu khi muốn thay đổi thông tin đăng nhập");
      return;
    }

    const payload: RentalConfigInput = {
      name: form.name.trim(),
      province_code: form.province_code,
      province_name: form.province_name,
      district_code: form.district_code,
      district_name: form.district_name,
      ward_code: form.ward_code.trim() || null,
      ward_name: form.ward_name.trim() || null,
      caption_template: form.caption_template,
      contact_phone: form.contact_phone.trim(),
      post_spacing_seconds: positiveInt(form.post_spacing_seconds, 480),
      post_delay_seconds: nonNegativeInt(form.post_delay_seconds, 0),
      poll_interval_seconds: positiveInt(form.poll_interval_seconds, 300),
      auto_post: form.auto_post,
      google_sheet_connection_id: form.google_sheet_connection_id || null,
      timezone: form.timezone,
    };
    if (form.username.trim() && form.password) {
      payload.credentials = { username: form.username.trim(), password: form.password };
    }

    setBusyAction("save");
    try {
      const saved = selectedConfigId
        ? await updateRentalConfig(selectedConfigId, payload)
        : await createRentalConfig(payload);
      const nextConfigs = selectedConfigId
        ? configs.map((item) => (item.id === saved.id ? saved : item))
        : [saved, ...configs];
      setConfigs(nextConfigs);
      setSelectedConfigId(saved.id);
      setForm(formFromConfig(saved));
      toast.success(selectedConfigId ? "Đã cập nhật cấu hình" : "Đã tạo cấu hình đăng trọ");
    } catch (error) {
      toast.error(errorMessage(error, "Không lưu được cấu hình"));
    } finally {
      setBusyAction("");
    }
  };

  const removeConfig = async () => {
    if (!selectedConfig || !window.confirm(`Xóa cấu hình “${selectedConfig.name}” và toàn bộ phòng đã đồng bộ?`)) {
      return;
    }
    setBusyAction("delete");
    try {
      await deleteRentalConfig(selectedConfig.id);
      const remaining = configs.filter((item) => item.id !== selectedConfig.id);
      setConfigs(remaining);
      const next = remaining[0] ?? null;
      setSelectedConfigId(next?.id ?? "");
      setForm(next ? formFromConfig(next) : INITIAL_FORM);
      setRooms([]);
      toast.success("Đã xóa cấu hình");
    } catch (error) {
      toast.error(errorMessage(error, "Không xóa được cấu hình"));
    } finally {
      setBusyAction("");
    }
  };

  const runConfigAction = async (action: "login" | "sync" | "post") => {
    if (!selectedConfigId) {
      toast.error("Lưu cấu hình trước khi thực hiện thao tác này");
      return;
    }
    setBusyAction(action);
    try {
      if (action === "login") {
        await testRentalLogin(selectedConfigId);
        toast.success("Đăng nhập NhatroVN thành công");
      } else if (action === "sync") {
        const result = await syncRentalNow(selectedConfigId);
        toast.success(`Đồng bộ xong: ${result.added} phòng mới, ${result.matched} phòng đã ghép nhóm`);
        await Promise.all([loadRooms(selectedConfigId), refreshSelectedConfig()]);
      } else {
        const result = await postRentalNow(selectedConfigId);
        toast.success(result.fired.length ? `Đã xử lý ${result.fired.length} lượt đăng` : "Chưa có phòng đến hạn đăng");
        await Promise.all([loadRooms(selectedConfigId), refreshSelectedConfig()]);
      }
    } catch (error) {
      toast.error(errorMessage(error, "Thao tác thất bại"));
    } finally {
      setBusyAction("");
    }
  };

  const refreshSelectedConfig = async () => {
    const nextConfigs = await listRentalConfigs();
    setConfigs(nextConfigs);
    const nextSelected = nextConfigs.find((item) => item.id === selectedConfigId);
    if (nextSelected) setForm(formFromConfig(nextSelected));
  };

  const runRoomAction = async (room: RentalRoom, action: "skip" | "retry") => {
    setBusyAction(`${action}:${room.id}`);
    try {
      const updated = action === "skip" ? await skipRoom(room.id) : await retryRoom(room.id);
      setRooms((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      toast.success(action === "skip" ? "Đã bỏ qua phòng" : "Đã đưa phòng về hàng đợi");
    } catch (error) {
      toast.error(errorMessage(error, "Không cập nhật được phòng"));
    } finally {
      setBusyAction("");
    }
  };

  const openAssignGroups = (room: RentalRoom) => {
    setAssigningRoom(room);
    setSelectedGroupIds(new Set(room.matched_group_ids));
  };

  const saveAssignedGroups = async () => {
    if (!assigningRoom) return;
    if (selectedGroupIds.size === 0) {
      toast.error("Chọn ít nhất một nhóm Facebook");
      return;
    }
    setBusyAction(`assign:${assigningRoom.id}`);
    try {
      const updated = await assignRoomGroups(assigningRoom.id, Array.from(selectedGroupIds));
      setRooms((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setAssigningRoom(null);
      toast.success("Đã gán nhóm và đưa phòng về hàng đợi đăng");
    } catch (error) {
      toast.error(errorMessage(error, "Không gán được nhóm"));
    } finally {
      setBusyAction("");
    }
  };

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight">Đăng trọ tự động</h1>
          <p className="mt-0.5 text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
            Đồng bộ phòng từ NhatroVN, ghép nhóm Facebook theo khu vực và theo dõi kết quả đăng.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className="h-8 gap-1.5 text-[9pt]"
            onClick={() => void runConfigAction("sync")}
            disabled={!selectedConfigId || Boolean(busyAction)}
          >
            {busyAction === "sync" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Đồng bộ ngay
          </Button>
          <Button
            className="btn-frost-primary h-8 gap-1.5 text-[9pt] text-white"
            style={{ backgroundColor: "var(--accent)" }}
            onClick={startNewConfig}
            disabled={Boolean(busyAction)}
          >
            <Plus className="h-3.5 w-3.5" />
            Cấu hình mới
          </Button>
        </div>
      </header>

      {loading ? (
        <div className="rounded-md border" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
          <EmptyState message="Đang tải cấu hình đăng trọ..." icon={Building2} />
        </div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_310px]">
          <ConfigForm
            form={form}
            setForm={setForm}
            configs={configs}
            selectedConfigId={selectedConfigId}
            sheets={sheets}
            busyAction={busyAction}
            onChooseConfig={chooseConfig}
            onSave={() => void saveConfig()}
            onDelete={() => void removeConfig()}
            onTest={() => void runConfigAction("login")}
          />
          <StatusPanel config={selectedConfig} rooms={rooms} onPost={() => void runConfigAction("post")} busyAction={busyAction} />
        </div>
      )}

      <RoomTable
        rooms={filteredRooms}
        totalRooms={rooms.length}
        loading={roomsLoading}
        statusFilter={statusFilter}
        selectedConfigId={selectedConfigId}
        busyAction={busyAction}
        onStatusFilter={setStatusFilter}
        onReload={() => void loadRooms(selectedConfigId)}
        onAssign={openAssignGroups}
        onSkip={(room) => void runRoomAction(room, "skip")}
        onRetry={(room) => void runRoomAction(room, "retry")}
      />

      <AssignGroupsDialog
        room={assigningRoom}
        groups={groups}
        selectedIds={selectedGroupIds}
        saving={Boolean(assigningRoom && busyAction === `assign:${assigningRoom.id}`)}
        onOpenChange={(open) => {
          if (!open && !busyAction.startsWith("assign:")) setAssigningRoom(null);
        }}
        onToggle={(groupId, checked) => {
          setSelectedGroupIds((current) => {
            const next = new Set(current);
            if (checked) next.add(groupId);
            else next.delete(groupId);
            return next;
          });
        }}
        onSave={() => void saveAssignedGroups()}
      />
    </div>
  );
}

function ConfigForm({
  form,
  setForm,
  configs,
  selectedConfigId,
  sheets,
  busyAction,
  onChooseConfig,
  onSave,
  onDelete,
  onTest,
}: {
  form: RentalForm;
  setForm: React.Dispatch<React.SetStateAction<RentalForm>>;
  configs: RentalConfig[];
  selectedConfigId: string;
  sheets: SheetConnection[];
  busyAction: string;
  onChooseConfig: (id: string) => void;
  onSave: () => void;
  onDelete: () => void;
  onTest: () => void;
}) {
  const update = <K extends keyof RentalForm>(key: K, value: RentalForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };
  const districtOptions = selectedConfigId && form.district_code && !HCM_DISTRICTS.some(([code]) => code === form.district_code)
    ? [[form.district_code, form.district_name] as const, ...HCM_DISTRICTS]
    : HCM_DISTRICTS;

  return (
    <section className="space-y-3">
      <SectionEyebrow label="Cấu hình nguồn và khu vực" />
      <div className="rounded-md border p-4" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Cấu hình đang xem">
            <select className={selectClass} value={selectedConfigId} onChange={(event) => onChooseConfig(event.target.value)}>
              <option value="">Cấu hình mới</option>
              {configs.map((config) => <option key={config.id} value={config.id}>{config.name}</option>)}
            </select>
          </Field>
          <Field label="Tên cấu hình">
            <Input className="h-8 text-[9pt]" value={form.name} onChange={(event) => update("name", event.target.value)} placeholder="Ví dụ: Trọ Gò Vấp" />
          </Field>
          <Field label={selectedConfigId ? "Tài khoản mới (để trống nếu giữ nguyên)" : "Tài khoản NhatroVN"}>
            <Input className="h-8 text-[9pt]" value={form.username} onChange={(event) => update("username", event.target.value)} autoComplete="username" placeholder="Tên đăng nhập" />
          </Field>
          <Field label={selectedConfigId ? "Mật khẩu mới (để trống nếu giữ nguyên)" : "Mật khẩu"}>
            <Input className="h-8 text-[9pt]" value={form.password} onChange={(event) => update("password", event.target.value)} type="password" autoComplete="current-password" placeholder="••••••••" />
          </Field>
          <Field label="Tỉnh / Thành phố">
            <select className={selectClass} value={form.province_code} onChange={(event) => {
              if (event.target.value === "79") {
                setForm((current) => ({ ...current, province_code: "79", province_name: "TP. Hồ Chí Minh", district_code: "", district_name: "" }));
              }
            }}>
              <option value="79">TP. Hồ Chí Minh</option>
              {form.province_code !== "79" && <option value={form.province_code}>{form.province_name}</option>}
            </select>
          </Field>
          <Field label="Quận / Huyện">
            <select className={selectClass} value={form.district_code} onChange={(event) => {
              const district = districtOptions.find(([code]) => code === event.target.value);
              setForm((current) => ({ ...current, district_code: district?.[0] ?? "", district_name: district?.[1] ?? "" }));
            }}>
              <option value="">Chọn quận / huyện</option>
              {districtOptions.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
          </Field>
          <Field label="Mã phường / xã (tùy chọn)">
            <Input className="h-8 text-[9pt]" value={form.ward_code} onChange={(event) => update("ward_code", event.target.value)} placeholder="Mã trên NhatroVN" />
          </Field>
          <Field label="Tên phường / xã (tùy chọn)">
            <Input className="h-8 text-[9pt]" value={form.ward_name} onChange={(event) => update("ward_name", event.target.value)} placeholder="Ví dụ: Phường 1" />
          </Field>
          <Field label="Google Sheet mirror (tùy chọn)">
            <select className={selectClass} value={form.google_sheet_connection_id} onChange={(event) => update("google_sheet_connection_id", event.target.value)}>
              <option value="">Không đồng bộ Google Sheet</option>
              {sheets.map((sheet) => <option key={sheet.id} value={sheet.id}>{sheet.name} · {sheet.sheet_name}</option>)}
            </select>
          </Field>
          <Field label="Số điện thoại liên hệ">
            <Input className="h-8 text-[9pt]" value={form.contact_phone} onChange={(event) => update("contact_phone", event.target.value)} inputMode="tel" placeholder="090..." />
          </Field>
          <Field label="Giãn cách giữa hai bài (giây)">
            <Input className="h-8 text-[9pt]" type="number" min={60} value={form.post_spacing_seconds} onChange={(event) => update("post_spacing_seconds", event.target.value)} />
          </Field>
          <Field label="Trì hoãn bài đầu tiên (giây)">
            <Input className="h-8 text-[9pt]" type="number" min={0} value={form.post_delay_seconds} onChange={(event) => update("post_delay_seconds", event.target.value)} />
          </Field>
          <Field label="Chu kỳ lấy dữ liệu (giây)">
            <Input className="h-8 text-[9pt]" type="number" min={60} value={form.poll_interval_seconds} onChange={(event) => update("poll_interval_seconds", event.target.value)} />
          </Field>
          <div className="space-y-1.5 md:col-span-2">
            <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>Mẫu nội dung và hashtag</Label>
            <Textarea className="max-h-40 overflow-auto text-[9pt]" rows={5} value={form.caption_template} onChange={(event) => update("caption_template", event.target.value)} />
            <p className="text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
              Biến hỗ trợ: {"{title}, {address}, {price}, {area_text}, {description}, {contact_phone}, {district_slug}"}.
            </p>
          </div>
          <label className="flex min-h-8 cursor-pointer items-center gap-2 text-[9pt] font-medium md:col-span-2">
            <Checkbox checked={form.auto_post} onCheckedChange={(checked) => update("auto_post", Boolean(checked))} />
            Tự động đăng khi ghép được nhóm
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-4" style={{ borderColor: "var(--border)" }}>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="h-8 gap-1.5 text-[9pt]" onClick={onTest} disabled={!selectedConfigId || Boolean(busyAction)}>
              {busyAction === "login" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
              Test đăng nhập
            </Button>
            {selectedConfigId && (
              <Button variant="ghost" className="h-8 gap-1.5 text-[9pt]" onClick={onDelete} disabled={Boolean(busyAction)}>
                <Trash2 className="h-3.5 w-3.5" />
                Xóa
              </Button>
            )}
          </div>
          <Button className="btn-frost-primary h-8 gap-1.5 text-[9pt] text-white" style={{ backgroundColor: "var(--accent)" }} onClick={onSave} disabled={Boolean(busyAction)}>
            {busyAction === "save" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : selectedConfigId ? <Pencil className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
            {selectedConfigId ? "Cập nhật" : "Lưu cấu hình"}
          </Button>
        </div>
      </div>
    </section>
  );
}

function StatusPanel({ config, rooms, onPost, busyAction }: { config: RentalConfig | null; rooms: RentalRoom[]; onPost: () => void; busyAction: string }) {
  const waiting = rooms.filter((room) => room.status === "new").length;
  return (
    <aside className="space-y-3">
      <SectionEyebrow label="Tình trạng vận hành" />
      <div className="overflow-hidden rounded-md border" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
        <StatusRow icon={Building2} label="Cấu hình" value={config?.name ?? "Chưa lưu"} />
        <StatusRow icon={MapPin} label="Khu vực" value={config ? [config.ward_name, config.district_name].filter(Boolean).join(", ") : "Chưa chọn"} />
        <StatusRow icon={RefreshCw} label="Trạng thái nguồn" value={config ? rentalConfigStatusLabel(config.status) : "Chưa chạy"} />
        <StatusRow icon={Clock3} label="Lần thử đồng bộ" value={formatDate(config?.last_sync_attempt_at)} />
        <StatusRow icon={Clock3} label="Lần đồng bộ cuối" value={formatDate(config?.last_synced_at)} />
        <StatusRow icon={Send} label="Lần đăng cuối" value={formatDate(config?.last_post_at)} last />
      </div>
      {config?.last_error && (
        <div className="rounded-md border p-3 text-[8pt] leading-5" style={{ borderColor: "var(--danger)", color: "var(--danger-fg-on-soft)", backgroundColor: "var(--danger-soft)" }}>
          {config.last_error}
        </div>
      )}
      <div className="stats-bar-dark flex items-center justify-between rounded-md">
        <span>{rooms.length} phòng · {waiting} chờ đăng</span>
        <span>{config?.auto_post ? "Tự động bật" : "Đăng thủ công"}</span>
      </div>
      <Button className="btn-frost-primary h-9 w-full gap-1.5 text-[9pt] text-white" style={{ backgroundColor: "var(--accent)" }} onClick={onPost} disabled={!config || Boolean(busyAction)}>
        {busyAction === "post" ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
        Đăng ngay một lượt
      </Button>
      <p className="text-[8pt] leading-5" style={{ color: "var(--muted-foreground)" }}>
        Mỗi lượt xử lý tối đa một nhóm đến hạn theo khoảng giãn cách đã cấu hình.
      </p>
    </aside>
  );
}

function RoomTable({
  rooms,
  totalRooms,
  loading,
  statusFilter,
  selectedConfigId,
  busyAction,
  onStatusFilter,
  onReload,
  onAssign,
  onSkip,
  onRetry,
}: {
  rooms: RentalRoom[];
  totalRooms: number;
  loading: boolean;
  statusFilter: string;
  selectedConfigId: string;
  busyAction: string;
  onStatusFilter: (status: string) => void;
  onReload: () => void;
  onAssign: (room: RentalRoom) => void;
  onSkip: (room: RentalRoom) => void;
  onRetry: (room: RentalRoom) => void;
}) {
  const [expandedRoomId, setExpandedRoomId] = useState("");
  const [roomJobs, setRoomJobs] = useState<Record<string, RentalPublicationJob[]>>({});
  const [jobsLoadingId, setJobsLoadingId] = useState("");

  const toggleJobs = async (room: RentalRoom) => {
    if (expandedRoomId === room.id) {
      setExpandedRoomId("");
      return;
    }
    setExpandedRoomId(room.id);
    setJobsLoadingId(room.id);
    try {
      const jobs = await listRentalRoomJobs(room.id);
      setRoomJobs((current) => ({
        ...current,
        [room.id]: jobs,
      }));
    } catch (error) {
      toast.error(errorMessage(error, "Không tải được lịch sử đăng của phòng"));
    } finally {
      setJobsLoadingId("");
    }
  };

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <SectionEyebrow label={`Danh sách phòng${totalRooms ? ` · ${totalRooms}` : ""}`} />
        <div className="flex flex-wrap items-center gap-2">
          <select className={selectClass} value={statusFilter} onChange={(event) => onStatusFilter(event.target.value)}>
            <option value="all">Tất cả trạng thái</option>
            <option value="new">Mới / chờ đăng</option>
            <option value="waiting_groups">Chờ gán nhóm</option>
            <option value="posting">Đang đăng</option>
            <option value="posted">Đã đăng</option>
            <option value="partial">Đăng một phần</option>
            <option value="pending_review">Chờ kiểm tra</option>
            <option value="rented">Đã thuê</option>
            <option value="error">Lỗi</option>
            <option value="skipped">Đã bỏ qua</option>
          </select>
          <Button variant="outline" className="h-8 gap-1.5 text-[9pt]" onClick={onReload} disabled={!selectedConfigId || loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Tải lại
          </Button>
        </div>
      </div>

      <div className="overflow-hidden rounded-md border" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
        {loading ? (
          <EmptyState message="Đang tải danh sách phòng..." icon={Building2} />
        ) : !selectedConfigId ? (
          <EmptyState message="Chọn hoặc tạo một cấu hình để xem danh sách phòng." icon={Building2} />
        ) : rooms.length === 0 ? (
          <EmptyState message={totalRooms ? "Không có phòng ở trạng thái đã chọn." : "Chưa có dữ liệu phòng. Bấm Đồng bộ ngay để bắt đầu."} icon={Building2} />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-[900px] w-full border-collapse text-left">
              <thead className="frost-grid-header">
                <tr>
                  <th className="px-3 py-2">Mã phòng</th>
                  <th className="px-3 py-2">Thông tin</th>
                  <th className="px-3 py-2">Khu vực</th>
                  <th className="px-3 py-2">Nhóm / kết quả</th>
                  <th className="px-3 py-2">Trạng thái</th>
                  <th className="px-3 py-2 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {rooms.map((room, index) => (
                  <Fragment key={room.id}>
                  <tr className={`${index % 2 ? "frost-table-row-odd" : "frost-table-row-even"} frost-table-row-hover border-t`} style={{ borderColor: "var(--border)" }}>
                    <td className="px-3 py-3 align-top font-mono text-[8pt]">{room.external_room_id}</td>
                    <td className="max-w-[340px] px-3 py-3 align-top">
                      <div className="truncate text-[9pt] font-semibold" title={room.title}>{room.title || "Phòng trọ"}</div>
                      <div className="mt-1 truncate text-[8pt]" style={{ color: "var(--muted-foreground)" }} title={room.address}>{room.address || "Chưa có địa chỉ"}</div>
                      <div className="mt-1 text-[8pt] font-medium">{[room.price, room.area_text].filter(Boolean).join(" · ") || "Chưa có giá/diện tích"}</div>
                      <div className="mt-1 flex items-center gap-1 text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
                        <Images className="h-3 w-3" />
                        {room.images.length} ảnh nguồn · {room.media_paths.length} ảnh đã tải
                      </div>
                      <div className="mt-1 text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
                        Nguồn: {room.source_status || "không rõ"} · thấy {formatDate(room.last_seen_at)}
                      </div>
                    </td>
                    <td className="px-3 py-3 align-top text-[8pt]">{[room.ward, room.district].filter(Boolean).join(", ") || "—"}</td>
                    <td className="px-3 py-3 align-top text-[8pt]">
                      <div>{room.matched_group_ids.length} nhóm</div>
                      {Object.keys(room.post_urls).length > 0 && <div className="mt-1" style={{ color: "var(--success-fg-on-soft)" }}>{Object.keys(room.post_urls).length} lượt đã gửi</div>}
                      {room.retry_count > 0 && <div className="mt-1" style={{ color: "var(--warning-fg-on-soft)" }}>Đã thử lại {room.retry_count} lần</div>}
                      {room.mirror_status && (
                        <div className="mt-1">
                          Sheet: <span className={room.mirror_status === "succeeded" ? "text-success" : room.mirror_status === "failed" ? "text-danger" : "text-warning"}>
                            {publicationStatusLabel(room.mirror_status)}
                          </span>
                        </div>
                      )}
                      {room.mirror_error && <div className="mt-1 max-w-48 text-danger" title={room.mirror_error}>{room.mirror_error}</div>}
                    </td>
                    <td className="px-3 py-3 align-top">
                      <RoomStatus status={room.status} />
                      {room.error && <div className="mt-1 max-w-48 text-wrap-pretty text-[8pt]" style={{ color: "var(--danger)" }} title={room.error}>{room.error}</div>}
                    </td>
                    <td className="px-3 py-3 align-top">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <Button variant="outline" className="h-7 gap-1 px-2 text-[8pt]" onClick={() => void toggleJobs(room)} disabled={jobsLoadingId === room.id}>
                          {jobsLoadingId === room.id
                            ? <LoaderCircle className="h-3 w-3 animate-spin" />
                            : expandedRoomId === room.id
                              ? <ChevronUp className="h-3 w-3" />
                              : <ChevronDown className="h-3 w-3" />}
                          Lịch sử
                        </Button>
                        {!["rented", "inactive"].includes(room.status) && (room.status === "waiting_groups" || room.matched_group_ids.length === 0) && (
                          <Button variant="outline" className="h-7 gap-1 px-2 text-[8pt]" onClick={() => onAssign(room)} disabled={Boolean(busyAction)}>
                            <UsersRound className="h-3 w-3" />
                            Gán nhóm
                          </Button>
                        )}
                        {!["skipped", "posted", "rented", "inactive"].includes(room.status) && (
                          <Button variant="ghost" className="h-7 px-2 text-[8pt]" onClick={() => onSkip(room)} disabled={Boolean(busyAction)}>
                            Bỏ qua
                          </Button>
                        )}
                        {(["error", "skipped", "partial", "pending_review"].includes(room.status)) && (
                          <Button variant="outline" className="h-7 gap-1 px-2 text-[8pt]" onClick={() => onRetry(room)} disabled={Boolean(busyAction)}>
                            {busyAction === `retry:${room.id}` ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                            Thử lại
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expandedRoomId === room.id && (
                    <tr className="border-t bg-secondary/40" style={{ borderColor: "var(--border)" }}>
                      <td colSpan={6} className="px-4 py-3">
                        <RoomJobHistory jobs={roomJobs[room.id] ?? []} loading={jobsLoadingId === room.id} />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function RoomJobHistory({ jobs, loading }: { jobs: RentalPublicationJob[]; loading: boolean }) {
  if (loading) {
    return <div className="flex items-center gap-2 text-[8pt] text-muted-foreground"><LoaderCircle className="h-3.5 w-3.5 animate-spin" />Đang tải publication jobs...</div>;
  }
  if (jobs.length === 0) {
    return <p className="text-[8pt] text-muted-foreground">Phòng này chưa có publication job.</p>;
  }
  return (
    <div className="grid gap-2">
      <div className="text-[8pt] font-semibold">Publication jobs theo từng nhóm</div>
      <div className="grid gap-1">
        {jobs.map((job) => (
          <div key={job.id} className="grid items-start gap-2 rounded-md border bg-card px-3 py-2 text-[8pt] sm:grid-cols-[minmax(0,1fr)_auto_auto]">
            <div>
              <div className="font-medium">Group {job.target_external_id || job.target_id}</div>
              <div className="mt-0.5 text-muted-foreground">
                Lịch {formatDate(job.scheduled_at)} · thử {job.attempt_count}/{job.max_attempts}
              </div>
              {job.error && <div className="mt-1 text-danger">{job.error}</div>}
            </div>
            <span className={`status-badge ${publicationStatusClass(job.status)}`}>{publicationStatusLabel(job.status)}</span>
            {job.facebook_url ? (
              <a href={job.facebook_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-primary">
                Mở bài <ExternalLink className="h-3 w-3" />
              </a>
            ) : <span className="text-muted-foreground">Chưa có URL</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function AssignGroupsDialog({
  room,
  groups,
  selectedIds,
  saving,
  onOpenChange,
  onToggle,
  onSave,
}: {
  room: RentalRoom | null;
  groups: FacebookGroup[];
  selectedIds: Set<string>;
  saving: boolean;
  onOpenChange: (open: boolean) => void;
  onToggle: (groupId: string, checked: boolean) => void;
  onSave: () => void;
}) {
  const usableGroups = groups.filter((group) => group.group_id);
  return (
    <Dialog open={Boolean(room)} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Gán nhóm Facebook</DialogTitle>
          <DialogDescription className="text-[9pt]">
            {room ? `${room.external_room_id} · ${room.title}` : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[360px] overflow-auto rounded-md border" style={{ borderColor: "var(--border)" }}>
          {usableGroups.length === 0 ? (
            <EmptyState message="Chưa có nhóm Facebook đã nhận diện group ID. Hãy import và kiểm tra nhóm ở trang Auto Share." icon={UsersRound} />
          ) : usableGroups.map((group, index) => (
            <label key={group.id} className={`flex cursor-pointer items-start gap-3 p-3 ${index ? "border-t" : ""}`} style={{ borderColor: "var(--border)" }}>
              <Checkbox checked={selectedIds.has(group.group_id)} onCheckedChange={(checked) => onToggle(group.group_id, Boolean(checked))} disabled={saving} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[9pt] font-semibold">{group.group_name}</div>
                <div className="mt-0.5 truncate font-mono text-[8pt]" style={{ color: "var(--muted-foreground)" }}>{group.group_id}</div>
              </div>
              <a href={group.group_url} target="_blank" rel="noreferrer" aria-label={`Mở ${group.group_name}`} className="shrink-0" onClick={(event) => event.stopPropagation()}>
                <ExternalLink className="h-3.5 w-3.5" style={{ color: "var(--muted-foreground)" }} />
              </a>
            </label>
          ))}
        </div>
        <DialogFooter>
          <Button onClick={onSave} disabled={saving || selectedIds.size === 0 || usableGroups.length === 0} className="gap-1.5 text-[9pt]">
            {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <UsersRound className="h-3.5 w-3.5" />}
            Gán {selectedIds.size} nhóm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>{label}</Label>
      {children}
    </div>
  );
}

function StatusRow({ icon: Icon, label, value, last = false }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string; last?: boolean }) {
  return (
    <div className={`flex items-center gap-3 px-3 py-3 ${last ? "" : "border-b"}`} style={{ borderColor: "var(--border)" }}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md" style={{ backgroundColor: "var(--secondary)" }}>
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0">
        <div className="text-[8pt]" style={{ color: "var(--muted-foreground)" }}>{label}</div>
        <div className="truncate text-[9pt] font-semibold" title={value}>{value}</div>
      </div>
    </div>
  );
}

function RoomStatus({ status }: { status: string }) {
  const map: Record<string, [string, string]> = {
    new: ["Mới / chờ đăng", "status-badge status-badge--info"],
    waiting_groups: ["Chờ gán nhóm", "status-badge status-badge--warning"],
    posting: ["Đang đăng", "status-badge status-badge--info"],
    posted: ["Đã đăng", "status-badge status-badge--success"],
    partial: ["Đăng một phần", "status-badge status-badge--warning"],
    pending_review: ["Chờ kiểm tra", "status-badge status-badge--warning"],
    rented: ["Đã thuê", "status-badge status-badge--default"],
    inactive: ["Không hoạt động", "status-badge status-badge--default"],
    error: ["Lỗi", "status-badge status-badge--danger"],
    skipped: ["Đã bỏ qua", "status-badge status-badge--default"],
  };
  const [label, className] = map[status] ?? [status, "status-badge status-badge--default"];
  return <span className={className}>{label}</span>;
}

function publicationStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "Chờ xử lý",
    dispatching: "Đang phân phối",
    queued: "Đã vào hàng đợi",
    running: "Đang đăng",
    succeeded: "Đã đăng",
    failed: "Thất bại",
    canceled: "Đã hủy",
    pending_review: "Chờ kiểm tra",
  };
  return labels[status] ?? status;
}

function publicationStatusClass(status: string) {
  if (status === "succeeded") return "status-badge--success";
  if (status === "failed") return "status-badge--danger";
  if (["pending_review"].includes(status)) return "status-badge--warning";
  if (["pending", "dispatching", "queued", "running"].includes(status)) return "status-badge--info";
  return "status-badge--default";
}

function rentalConfigStatusLabel(status: string) {
  const labels: Record<string, string> = {
    active: "Sẵn sàng",
    syncing: "Đang đồng bộ",
    paused: "Tạm dừng",
    error: "Có lỗi",
  };
  return labels[status] ?? status;
}

function formFromConfig(config: RentalConfig): RentalForm {
  return {
    name: config.name,
    username: "",
    password: "",
    province_code: config.province_code,
    province_name: config.province_name,
    district_code: config.district_code,
    district_name: config.district_name,
    ward_code: config.ward_code ?? "",
    ward_name: config.ward_name ?? "",
    caption_template: config.caption_template || DEFAULT_CAPTION,
    contact_phone: config.contact_phone,
    post_spacing_seconds: String(config.post_spacing_seconds),
    post_delay_seconds: String(config.post_delay_seconds),
    poll_interval_seconds: String(config.poll_interval_seconds),
    auto_post: config.auto_post,
    google_sheet_connection_id: config.google_sheet_connection_id ?? "",
    timezone: config.timezone || "Asia/Ho_Chi_Minh",
  };
}

function positiveInt(value: string, fallback: number) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function nonNegativeInt(value: string, fallback: number) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

const selectClass = "h-8 w-full rounded-md border bg-transparent px-3 text-[9pt] outline-none transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50";
