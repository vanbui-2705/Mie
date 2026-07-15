"use client";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "flowmeta_access_token";
const USER_KEY = "flowmeta_user";

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
  return `Yêu cầu thất bại (${status}).`;
}

export async function apiFetch<T>(
  path: string,
  options?: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
  },
): Promise<T> {
  const token = getAuthToken();
  const isFormData = typeof FormData !== "undefined" && options?.body instanceof FormData;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
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

export async function apiDelete<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE", body, signal });
}
