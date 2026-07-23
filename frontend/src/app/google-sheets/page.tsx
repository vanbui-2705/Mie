"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check, Clipboard, ExternalLink, FileJson, FileSpreadsheet,
  LoaderCircle, RefreshCw, Save, ShieldCheck, Trash2, Unplug,
} from "lucide-react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/EmptyState";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiDelete, apiGet, apiPost } from "@/lib/api-client";

type SheetConnection = {
  id: string;
  name: string;
  spreadsheet_id: string;
  spreadsheet_url: string;
  sheet_name: string;
  service_account_email: string;
  poll_interval_seconds: number;
  timezone: string;
  status: "connected" | "read_only" | "error" | string;
  last_synced_at: string | null;
  last_error: string | null;
  created_at: string | null;
};

type Inspection = {
  connected: boolean;
  spreadsheet_id: string;
  spreadsheet_title: string;
  sheet_name: string;
  sheet_id: number | null;
  row_count: number;
  column_count: number;
  can_edit: boolean;
  headers: string[];
  preview_rows: string[][];
  service_account_email: string;
};

const INITIAL_FORM = {
  name: "",
  spreadsheetUrl: "",
  sheetName: "Posts",
  pollInterval: 60,
  timezone: "Asia/Ho_Chi_Minh",
};

