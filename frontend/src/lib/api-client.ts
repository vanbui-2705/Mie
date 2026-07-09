"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`API error ${status}`);
  }
}

function normalizeError(status: number, body: unknown): string {
  if (status === 401) return "Phiên đăng nhập hết hạn, vui lòng tải lại trang.";
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
  const res = await fetch(`${API_BASE}${path}`, {
    method: options?.method ?? "GET",
    headers: { "Content-Type": "application/json" },
    body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options?.signal,
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    throw new Error(normalizeError(res.status, body), { cause: new ApiError(res.status, body) });
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

export async function apiDelete<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE", body, signal });
}

export interface SSEState<T> {
  data: T | null;
  connected: boolean;
  error: string | null;
  close: () => void;
}

export function createSSEClient<T>(
  url: string,
  onData: (data: T) => void,
  opts: { reconnect?: boolean; reconnectBaseMs?: number; reconnectMaxMs?: number } = {},
): SSEState<T> {
  const { reconnect = true, reconnectBaseMs = 1000, reconnectMaxMs = 5000 } = opts;
  let connected = false;
  let error: string | null = null;
  const closed = { value: false } as { value: boolean };
  let retryCount = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let eventSource: EventSource | null = null;

  function calcDelay(): number {
    const delay = Math.min(reconnectBaseMs * 2 ** retryCount, reconnectMaxMs);
    retryCount += 1;
    return delay;
  }

  function doConnect(): EventSource {
    closed.value = false;
    error = null;
    connected = false;
    if (eventSource) {
      try {
        eventSource.close();
      } catch {}
    }

    const es = new EventSource(url);
    eventSource = es;

    es.onopen = () => {
      connected = true;
      error = null;
      retryCount = 0;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    es.onerror = () => {
      connected = false;
      es.close();
      if (!closed.value && reconnect) {
        error = "Đang kết nối lại...";
        const delay = calcDelay();
        reconnectTimer = setTimeout(() => {
          if (!closed.value) doConnect();
        }, delay);
      }
    };

    es.onmessage = (evt) => {
      try {
        onData(JSON.parse(evt.data) as T);
      } catch {}
    };

    for (const eventName of ["log", "stats", "proxy_status"]) {
      es.addEventListener(eventName, (evt: MessageEvent) => {
        try {
          onData(JSON.parse(evt.data) as T);
        } catch {}
      });
    }

    return es;
  }

  doConnect();

  function close() {
    closed.value = true;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    try {
      eventSource?.close();
    } catch {}
    eventSource = null;
    connected = false;
  }

  return {
    get data() {
      return null;
    },
    get connected() {
      return connected;
    },
    get error() {
      return error;
    },
    close,
  };
}

export function useSSE<T>(
  url: string,
  onData: (data: T) => void,
  opts: { reconnect?: boolean; reconnectBaseMs?: number; reconnectMaxMs?: number } = {},
): SSEState<T> {
  const onDataRef = useRef(onData);
  onDataRef.current = onData;

  const [, setTick] = useState(0);
  const clientRef = useRef<ReturnType<typeof createSSEClient<T>> | null>(null);

  useEffect(() => {
    const client = createSSEClient<T>(
      url,
      (data) => {
        onDataRef.current(data);
        setTick((n) => n + 1);
      },
      opts,
    );
    clientRef.current = client;
    return () => {
      client.close();
      clientRef.current = null;
    };
  }, [url]);

  const client = clientRef.current;
  return {
    data: null,
    connected: client ? client.connected : false,
    error: client ? client.error : null,
    close: () => client?.close(),
  };
}
