"use client";

import type {
  FacebookPostTarget,
  GoogleSheetConnection,
  PublicationHealth,
  PublicationJob,
  RentalConfig,
  RentalConfigInput,
  RentalPublicationJob,
  RentalRoom,
  SheetCampaign,
  SheetCampaignInput,
  SheetSourceItem,
} from "@/types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "flowmeta_access_token";
const USER_KEY = "flowmeta_user";

export function getApiBase() {
  if (typeof window === "undefined") return API_BASE;
  try {
    const configuredUrl = new URL(API_BASE, window.location.origin);
    const configuredIsLocal = configuredUrl.hostname === "localhost" || configuredUrl.hostname === "127.0.0.1";
    const browserIsLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    return configuredIsLocal && !browserIsLocal ? window.location.origin : API_BASE;
  } catch {
    return API_BASE;
  }
}

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`API error ${status}`);
  }
}

export type AuthUser = {
  id: string;
  username: string;
  role: string;
  roles?: string[];
  permissions?: string[];
  email?: string;
  status?: string;
};

export function getAuthToken() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function setAuthSession(token: string, user: AuthUser) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuthSession() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

function errorDetail(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("detail" in body)) return null;
  const detail = (body as Record<string, unknown>).detail;
  return typeof detail === "string" ? detail : null;
}

function normalizeError(status: number, body: unknown, path: string): string {
  const detail = errorDetail(body);
  if (status === 401 && path === "/api/auth/login") {
    return detail === "Invalid username or password"
      ? "Sai tài khoản hoặc mật khẩu."
      : (detail || "Đăng nhập thất bại.");
  }
  if (path === "/api/auth/login") {
    const loginMessages: Record<string, string> = {
      "Admin password is not configured": "Tài khoản quản trị chưa được cấu hình mật khẩu.",
      "User account is disabled": "Tài khoản đã bị vô hiệu hóa.",
    };
    return (detail && loginMessages[detail]) || detail || `Đăng nhập thất bại (${status}).`;
  }
  if (path === "/api/auth/register") {
    const registerMessages: Record<string, string> = {
      "Valid email is required": "Email không hợp lệ.",
      "Username must be at least 3 characters": "Tên đăng nhập phải có ít nhất 3 ký tự.",
      "Password must be at least 8 characters": "Mật khẩu phải có ít nhất 8 ký tự.",
      "Email or username already exists": "Email hoặc tên đăng nhập đã tồn tại.",
    };
    return (detail && registerMessages[detail]) || detail || `Đăng ký thất bại (${status}).`;
  }
  if (status === 401) return "Phiên đăng nhập hết hạn, vui lòng đăng nhập lại.";
  if (status === 422 && body && typeof body === "object" && "detail" in body) {
    const detail = (body as Record<string, unknown>).detail;
    if (Array.isArray(detail) && detail.length > 0 && typeof detail[0] === "object") {
      return ((detail[0] as Record<string, unknown>).msg as string) ?? "Dữ liệu không hợp lệ.";
    }
    if (typeof detail === "string") return detail;
    return "Dữ liệu không hợp lệ.";
  }
  if (status >= 500) return "Lỗi máy chủ nội bộ.";
  if (detail) return detail;
  return `Yêu cầu thất bại (${status}).`;
}

export async function apiFetch<T>(
  path: string,
  options?: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    /** Origin to call instead of the Face API — Flow Studio runs on its own port. */
    base?: string;
  },
): Promise<T> {
  const token = getAuthToken();
  const isFormData = typeof FormData !== "undefined" && options?.body instanceof FormData;
  let res: Response;
  try {
    res = await fetch(`${options?.base ?? getApiBase()}${path}`, {
      method: options?.method ?? "GET",
      headers: {
        ...(!isFormData ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: options?.body === undefined
        ? undefined
        : isFormData
          ? options.body as FormData
          : JSON.stringify(options.body),
      signal: options?.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Không thể kết nối tới máy chủ. Vui lòng kiểm tra kết nối và thử lại.", { cause: error });
  }

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    const isLoginRequest = path === "/api/auth/login";
    if (res.status === 401 && !isLoginRequest && typeof window !== "undefined" && window.location.pathname !== "/login") {
      clearAuthSession();
      window.location.href = "/login";
    }
    throw new Error(normalizeError(res.status, body, path), { cause: new ApiError(res.status, body) });
  }

  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    return text as unknown as T;
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(path, { method: "GET", signal });
}

export async function apiPost<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(path, { method: "POST", body, signal });
}

export async function apiPatch<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(path, { method: "PATCH", body, signal });
}

export async function apiPut<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(path, { method: "PUT", body, signal });
}

export async function apiDelete<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE", body, signal });
}

