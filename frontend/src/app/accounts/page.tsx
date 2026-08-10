"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { BulkImportDialog } from "@/features/accounts";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { EmptyState } from "@/components/shared/EmptyState";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { TargetDeleteButton } from "@/components/shared/TargetDeleteButton";
import { apiFetch } from "@/lib/api-client";
import { Download, FileText, MonitorUp, RefreshCw, RotateCw, ShieldCheck, Users } from "lucide-react";
import { toast } from "sonner";
import type React from "react";

type FacebookAccount = {
  id: string;
  uid: string;
  name: string;
  masked_token: string;
  token_status: string;
  token_expires_at: string | null;
  token_last_refreshed_at: string | null;
  token_is_long_lived: boolean;
  token_refresh_due: boolean;
  last_error: string;
  last_checked_at: string | null;
  browser_status: string;
  browser_last_checked_at: string | null;
  browser_last_error: string;
  created_at: string | null;
};

type FacebookPage = {
  id: string;
  facebook_account_id: string;
  page_id: string;
  page_name: string;
  category: string;
  permissions: string[] | Record<string, unknown>;
  status: string;
  created_at: string | null;
};

type ImportResult = {
  total: number;
  added: number;
  duplicate: number;
  exchanged_long_lived?: number;
  exchange_failed?: number;
  names_resolved?: number;
  errors: string[];
};

function tokenStatusLabel(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "da nap") return "Đã nạp";
  if (normalized === "da refresh token") return "Đã refresh";
  if (normalized === "chua kiem tra") return "Chưa kiểm tra";
  return status;
}

function permissionText(value: FacebookPage["permissions"]) {
  if (Array.isArray(value)) return value.join(", ");
  if (!value) return "";
  return Object.values(value).join(", ");
}

function browserStatusLabel(status: string) {
  if (status === "not_configured") return "Chưa login";
  if (status === "login_required") return "Cần connect";
  if (status === "logged_in") return "Browser ready";
  if (status === "extension_online") return "Extension online";
  if (status === "extension_offline") return "Extension offline";
  if (status === "expired") return "Hết phiên";
  if (status === "checkpoint") return "Checkpoint";
  if (status === "error") return "Lỗi browser";
  return status || "Chưa login";
}

