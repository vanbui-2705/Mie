"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { SectionEyebrow } from "@/components/shared/SectionEyebrow";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api-client";
import type { AppSettings } from "@/types";

const EMPTY: AppSettings = {
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

function mapSettings(row: Record<string, unknown>): AppSettings {
  return {
    ...EMPTY,
    kiotAuthToken: "",
    kiotAuthTokenMasked: String(row.kiot_auth_token_masked ?? ""),
    proxyApiKeys: "",
    getNewProxyUrl: String(row.get_new_url_template ?? EMPTY.getNewProxyUrl),
    getCurrentProxyUrl: String(row.get_current_url_template ?? EMPTY.getCurrentProxyUrl),
    usesPerProxy: Number(row.uses_per_proxy ?? EMPTY.usesPerProxy),
    checkInterval: Number(row.proxy_check_interval ?? EMPTY.checkInterval),
    interactionThreads: Number(row.interaction_threads ?? EMPTY.interactionThreads),
    postsPerUid: Number(row.posts_per_uid ?? EMPTY.postsPerUid),
    delayMin: Number(row.delay_min_seconds ?? EMPTY.delayMin),
    delayMax: Number(row.delay_max_seconds ?? EMPTY.delayMax),
    delayEveryRounds: Number(row.delay_every_rounds ?? EMPTY.delayEveryRounds),
  };
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [autoCheckOnImport, setAutoCheckOnImport] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const data = await apiFetch<Record<string, unknown>>("/api/settings");
        if (!cancelled && data) setSettings(mapSettings(data));
      } catch { /* use defaults */ } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await apiFetch("/api/settings", {
        method: "PUT",
        body: {
          interaction_threads: settings.interactionThreads,
          posts_per_uid: settings.postsPerUid,
          delay_min_seconds: settings.delayMin,
          delay_max_seconds: settings.delayMax,
          delay_every_rounds: settings.delayEveryRounds,
          uses_per_proxy: settings.usesPerProxy,
          proxy_check_interval: settings.checkInterval,
          get_new_url_template: settings.getNewProxyUrl,
          get_current_url_template: settings.getCurrentProxyUrl,
          kiot_auth_token: "",
        },
      });
      setSaved(true);
      toast.success("Đã lưu cài đặt");
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      if (e instanceof Error) toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setSettings(EMPTY);
    setAutoCheckOnImport(false);
    toast("Đã đặt lại về mặc định");
  };

  const update = (patch: Partial<AppSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  };

  if (loading) {
    return (
      <div className="space-y-5">
        <h1 className="text-lg font-semibold" style={{ color: "var(--foreground)" }}>
          Cài đặt
        </h1>
        <p className="text-[9pt]" style={{ color: "var(--muted-foreground)" }}>
          Đang tải...
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--foreground)" }}>
          Cài đặt
        </h1>
        <p className="text-[9pt] mt-0.5" style={{ color: "var(--muted-foreground)" }}>
          Cấu hình delay, luồng, hành vi mặc định
        </p>
      </div>

      {/* Delay defaults */}
      <div
        className="rounded-lg border"
        style={{ backgroundColor: "var(--card)", borderColor: "var(--border)" }}
      >
        <div className="p-4">
          <SectionEyebrow label="Delay mặc định" />
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                Delay từ (giây)
              </Label>
              <Input
                type="number"
                value={settings.delayMin}
                onChange={(e) => update({ delayMin: parseInt(e.target.value) || 0 })}
                className="h-8 w-24 text-[9pt]"
                disabled={saving}
                min={0}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                Delay đến (giây)
              </Label>
              <Input
                type="number"
                value={settings.delayMax}
                onChange={(e) => update({ delayMax: parseInt(e.target.value) || 0 })}
                className="h-8 w-24 text-[9pt]"
                disabled={saving}
                min={0}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                Sau mỗi N vòng
              </Label>
              <Input
                type="number"
                value={settings.delayEveryRounds}
                onChange={(e) => update({ delayEveryRounds: parseInt(e.target.value) || 1 })}
                className="h-8 w-24 text-[9pt]"
                disabled={saving}
                min={1}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Behavior */}
      <div
        className="rounded-lg border"
        style={{ backgroundColor: "var(--card)", borderColor: "var(--border)" }}
      >
        <div className="p-4">
          <SectionEyebrow label="Hành vi" />
          <div className="flex flex-col gap-4 max-w-xl">
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                Luồng song song tối đa
              </Label>
              <Input
                type="number"
                value={settings.interactionThreads}
                onChange={(e) => update({ interactionThreads: parseInt(e.target.value) || 1 })}
                className="h-8 w-24 text-[9pt]"
                disabled={saving}
                min={1}
                max={50}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-[9pt] font-medium" style={{ color: "var(--muted-foreground)" }}>
                Post mỗi UID
              </Label>
              <Input
                type="number"
                value={settings.postsPerUid}
                onChange={(e) => update({ postsPerUid: parseInt(e.target.value) || 1 })}
                className="h-8 w-24 text-[9pt]"
                disabled={saving}
                min={1}
                max={20}
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="autoCheck"
                checked={autoCheckOnImport}
                onCheckedChange={(checked) => setAutoCheckOnImport(checked === true)}
                disabled={saving}
              />
              <Label
                htmlFor="autoCheck"
                className="text-[9pt] font-medium cursor-pointer select-none"
                style={{ color: "var(--text)" }}
              >
                Tự động kiểm tra token profile khi nhập
              </Label>
            </div>
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={handleSave}
          disabled={saving}
          className="btn-frost-primary h-8 flex-1 px-4 text-[9pt] font-medium sm:flex-none"
          style={{ backgroundColor: "var(--accent)", color: "#fff" }}
        >
          Lưu cài đặt
        </Button>
        <Button
          variant="outline"
          onClick={handleReset}
          className="h-8 flex-1 px-4 text-[9pt] sm:flex-none"
          style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
        >
          Đặt lại
        </Button>
        {saved && (
          <span className="text-[9pt] self-center ml-1" style={{ color: "var(--success)" }}>
            Đã lưu
          </span>
        )}
      </div>
    </div>
  );
}