// ─── Rental (Đăng trọ tự động) ──────────────────────────────────────────────

export function listSheetCampaigns(signal?: AbortSignal) {
  return apiGet<SheetCampaign[]>("/api/sheet-campaigns", signal);
}
export function createSheetCampaign(body: SheetCampaignInput) {
  return apiPost<SheetCampaign>("/api/sheet-campaigns", body);
}
export function updateSheetCampaign(id: string, body: Partial<Omit<SheetCampaignInput, "connection_id">>) {
  return apiPut<SheetCampaign>(`/api/sheet-campaigns/${id}`, body);
}
export function deleteSheetCampaign(id: string) {
  return apiDelete<{ deleted: boolean; id: string }>(`/api/sheet-campaigns/${id}`);
}
export function syncSheetCampaign(id: string) {
  return apiPost<Record<string, unknown>>(`/api/sheet-campaigns/${id}/sync`, {});
}
export function pauseSheetCampaign(id: string) {
  return apiPost<SheetCampaign>(`/api/sheet-campaigns/${id}/pause`, {});
}
export function resumeSheetCampaign(id: string) {
  return apiPost<SheetCampaign>(`/api/sheet-campaigns/${id}/resume`, {});
}
export function listSheetSourceItems(id: string, status?: string, signal?: AbortSignal) {
  const query = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
  return apiGet<SheetSourceItem[]>(`/api/sheet-campaigns/${id}/items${query}`, signal);
}
export function listSheetPublicationJobs(id: string, signal?: AbortSignal) {
  return apiGet<PublicationJob[]>(`/api/sheet-campaigns/${id}/jobs`, signal);
}
export function publishSheetSourceNow(id: string) {
  return apiPost<{ queued: unknown[] }>(`/api/sheet-campaigns/items/${id}/publish-now`, {});
}
export function cancelSheetSource(id: string) {
  return apiPost<SheetSourceItem>(`/api/sheet-campaigns/items/${id}/cancel`, {});
}
export function listGoogleSheetConnections(signal?: AbortSignal) {
  return apiGet<GoogleSheetConnection[]>("/api/google-sheets/connections", signal);
}
export function listFacebookPostTargets(signal?: AbortSignal) {
  return apiGet<FacebookPostTarget[]>("/api/post-targets", signal);
}
export function getPublicationHealth(signal?: AbortSignal) {
  return apiGet<PublicationHealth>("/api/health/publication", signal);
}

export function listRentalConfigs(signal?: AbortSignal) {
  return apiGet<RentalConfig[]>("/api/rental/configs", signal);
}
export function createRentalConfig(body: RentalConfigInput) {
  return apiPost<RentalConfig>("/api/rental/configs", body);
}
export function updateRentalConfig(id: string, body: Partial<RentalConfigInput>) {
  // Router registers PUT /api/rental/configs/{id} (see backend/app/routers/rental.py).
  return apiPut<RentalConfig>(`/api/rental/configs/${id}`, body);
}
export function deleteRentalConfig(id: string) {
  return apiDelete<{ deleted: boolean; id: string }>(`/api/rental/configs/${id}`);
}
export function testRentalLogin(id: string) {
  return apiPost<{ ok: boolean }>(`/api/rental/configs/${id}/test-login`, {});
}
export function syncRentalNow(id: string) {
  return apiPost<{ added: number; matched: number; waiting: number }>(`/api/rental/configs/${id}/sync-now`, {});
}
export function postRentalNow(id: string) {
  // RentalPostService.post_due() posts one throttled batch across all due configs
  // (not scoped to `id`); response shape is { fired: [...] } per rental_post.py.
  return apiPost<{
    fired: Array<{
      config_id: string;
      room_id: string;
      group_id: string | null;
      status: string;
      skipped?: boolean;
    }>;
  }>(`/api/rental/configs/${id}/post-now`, {});
}
export function listRentalRooms(id: string, signal?: AbortSignal) {
  return apiGet<RentalRoom[]>(`/api/rental/configs/${id}/rooms`, signal);
}
export function listRentalRoomJobs(roomId: string, signal?: AbortSignal) {
  return apiGet<RentalPublicationJob[]>(`/api/rental/rooms/${roomId}/jobs`, signal);
}
export function assignRoomGroups(roomId: string, groupIds: string[]) {
  return apiPost<RentalRoom>(`/api/rental/rooms/${roomId}/assign-groups`, { group_ids: groupIds });
}
export function skipRoom(roomId: string) {
  return apiPost<RentalRoom>(`/api/rental/rooms/${roomId}/skip`, {});
}
export function retryRoom(roomId: string) {
  return apiPost<RentalRoom>(`/api/rental/rooms/${roomId}/retry`, {});
}
