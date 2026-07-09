"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { LogEntry, TaskStats } from "@/types";

// ── constants ──────────────────────────────────────────────────────────────────

const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// ── SSE state + core hook ─────────────────────────────────────────────────────

export interface SSEState<T> {
  data: T | null;
  connected: boolean;
  error: string | null;
  close: () => void;
}

export function useSSE<T>(
  url: string,
  opts: { reconnect?: boolean; reconnectBaseMs?: number; reconnectMaxMs?: number } = {}
): SSEState<T> {
  const { reconnect = true, reconnectBaseMs = 1000, reconnectMaxMs = 5000 } = opts;
  const [data, setData] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(null);
  const retryRef = useRef(0);
  const closedRef = useRef(false);

  const calcDelay = useCallback(() => {
    const delay = Math.min(reconnectBaseMs * 2 ** retryRef.current, reconnectMaxMs);
    retryRef.current += 1;
    return delay;
  }, [reconnectBaseMs, reconnectMaxMs]);

  const connect = useCallback(() => {
    closedRef.current = false;
    setError(null);
    esRef.current?.close();
    const es = new EventSource(url);
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
        const delay = calcDelay();
        timerRef.current = setTimeout(() => { if (!closedRef.current) connect(); }, delay);
      }
    };

    es.onmessage = (evt) => { try { setData(JSON.parse(evt.data) as T); } catch {} };
    es.addEventListener("log",      (evt) => { try { setData(JSON.parse((evt as MessageEvent).data) as T); } catch {} });
    es.addEventListener("stats",    (evt) => { try { setData(JSON.parse((evt as MessageEvent).data) as T); } catch {} });
    es.addEventListener("proxy_status", (evt) => { try { setData(JSON.parse((evt as MessageEvent).data) as T); } catch {} });

    es.addEventListener("close", () => { setConnected(false); });
  }, [url, reconnect, calcDelay]);

  const close = useCallback(() => {
    closedRef.current = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    try { esRef.current?.close(); } catch {}
    esRef.current = null;
    setConnected(false);
    retryRef.current = 0;
    setError(null);
  }, []);

  useEffect(() => { connect(); return close; }, [connect, close]);

  return { data, connected, error, close };
}

// ── convenience stream hooks ──────────────────────────────────────────────────

// The backend exposes a SINGLE unified SSE endpoint at /api/events/stream
// (see main.py:96).  We filter by channel via the `channels` query param.

export function useLogStream(urlBase: string) {
  const base = urlBase.replace(/\/$/, "");
  return useSSE<LogEntry>(`${base}/api/events/stream?channels=log`, { reconnect: true, reconnectBaseMs: 1000 });
}

export function useStatsStream(urlBase: string) {
  const base = urlBase.replace(/\/$/, "");
  return useSSE<TaskStats>(`${base}/api/events/stream?channels=log,stats`, { reconnect: true, reconnectBaseMs: 1000 });
}

// ── health check (polling, no SSE) ────────────────────────────────────────────

export function useHealthCheck(options?: { interval?: number; urlBase?: string }) {
  const base = (options?.urlBase ?? API_BASE).replace(/\/$/, "");
  const [status, setStatus] = useState<"checking" | "online" | "offline">("checking");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const doCheck = useCallback(async () => {
    setStatus("checking");
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const res = await fetch(`${base}/api/health`, { signal: ctrl.signal });
      setStatus(res.ok ? "online" : "offline");
    } catch {
      setStatus("offline");
    }
  }, [base]);

  useEffect(() => {
    const interval = options?.interval ?? 30000;
    doCheck();
    timerRef.current = setInterval(doCheck, interval);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      abortRef.current?.abort();
    };
  }, [doCheck, options?.interval]);

  return { status };
}