export default function GoogleSheetsPage() {
  const [connections, setConnections] = useState<SheetConnection[]>([]);
  const [form, setForm] = useState(INITIAL_FORM);
  const [credentials, setCredentials] = useState<Record<string, unknown> | null>(null);
  const [credentialFileName, setCredentialFileName] = useState("");
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyConnectionId, setBusyConnectionId] = useState<string | null>(null);

  const canSubmit = Boolean(credentials && form.spreadsheetUrl.trim() && form.sheetName.trim());

  const loadConnections = useCallback(async () => {
    setLoading(true);
    try {
      setConnections(await apiGet<SheetConnection[]>("/api/google-sheets/connections"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Không tải được nguồn Google Sheets");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadConnections(), 0);
    return () => window.clearTimeout(timer);
  }, [loadConnections]);

  const requestBody = useMemo(() => ({
    name: form.name.trim(),
    spreadsheet_url: form.spreadsheetUrl.trim(),
    sheet_name: form.sheetName.trim(),
    poll_interval_seconds: form.pollInterval,
    timezone: form.timezone,
    credentials,
  }), [credentials, form]);

  const handleCredentialFile = useCallback(async (file?: File) => {
    setInspection(null);
    if (!file) {
      setCredentials(null);
      setCredentialFileName("");
      return;
    }
    if (file.size > 1024 * 1024) {
      toast.error("File credentials vượt quá giới hạn 1 MB");
      return;
    }
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
      if (parsed.type !== "service_account" || typeof parsed.client_email !== "string") {
        throw new Error("Đây không phải file service account hợp lệ");
      }
      setCredentials(parsed);
      setCredentialFileName(file.name);
      toast.success("Đã đọc credentials, nội dung file sẽ không hiển thị trên màn hình");
    } catch (error) {
      setCredentials(null);
      setCredentialFileName("");
      toast.error(error instanceof Error ? error.message : "Không đọc được file credentials");
    }
  }, []);

  const testConnection = useCallback(async () => {
    if (!canSubmit) {
      toast.error("Chọn file credentials và nhập link Google Sheets trước khi kiểm tra");
      return;
    }
    setTesting(true);
    setInspection(null);
    try {
      const result = await apiPost<Inspection>("/api/google-sheets/connections/test", requestBody);
      setInspection(result);
      toast.success(result.can_edit ? "Kết nối thành công, có quyền đọc và ghi" : "Kết nối được nhưng chỉ có quyền đọc");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Kiểm tra kết nối thất bại");
    } finally {
      setTesting(false);
    }
  }, [canSubmit, requestBody]);

  const saveConnection = useCallback(async () => {
    if (!canSubmit) {
      toast.error("Chọn file credentials và nhập link Google Sheets trước khi lưu");
      return;
    }
    setSaving(true);
    try {
      await apiPost<SheetConnection>("/api/google-sheets/connections", requestBody);
      toast.success("Đã lưu nguồn Google Sheets");
      setForm(INITIAL_FORM);
      setCredentials(null);
      setCredentialFileName("");
      setInspection(null);
      await loadConnections();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Không lưu được nguồn Google Sheets");
    } finally {
      setSaving(false);
    }
  }, [canSubmit, loadConnections, requestBody]);

  const testSavedConnection = useCallback(async (connection: SheetConnection) => {
    setBusyConnectionId(connection.id);
    try {
      const result = await apiPost<Inspection>(`/api/google-sheets/connections/${connection.id}/test`, {});
      setInspection(result);
      toast.success(result.can_edit ? `Nguồn “${connection.name}” hoạt động bình thường` : `Nguồn “${connection.name}” đang chỉ đọc`);
      await loadConnections();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Kiểm tra nguồn thất bại");
      await loadConnections();
    } finally {
      setBusyConnectionId(null);
    }
  }, [loadConnections]);

  const deleteConnection = useCallback(async (connection: SheetConnection) => {
    if (!window.confirm(`Xóa nguồn “${connection.name}”?`)) return;
    setBusyConnectionId(connection.id);
    try {
      await apiDelete(`/api/google-sheets/connections/${connection.id}`);
      toast.success("Đã xóa nguồn Google Sheets");
      await loadConnections();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Không xóa được nguồn Google Sheets");
    } finally {
      setBusyConnectionId(null);
    }
  }, [loadConnections]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>
            Nguồn Google Sheets
          </h1>
          <p className="mt-0.5 text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
            Kết nối bảng nội dung để chuẩn bị luồng đồng bộ và tự động đăng Facebook.
          </p>
        </div>
        <Button variant="outline" className="h-8 gap-1.5 text-[9pt]" onClick={loadConnections} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Tải lại
        </Button>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
        <section className="space-y-4 rounded-md border p-4" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
          <SectionEyebrow label="Thêm nguồn mới" />

          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Tên nguồn">
              <Input
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                className="h-8 text-[9pt]"
                placeholder="Ví dụ: Nội dung phòng trọ"
                disabled={saving || testing}
              />
            </Field>
            <Field label="Tên worksheet">
              <Input
                value={form.sheetName}
                onChange={(event) => { setForm((current) => ({ ...current, sheetName: event.target.value })); setInspection(null); }}
                className="h-8 text-[9pt]"
                placeholder="Posts"
                disabled={saving || testing}
              />
            </Field>
          </div>

          <Field label="Link hoặc Spreadsheet ID">
            <Input
              value={form.spreadsheetUrl}
              onChange={(event) => { setForm((current) => ({ ...current, spreadsheetUrl: event.target.value })); setInspection(null); }}
              className="h-8 font-mono text-[8pt]"
              placeholder="https://docs.google.com/spreadsheets/d/.../edit"
              disabled={saving || testing}
            />
          </Field>

          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Chu kỳ kiểm tra">
              <select
                className="h-8 w-full rounded-md border bg-transparent px-2 text-[9pt] outline-none focus:ring-2 focus:ring-ring/40"
                style={{ borderColor: "var(--border)", backgroundColor: "var(--input-bg)" }}
                value={form.pollInterval}
                onChange={(event) => setForm((current) => ({ ...current, pollInterval: Number(event.target.value) }))}
                disabled={saving || testing}
              >
                <option value={30}>30 giây</option>
                <option value={60}>1 phút</option>
                <option value={300}>5 phút</option>
                <option value={900}>15 phút</option>
              </select>
            </Field>
            <Field label="Múi giờ">
              <select
                className="h-8 w-full rounded-md border bg-transparent px-2 text-[9pt] outline-none focus:ring-2 focus:ring-ring/40"
                style={{ borderColor: "var(--border)", backgroundColor: "var(--input-bg)" }}
                value={form.timezone}
                onChange={(event) => setForm((current) => ({ ...current, timezone: event.target.value }))}
                disabled={saving || testing}
              >
                <option value="Asia/Ho_Chi_Minh">Việt Nam (UTC+7)</option>
                <option value="UTC">UTC</option>
              </select>
            </Field>
          </div>

          <Field label="Service-account credentials">
            <div className="flex flex-wrap items-center gap-2 rounded-md border p-3" style={{ borderColor: credentials ? "var(--success)" : "var(--border)", backgroundColor: "var(--background)" }}>
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md" style={{ backgroundColor: credentials ? "var(--success-soft)" : "var(--secondary)" }}>
                {credentials ? <Check className="h-4 w-4" style={{ color: "var(--success-fg-on-soft)" }} /> : <FileJson className="h-4 w-4" style={{ color: "var(--muted-foreground)" }} />}
              </div>
              <div className="min-w-[180px] flex-1">
                <div className="truncate text-[9pt] font-semibold">{credentialFileName || "Chưa chọn file JSON"}</div>
                <div className="truncate text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
                  {credentials ? String(credentials.client_email || "Service account") : "File chỉ được gửi bảo mật tới backend khi kiểm tra hoặc lưu."}
                </div>
              </div>
              <label className="inline-flex h-8 cursor-pointer items-center rounded-md border px-3 text-[9pt] transition hover:bg-muted" style={{ borderColor: "var(--border)" }}>
                Chọn file
                <input
                  type="file"
                  accept=".json,application/json"
                  className="hidden"
                  disabled={saving || testing}
                  onChange={(event) => { void handleCredentialFile(event.target.files?.[0]); event.target.value = ""; }}
                />
              </label>
            </div>
          </Field>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button variant="outline" className="h-9 gap-1.5 text-[9pt]" onClick={testConnection} disabled={!canSubmit || testing || saving}>
              {testing ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Unplug className="h-3.5 w-3.5" />} Kiểm tra kết nối
            </Button>
            <Button className="btn-frost-primary h-9 gap-1.5 text-[9pt] text-white" style={{ backgroundColor: "var(--accent)" }} onClick={saveConnection} disabled={!canSubmit || testing || saving}>
              {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Lưu nguồn
            </Button>
          </div>
        </section>

        <InspectionPanel inspection={inspection} testing={testing} onCopyEmail={(email) => void copyText(email)} />
      </div>

      <section className="space-y-3">
        <SectionEyebrow label="Nguồn đã kết nối" />
        <div className="overflow-hidden rounded-md border" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
          {loading ? (
            <EmptyState message="Đang tải các nguồn Google Sheets..." icon={FileSpreadsheet} />
          ) : connections.length === 0 ? (
            <EmptyState message="Chưa có nguồn Google Sheets. Thêm connection đầu tiên ở biểu mẫu phía trên." icon={FileSpreadsheet} />
          ) : (
            <div className="divide-y" style={{ borderColor: "var(--border)" }}>
              {connections.map((connection) => (
                <div key={connection.id} className="grid gap-3 p-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                  <div className="flex min-w-0 items-start gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md" style={{ backgroundColor: "var(--secondary)" }}>
                      <FileSpreadsheet className="h-4 w-4" style={{ color: "var(--accent)" }} />
                    </div>
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-[10pt] font-semibold">{connection.name}</span>
                        <ConnectionStatus status={connection.status} />
                        <span className="text-[8pt]" style={{ color: "var(--muted-foreground)" }}>mỗi {formatInterval(connection.poll_interval_seconds)}</span>
                      </div>
                      <div className="truncate font-mono text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
                        {connection.sheet_name} · {connection.service_account_email}
                      </div>
                      {connection.last_error && <div className="text-[8pt]" style={{ color: "var(--danger)" }}>{connection.last_error}</div>}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 md:justify-end">
                    <Button variant="outline" className="h-8 gap-1.5 text-[8pt]" onClick={() => void testSavedConnection(connection)} disabled={busyConnectionId !== null}>
                      {busyConnectionId === connection.id ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />} Kiểm tra
                    </Button>
                    <Button variant="outline" className="h-8 gap-1.5 text-[8pt]" render={<a href={connection.spreadsheet_url} target="_blank" rel="noreferrer" />}>
                      <ExternalLink className="h-3.5 w-3.5" /> Mở Sheet
                    </Button>
                    <Button variant="ghost" className="h-8 gap-1.5 text-[8pt]" onClick={() => void deleteConnection(connection)} disabled={busyConnectionId !== null}>
                      <Trash2 className="h-3.5 w-3.5" /> Xóa
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
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

function InspectionPanel({ inspection, testing, onCopyEmail }: { inspection: Inspection | null; testing: boolean; onCopyEmail: (email: string) => void }) {
  if (testing) {
    return (
      <aside className="flex min-h-[360px] items-center justify-center rounded-md border p-5" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
        <div className="flex flex-col items-center gap-3 text-center">
          <LoaderCircle className="h-7 w-7 animate-spin" style={{ color: "var(--accent)" }} />
          <div>
            <div className="text-[10pt] font-semibold">Đang kiểm tra Google Sheets</div>
            <div className="mt-1 text-[8pt]" style={{ color: "var(--muted-foreground)" }}>Xác thực service account, quyền truy cập và dữ liệu mẫu.</div>
          </div>
        </div>
      </aside>
    );
  }

  if (!inspection) {
    return (
      <aside className="rounded-md border p-4" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
        <SectionEyebrow label="Kiểm tra trước khi lưu" />
        <div className="space-y-2">
          <CheckRow done={false} title="Credentials" detail="Chọn file JSON của Google service account." />
          <CheckRow done={false} title="Spreadsheet" detail="Dán link Sheet và nhập đúng tên worksheet." />
          <CheckRow done={false} title="Quyền chỉnh sửa" detail="Chia sẻ Sheet cho email service account với quyền Editor." />
        </div>
        <div className="mt-4 rounded-md border p-3 text-[8pt] leading-5" style={{ borderColor: "var(--border)", backgroundColor: "var(--background)", color: "var(--muted-foreground)" }}>
          Sau khi kiểm tra, khu vực này sẽ hiển thị quyền truy cập, kích thước Sheet, header và tối đa 5 dòng dữ liệu mẫu.
        </div>
      </aside>
    );
  }

  return (
    <aside className="space-y-4 rounded-md border p-4" style={{ borderColor: inspection.can_edit ? "var(--success)" : "var(--warning)", backgroundColor: "var(--card)" }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <SectionEyebrow label="Kết quả kiểm tra" />
          <div className="text-[11pt] font-semibold">{inspection.spreadsheet_title || "Google Sheets"}</div>
          <div className="mt-0.5 text-[8pt]" style={{ color: "var(--muted-foreground)" }}>
            {inspection.sheet_name} · {inspection.row_count} dòng · {inspection.column_count} cột
          </div>
        </div>
        <ConnectionStatus status={inspection.can_edit ? "connected" : "read_only"} />
      </div>

      <div className="space-y-2">
        <CheckRow done title="Credentials hợp lệ" detail="Google đã cấp access token cho service account." />
        <CheckRow done title="Đọc được worksheet" detail={`Đã tìm thấy worksheet “${inspection.sheet_name}”.`} />
        <CheckRow done={inspection.can_edit} warning={!inspection.can_edit} title={inspection.can_edit ? "Có quyền đọc và ghi" : "Hiện chỉ có quyền đọc"} detail={inspection.can_edit ? "Có thể cập nhật trạng thái đăng ngược về Sheet." : "Hãy chia sẻ Sheet với quyền Editor trước khi lưu."} />
      </div>

      <div className="rounded-md border p-2.5" style={{ borderColor: "var(--border)", backgroundColor: "var(--background)" }}>
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="text-[8pt] font-semibold">Service account</span>
          <Button variant="ghost" size="xs" className="gap-1 text-[8pt]" onClick={() => onCopyEmail(inspection.service_account_email)}>
            <Clipboard className="h-3 w-3" /> Sao chép
          </Button>
        </div>
        <div className="truncate font-mono text-[8pt]" style={{ color: "var(--muted-foreground)" }}>{inspection.service_account_email}</div>
      </div>

      <PreviewTable inspection={inspection} />
    </aside>
  );
}

function CheckRow({ done, warning = false, title, detail }: { done: boolean; warning?: boolean; title: string; detail: string }) {
  const color = warning ? "var(--warning)" : done ? "var(--success)" : "var(--muted-foreground)";
  return (
    <div className="flex items-start gap-2.5 rounded-md border p-2.5" style={{ borderColor: "var(--border)", backgroundColor: "var(--background)" }}>
      <div className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border" style={{ borderColor: color, backgroundColor: done && !warning ? "var(--success-soft)" : "transparent" }}>
        {done && !warning && <Check className="h-2.5 w-2.5" style={{ color }} />}
      </div>
      <div className="min-w-0">
        <div className="text-[8.5pt] font-semibold" style={{ color }}>{title}</div>
        <div className="mt-0.5 text-[8pt] leading-4" style={{ color: "var(--muted-foreground)" }}>{detail}</div>
      </div>
    </div>
  );
}

function PreviewTable({ inspection }: { inspection: Inspection }) {
  if (inspection.headers.length === 0) {
    return <div className="rounded-md border p-3 text-[8pt]" style={{ borderColor: "var(--warning)", color: "var(--warning-fg-on-soft)", backgroundColor: "var(--warning-soft)" }}>Worksheet đang trống hoặc chưa có hàng header.</div>;
  }
  return (
    <div className="space-y-1.5">
      <div className="text-[8pt] font-semibold">Preview dữ liệu</div>
      <div className="max-h-[190px] overflow-auto rounded-md border" style={{ borderColor: "var(--border)" }}>
        <table className="min-w-full border-collapse text-left text-[8pt]">
          <thead className="sticky top-0 z-[1]" style={{ backgroundColor: "var(--surface-dark)", color: "white" }}>
            <tr>{inspection.headers.map((header, index) => <th key={`${header}-${index}`} className="whitespace-nowrap border-r px-2 py-1.5 font-semibold" style={{ borderColor: "rgba(255,255,255,0.1)" }}>{header || `Cột ${index + 1}`}</th>)}</tr>
          </thead>
          <tbody>
            {inspection.preview_rows.length === 0 ? (
              <tr><td colSpan={inspection.headers.length} className="px-2 py-5 text-center" style={{ color: "var(--muted-foreground)" }}>Chưa có dòng dữ liệu.</td></tr>
            ) : inspection.preview_rows.map((row, rowIndex) => (
              <tr key={rowIndex} className={rowIndex % 2 ? "frost-table-row-odd" : "frost-table-row-even"}>
                {inspection.headers.map((_, cellIndex) => <td key={cellIndex} className="max-w-44 truncate border-r border-t px-2 py-1.5" style={{ borderColor: "var(--border)" }} title={row[cellIndex] || ""}>{row[cellIndex] || ""}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ConnectionStatus({ status }: { status: string }) {
  const className = status === "connected" ? "status-badge status-badge--success" : status === "read_only" ? "status-badge status-badge--warning" : status === "error" ? "status-badge status-badge--danger" : "status-badge status-badge--default";
  const label = status === "connected" ? "Sẵn sàng" : status === "read_only" ? "Chỉ đọc" : status === "error" ? "Lỗi" : status;
  return <span className={className}>{label}</span>;
}

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value);
    toast.success("Đã sao chép email service account");
  } catch {
    toast.error("Không sao chép được, hãy chọn và sao chép thủ công");
  }
}

function formatInterval(seconds: number) {
  if (seconds % 60 === 0) return `${seconds / 60} phút`;
  return `${seconds} giây`;
}
