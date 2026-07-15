"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { LogEntry, TaskStats } from "@/types";
import { getAuthToken } from "./api-client";

export function useSSE<T>(
url: string,
opts: { reconnect?: boolean; reconnectBaseMs?: number; reconnectMaxMs?: number } = {},
): { data: T | null; connected: boolean; error: string | null; close: () => void } {
const { reconnect = true, reconnectBaseMs = 1000, reconnectMaxMs = 5000 } = opts;
const [data, setData] = useState<T | null>(null);
const [connected, setConnected] = useState(false);
const [error, setError] = useState<string | null>(null);
const esRef = useRef<EventSource | null>(null);
const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
const retryRef = useRef(0);
const closedRef = useRef(false);

const close = useCallback(() => {
closedRef.current = true;
if (timerRef.current) clearTimeout(timerRef.current);
timerRef.current = null;
esRef.current?.close();
esRef.current = null;
setConnected(false);
retryRef.current = 0;
setError(null);
}, []);

useEffect(() => {
closedRef.current = false;

function connect() {
esRef.current?.close();
const token = getAuthToken();
const finalUrl = token ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}` : url;
const es = new EventSource(finalUrl);
esRef.current = es;

es.onopen = () => {
setConnected(true);
setError(null);
retryRef.current = 0;
if (timerRef.current) clearTimeout(timerRef.current);
timerRef.current = null;
};

es.onerror = () => {
setConnected(false);
es.close();
esRef.current = null;
if (!closedRef.current && reconnect) {
setError("Đang kết nối lại...");
const delay = Math.min(reconnectBaseMs * 2 ** retryRef.current, reconnectMaxMs);
retryRef.current += 1;
timerRef.current = setTimeout(() => {
if (!closedRef.current) connect();
}, delay);
}
};

const receive = (payload: string) => {
try { setData(JSON.parse(payload) as T); } catch { /* ignore non-JSON keepalive */ }
};
es.onmessage = (event) => receive(event.data);
for (const eventName of ["log", "stats", "proxy_status"]) {
es.addEventListener(eventName, (event) => receive((event as MessageEvent).data));
}
es.addEventListener("close", () => setConnected(false));
}

connect();
return () => {
closedRef.current = true;
if (timerRef.current) clearTimeout(timerRef.current);
timerRef.current = null;
esRef.current?.close();
esRef.current = null;
};
}, [url, reconnect, reconnectBaseMs, reconnectMaxMs]);

return { data, connected, error, close };
}

export function useLogStream(urlBase: string) {
const base = urlBase.replace(/\/$/, "");
return useSSE<LogEntry>(`${base}/api/events/stream?channels=log`, { reconnect: true, reconnectBaseMs: 1000 });
}

export function useStatsStream(urlBase: string) {
const base = urlBase.replace(/\/$/, "");
return useSSE<TaskStats>(`${base}/api/events/stream?channels=log,stats`, { reconnect: true, reconnectBaseMs: 1000 });
}

export function useHealthCheck(options?: { interval?: number; urlBase?: string }) {
const base = (options?.urlBase ?? "http://localhost:8000").replace(/\/$/, "");
const interval = options?.interval ?? 30000;
const [status, setStatus] = useState<"checking" | "online" | "offline">("checking");
const abortRef = useRef<AbortController | null>(null);

const doCheck = useCallback(async () => {
abortRef.current?.abort();
const controller = new AbortController();
abortRef.current = controller;
try {
const response = await fetch(`${base}/api/health`, { signal: controller.signal });
setStatus(response.ok ? "online" : "offline");
} catch {
if (!controller.signal.aborted) setStatus("offline");
}
}, [base]);

useEffect(() => {
const initialTimer = setTimeout(() => void doCheck(), 0);
const timer = setInterval(() => void doCheck(), interval);
return () => { clearTimeout(initialTimer); clearInterval(timer); abortRef.current?.abort(); };
}, [doCheck, interval]);

return { status };
}
