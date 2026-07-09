"use client";

import { useState, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { ProxyGrid } from "@/components/proxy/ProxyGrid";
import { ProxyControls } from "@/components/proxy/ProxyControls";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { Globe2, Trash2, Play, Square } from "lucide-react";
import { apiFetch } from "@/lib/api-client";
import { toast } from "sonner";
import type { ProxyKeyState, AppSettings } from "@/types";

const EMPTY_SETTINGS: AppSettings = {
  kiotAuthToken: "",
  kiotAuthTokenMasked: "",
  proxyApiKeys: "",
  getNewProxyUrl: "https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}",
  getCurrentProxyUrl: "https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}",
  usesPerProxy: 4,
  checkInterval: 5,
  interactionThreads: 5,
  postsPerUid: 1,
  delayMin: 0,
  delayMax: 0,
  delayEveryRounds: 1,
};

type ApiSettings = Record<string, unknown>;
type ApiProxyKey = Record<string, unknown>;

function mapSettings(row: ApiSettings): AppSettings {
  return {
    ...EMPTY_SETTINGS,
    // Masked value — display only. Never write this back as the real token.
    kiotAuthToken: "",
    kiotAuthTokenMasked: String(row.kiot_auth_token_masked ?? ""),
    proxyApiKeys: "",
    getNewProxyUrl: String(row.get_new_url_template ?? EMPTY_SETTINGS.getNewProxyUrl),
    getCurrentProxyUrl: String(row.get_current_url_template ?? EMPTY_SETTINGS.getCurrentProxyUrl),
    usesPerProxy: Number(row.uses_per_proxy ?? EMPTY_SETTINGS.usesPerProxy),
    checkInterval: Number(row.proxy_check_interval ?? EMPTY_SETTINGS.checkInterval),
    interactionThreads: Number(row.interaction_threads ?? EMPTY_SETTINGS.interactionThreads),
    postsPerUid: Number(row.posts_per_uid ?? EMPTY_SETTINGS.postsPerUid),
    delayMin: Number(row.delay_min_seconds ?? EMPTY_SETTINGS.delayMin),
    delayMax: Number(row.delay_max_seconds ?? EMPTY_SETTINGS.delayMax),
    delayEveryRounds: Number(row.delay_every_rounds ?? EMPTY_SETTINGS.delayEveryRounds),
  };
}

function mapProxy(row: ApiProxyKey): ProxyKeyState {
  const endpoint = row.endpoint as ProxyKeyState["endpoint"] | null;
  return {
    id: Number(row.id ?? 0),
    maskedApiKey: String(row.masked_api_key ?? row.maskedApiKey ?? ""),
    currentProxy: String(row.current_proxy ?? row.currentProxy ?? ""),
    remainingUses: Number(row.remaining_uses ?? row.remainingUses ?? 0),
    reservedUses: Number(row.reserved_uses ?? row.reservedUses ?? 0),
    status: String(row.status ?? "Stopped") as ProxyKeyState["status"],
    ipExpiresAt: String(row.ip_expires_at ?? row.ipExpiresAt ?? ""),
    lastError: (row.last_error ?? row.lastError ?? null) as string | null,
    display: String(row.current_proxy ?? row.currentProxy ?? endpoint?.display ?? ""),
    endpoint,
    // apiKey is the masked display string — the raw key is never returned
    apiKey: String(row.masked_api_key ?? row.apiKey ?? ""),
  };
}

export default function ProxyPage() {
  const [config, setConfig] = useState<AppSettings>(EMPTY_SETTINGS);
  const [proxyKeys, setProxyKeys] = useState<ProxyKeyState[]>([]);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [settings, keys] = await Promise.all([
        apiFetch<ApiSettings>("/api/settings").catch(() => EMPTY_SETTINGS as unknown as ApiSettings),
        apiFetch<ApiProxyKey[]>("/api/proxy/status").catch(() => []),
      ]);
      if (settings) setConfig(mapSettings(settings));
      setProxyKeys((keys ?? []).map(mapProxy));
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleSave = async () => {
    setSaving(true);
    try {
      // Only send non-empty auth token if the user has typed a raw one;
      // otherwise leave it empty so the backend keeps the existing encrypted value.
      const tokenToSave = config.kiotAuthToken || "";
      await apiFetch("/api/settings", {
        method: "PUT",
        body: {
          kiot_auth_token: tokenToSave,
          get_new_url_template: config.getNewProxyUrl,
          get_current_url_template: config.getCurrentProxyUrl,
          uses_per_proxy: config.usesPerProxy,
          proxy_check_interval: config.checkInterval,
          interaction_threads: config.interactionThreads,
          posts_per_uid: config.postsPerUid,
          delay_min_seconds: config.delayMin,
          delay_max_seconds: config.delayMax,
          delay_every_rounds: config.delayEveryRounds,
        },
      });
      if (config.proxyApiKeys.trim()) {
        await apiFetch("/api/proxy/keys/import", {
          method: "POST",
          body: { raw_text: config.proxyApiKeys },
        });
      }
      toast.success("Đã lưu cấu hình proxy.");
      await loadAll();
    } catch (e) {
      if (e instanceof Error) toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleStart = async () => {
    try {
      await apiFetch("/api/proxy/monitor/start", {
        method: "POST",
        body: {
          auth_token: config.kiotAuthToken || undefined,
          get_new_url: config.getNewProxyUrl,
          get_current_url: config.getCurrentProxyUrl,
          uses_per_proxy: config.usesPerProxy,
          check_interval: config.checkInterval,
        },
      });
      toast.success("Đã bắt đầu quản lý proxy.");
      setRunning(true);
      await loadAll();
    } catch (e) {
      if (e instanceof Error) toast.error(e.message);
    }
  };

  const handleStop = async () => {
    try {
      await apiFetch("/api/proxy/monitor/stop", { method: "POST" });
      toast.success("Đã dừng quản lý proxy.");
      setRunning(false);
      await loadAll();
    } catch (e) {
      if (e instanceof Error) toast.error(e.message);
    }
  };

  const handleDelete = async () => {
    try {
      await apiFetch("/api/proxy/keys", { method: "DELETE" });
      toast.success("Đã xóa tất cả proxy.");
      setProxyKeys([]);
    } catch (e) {
      if (e instanceof Error) toast.error(e.message);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>
            Quản lý Proxy
          </h1>
          <p className="text-[9pt] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
            Cấu hình và giám sát KiotProxy
          </p>
        </div>
      </div>

      <ProxyControls
        config={config}
        onConfigChange={(patch) => setConfig((p) => ({ ...p, ...patch }))}
        onSave={handleSave}
        saving={saving}
        running={running}
        onStart={handleStart}
        onStop={handleStop}
        onDelete={handleDelete}
        deleting={deleting}
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionEyebrow label="Danh sách proxy" />
        <div className="flex flex-wrap gap-2">
          {!running ? (
            <Button
              onClick={handleStart}
              className="btn-frost-primary h-8 px-4 text-[9pt] gap-1.5 text-white"
              style={{ backgroundColor: "var(--accent)" }}
            >
              <Play className="w-3.5 h-3.5" /> Bắt đầu proxy
            </Button>
          ) : (
            <Button
              onClick={handleStop}
              variant="outline"
              className="h-8 px-4 text-[9pt] gap-1.5"
              style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
            >
              <Square className="w-3.5 h-3.5" /> Dừng
            </Button>
          )}
          <Button
            variant="ghost"
            onClick={handleDelete}
            disabled={deleting || running}
            className="h-8 px-3 text-[9pt] gap-1.5"
            style={{ color: "var(--danger)" }}
          >
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <p className="text-[9pt]" style={{ color: "var(--muted-foreground)" }}>Đang tải...</p>
        </div>
      ) : (
        <ProxyGrid keys={proxyKeys} />
      )}
    </div>
  );
}