function tokenExpiryLabel(account: FacebookAccount) {
  if (!account.token_expires_at) return account.token_is_long_lived ? "Long-lived" : "Chưa rõ hạn";
  const expires = new Date(account.token_expires_at);
  const diffMs = expires.getTime() - Date.now();
  const days = Math.ceil(diffMs / 86400000);
  if (days < 0) return "Đã hết hạn";
  if (days === 0) return "Hết hạn hôm nay";
  const prefix = account.token_is_long_lived ? "LL" : "Token";
  return `${prefix} còn ${days} ngày`;
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<FacebookAccount[]>([]);
  const [pages, setPages] = useState<FacebookPage[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState<string>("");
  const [importOpen, setImportOpen] = useState(false);
  const [importSummary, setImportSummary] = useState<ImportResult | null>(null);

  const selectedAccount = useMemo(
    () => accounts.find((account) => account.id === selectedAccountId) ?? accounts[0],
    [accounts, selectedAccountId]
  );

  const visiblePages = useMemo(() => {
    if (!selectedAccount) return pages;
    return pages.filter((page) => page.facebook_account_id === selectedAccount.id);
  }, [pages, selectedAccount]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [accountRows, pageRows] = await Promise.all([
        apiFetch<FacebookAccount[]>("/api/facebook-accounts"),
        apiFetch<FacebookPage[]>("/api/facebook-pages"),
      ]);
      setAccounts(accountRows ?? []);
      setPages(pageRows ?? []);
      setSelectedAccountId((current) => current || accountRows?.[0]?.id || "");
    } catch (error) {
      if (error instanceof Error) toast.error(error.message);
      setAccounts([]);
      setPages([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => void loadAll(), 0);
    return () => clearTimeout(timer);
  }, [loadAll]);

  const handleImport = async (text: string) => {
    const result = await apiFetch<ImportResult>("/api/facebook-accounts/import", {
      method: "POST",
      body: { raw_text: text },
    });
    setImportSummary(result);
    const errorSuffix = result.errors.length ? `, ${result.errors.length} lỗi định dạng` : "";
    const exchangeSuffix = result.exchanged_long_lived
      ? `, đổi long-lived ${result.exchanged_long_lived}`
      : "";
    const exchangeFailSuffix = result.exchange_failed
      ? `, ${result.exchange_failed} token chưa đổi long-lived`
      : "";
    const nameSuffix = result.names_resolved ? `, lấy tên ${result.names_resolved}` : "";
    toast.success(`Đã nhập ${result.total} account: thêm ${result.added}, refresh ${result.duplicate}${nameSuffix}${exchangeSuffix}${exchangeFailSuffix}${errorSuffix}.`);
    await loadAll();
  };

  const handleTargetDeleted = useCallback(async () => {
    setSelectedAccountId("");
    await loadAll();
  }, [loadAll]);

  const handleCheck = async (account: FacebookAccount) => {
    setWorkingId(account.id);
    try {
      await apiFetch(`/api/facebook-accounts/${account.id}/check`, { method: "POST", body: {} });
      toast.success(`Đã kiểm tra token UID ${account.uid}.`);
      await loadAll();
    } catch (error) {
      if (error instanceof Error) toast.error(error.message);
    } finally {
      setWorkingId("");
    }
  };

  const handleSyncPages = async (account: FacebookAccount) => {
    setWorkingId(account.id);
    try {
      const result = await apiFetch<{ added: number; updated: number }>(
        `/api/facebook-accounts/${account.id}/sync-pages`,
        { method: "POST", body: {} }
      );
      toast.success(`Đã đồng bộ ${result.added} page mới, cập nhật ${result.updated} page.`);
      await loadAll();
      setSelectedAccountId(account.id);
    } catch (error) {
      if (error instanceof Error) toast.error(error.message);
    } finally {
      setWorkingId("");
    }
  };

  const handleConnectBrowser = async (account: FacebookAccount) => {
    setWorkingId(account.id);
    try {
      const result = await apiFetch<{
        session_url: string;
        message: string;
        remote_username?: string;
        remote_password?: string;
      }>(
        `/api/facebook-accounts/${account.id}/connect-browser/start`,
        { method: "POST", body: {} }
      );
      if (result.session_url) {
        window.open(result.session_url, "_blank", "noopener,noreferrer");
        const credentialHint = result.remote_password
          ? ` Kasm: ${result.remote_username || "kasm_user"} / ${result.remote_password}.`
          : "";
        toast.success(`Đã mở trình duyệt kết nối.${credentialHint} Đăng nhập Facebook một lần rồi bấm Kiểm tra trình duyệt. Các tác vụ sau đó sẽ chạy ẩn.`);
      } else {
        toast.error(result.message || "Chưa cấu hình browser connect.");
      }
      await loadAll();
    } catch (error) {
      if (error instanceof Error) toast.error(error.message);
    } finally {
      setWorkingId("");
    }
  };

  const handleBrowserStatus = async (account: FacebookAccount) => {
    setWorkingId(account.id);
    try {
      const result = await apiFetch<{ status: string; last_error: string }>(
        `/api/facebook-accounts/${account.id}/connect-browser/status`
      );
      if (result.status === "logged_in") toast.success("Browser profile đã sẵn sàng. Task sẽ chạy ẩn bằng Playwright.");
      else toast.message(result.last_error || browserStatusLabel(result.status));
      await loadAll();
    } catch (error) {
      if (error instanceof Error) toast.error(error.message);
    } finally {
      setWorkingId("");
    }
  };

  const liveCount = accounts.filter((account) => account.token_status.toLowerCase() === "live").length;
  const errorCount = accounts.filter((account) => ["die", "checkpoint", "token out"].includes(account.token_status.toLowerCase())).length;
  const browserReadyCount = accounts.filter((account) => account.browser_status === "logged_in").length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>
            Facebook Accounts
          </h1>
          <p className="text-[9pt] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
            Quản lý UID|TOKEN, Fanpage và connector. Extension online thì task chạy trên browser thật của người dùng.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => setImportOpen(true)} className="h-8 px-3 text-[9pt] gap-1.5">
            <Download className="w-3.5 h-3.5" /> Nhập UID|TOKEN
          </Button>
          <Button variant="outline" onClick={loadAll} disabled={loading} className="h-8 px-3 text-[9pt] gap-1.5">
            <RefreshCw className={"w-3.5 h-3.5 " + (loading ? "animate-spin" : "")} /> Làm mới
          </Button>
        </div>
      </div>

      {importSummary && (
        <div
          className="rounded-md border px-3 py-2 text-[9pt]"
          style={{ borderColor: "var(--border)", backgroundColor: "var(--card)", color: "var(--foreground)" }}
        >
          Import gần nhất: {importSummary.total} account, thêm mới {importSummary.added}, cập nhật token trùng {importSummary.duplicate}
          {importSummary.errors.length > 0 && (
            <span style={{ color: "var(--danger)" }}> · {importSummary.errors.length} dòng lỗi định dạng</span>
          )}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Metric icon={Users} label="Facebook Account" value={accounts.length} />
        <Metric icon={ShieldCheck} label="Token live" value={liveCount} />
        <Metric icon={FileText} label="Fanpage đã sync" value={pages.length} />
        <Metric icon={MonitorUp} label="Browser ready" value={browserReadyCount} />
        <Metric icon={RotateCw} label="Cần xử lý" value={errorCount} danger />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <section>
          <SectionEyebrow label="Danh sách Facebook Account" />
          <div className="overflow-x-auto rounded-md border" style={{ borderColor: "var(--border)" }}>
            <table className="w-full text-[9pt]" style={{ borderCollapse: "collapse", minWidth: 820 }}>
              <thead>
                <tr style={{ height: 32, backgroundColor: "var(--surface-dark)", color: "var(--surface-dark-fg)" }}>
                  <th className="text-center font-semibold px-2" style={{ width: 46 }}>STT</th>
                  <th className="font-semibold px-2 text-left">UID</th>
                  <th className="font-semibold px-2 text-left">Tên</th>
                  <th className="font-semibold px-2 text-left">Token</th>
                  <th className="font-semibold px-2 text-left">Token</th>
                  <th className="font-semibold px-2 text-left">Hạn token</th>
                  <th className="font-semibold px-2 text-left">Browser</th>
                  <th className="font-semibold px-2 text-right" style={{ width: 300 }}>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  Array.from({ length: 4 }).map((_, index) => (
                    <tr key={index} style={{ height: 34 }}>
                      <td colSpan={8}><div className="skeleton-row w-full" /></td>
                    </tr>
                  ))
                ) : accounts.length === 0 ? (
                  <tr>
                    <td colSpan={8}>
                      <EmptyState message="Chưa có Facebook Account. Hãy nhập UID|TOKEN để bắt đầu." />
                    </td>
                  </tr>
                ) : (
                  accounts.map((account, index) => {
                    const active = selectedAccount?.id === account.id;
                    return (
                      <tr
                        key={account.id}
                        onClick={() => setSelectedAccountId(account.id)}
                        style={{
                          height: 36,
                          backgroundColor: active ? "var(--accent-soft)" : index % 2 === 0 ? "var(--card)" : "var(--surface-row)",
                          borderBottom: "1px solid var(--divider)",
                          cursor: "pointer",
                        }}
                      >
                        <td className="text-center px-2" style={{ color: "var(--muted-foreground)" }}>{index + 1}</td>
                        <td className="px-2 font-mono" style={{ fontFamily: "var(--font-mono)" }}>{account.uid}</td>
                        <td className="px-2">{account.name || "Chưa lấy tên"}</td>
                        <td className="px-2 font-mono" style={{ fontFamily: "var(--font-mono)" }}>{account.masked_token}</td>
                        <td className="px-2"><StatusBadge status={tokenStatusLabel(account.token_status)} /></td>
                        <td className="px-2" title={account.token_last_refreshed_at ? `Refresh: ${new Date(account.token_last_refreshed_at).toLocaleString("vi-VN")}` : ""}>
                          <StatusBadge status={account.token_refresh_due ? "Sắp refresh" : tokenExpiryLabel(account)} />
                        </td>
                        <td className="px-2" title={account.browser_last_error || ""}><StatusBadge status={browserStatusLabel(account.browser_status)} /></td>
                        <td className="px-2">
                          <div className="flex justify-end gap-1.5">
                             <Button
                              variant="outline"
                              className="h-7 px-2 text-[8.5pt]"
                              disabled={workingId === account.id}
                              onClick={(event) => {
                                event.stopPropagation();
                                handleCheck(account);
                              }}
                            >
                              Check
                            </Button>
                            <Button
                              className="h-7 px-2 text-[8.5pt] text-white"
                              style={{ backgroundColor: "var(--accent)" }}
                              disabled={workingId === account.id}
                              onClick={(event) => {
                                event.stopPropagation();
                                handleSyncPages(account);
                              }}
                            >
                              Sync page
                            </Button>
                            <Button
                              variant="outline"
                              className="h-7 px-2 text-[8.5pt]"
                              disabled={workingId === account.id}
                              onClick={(event) => {
                                event.stopPropagation();
                                handleConnectBrowser(account);
                              }}
                            >
                              Connect Facebook
                            </Button>
                            <Button
                              variant="outline"
                              className="h-7 px-2 text-[8.5pt]"
                              disabled={workingId === account.id}
                              onClick={(event) => {
                                event.stopPropagation();
                                handleBrowserStatus(account);
                              }}
                            >
                               Check browser
                             </Button>
                             <TargetDeleteButton
                               target={{ id: `personal:${account.id}`, name: account.name || account.uid, type: "personal" }}
                               disabled={workingId === account.id}
                               onDeleted={handleTargetDeleted}
                             />
                           </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <SectionEyebrow label="Fanpage theo account" />
          <div className="rounded-md border overflow-hidden" style={{ borderColor: "var(--border)", backgroundColor: "var(--card)" }}>
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3" style={{ borderBottom: "1px solid var(--divider)" }}>
              <div className="min-w-0">
                <div className="text-[9pt] font-semibold" style={{ color: "var(--foreground)" }}>
                  {selectedAccount ? selectedAccount.name || selectedAccount.uid : "Chưa chọn account"}
                </div>
                <div className="text-[8.5pt] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
                  {visiblePages.length} Fanpage khả dụng
                </div>
              </div>
              {selectedAccount && <StatusBadge status={tokenStatusLabel(selectedAccount.token_status)} />}
            </div>
            <div className="max-h-[520px] overflow-auto">
              {visiblePages.length === 0 ? (
                <EmptyState message="Chưa có Fanpage. Chọn account rồi bấm Sync page." />
              ) : (
                <table className="w-full text-[9pt]" style={{ borderCollapse: "collapse", minWidth: 560 }}>
                  <thead>
                    <tr style={{ height: 30, backgroundColor: "var(--surface-row)", color: "var(--foreground)" }}>
                      <th className="text-left font-semibold px-3">Page</th>
                      <th className="text-left font-semibold px-3">Page ID</th>
                       <th className="text-left font-semibold px-3">Quyền</th>
                       <th className="text-right font-semibold px-3">Thao tác</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visiblePages.map((page, index) => (
                      <tr key={page.id} style={{ height: 34, borderBottom: "1px solid var(--divider)", backgroundColor: index % 2 === 0 ? "var(--card)" : "var(--surface-row)" }}>
                        <td className="px-3">
                          <div className="font-medium" style={{ color: "var(--foreground)" }}>{page.page_name}</div>
                          <div className="text-[8pt]" style={{ color: "var(--muted-foreground)" }}>{page.category || "Không có category"}</div>
                        </td>
                        <td className="px-3 font-mono" style={{ fontFamily: "var(--font-mono)" }}>{page.page_id}</td>
                         <td className="px-3" title={permissionText(page.permissions)} style={{ maxWidth: 170, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--muted-foreground)" }}>
                           {permissionText(page.permissions) || "Chưa rõ"}
                         </td>
                         <td className="px-3 text-right">
                           <TargetDeleteButton
                             target={{ id: `page:${page.id}`, name: page.page_name, type: "page" }}
                             onDeleted={loadAll}
                           />
                         </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </section>
      </div>

      <BulkImportDialog open={importOpen} onClose={() => setImportOpen(false)} onImport={handleImport} />
    </div>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
  danger = false,
}: {
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  label: string;
  value: number;
  danger?: boolean;
}) {
  return (
    <div className="rounded-md border px-4 py-3 flex items-center gap-3" style={{ backgroundColor: "var(--card)", borderColor: "var(--border)" }}>
      <div className="h-8 w-8 rounded-md flex items-center justify-center" style={{ backgroundColor: danger ? "var(--danger-soft)" : "var(--accent-soft)" }}>
        <Icon className="w-4 h-4" style={{ color: danger ? "var(--danger)" : "var(--accent)" }} />
      </div>
      <div>
        <div className="text-[8.5pt]" style={{ color: "var(--muted-foreground)" }}>{label}</div>
        <div className="text-base font-semibold" style={{ color: "var(--foreground)" }}>{value}</div>
      </div>
    </div>
  );
}
