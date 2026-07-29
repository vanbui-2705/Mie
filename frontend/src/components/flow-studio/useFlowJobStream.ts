"use client";

import { useEffect, useRef, useState } from "react";
import { getAuthToken } from "@/lib/api-client";
import { flowEventsUrl } from "@/lib/flow-api";

/**
 * Not `useSSE`: that hook collapses every event into one `data` value, and the
 * clip channel needs the event NAME to tell `done` from `phase` — the payloads
 * differ only by which optional field is present (see services/clip_runner.py).
 */
export type FlowJobEvent =
  | { type: "phase"; phase: string }
  | { type: "clip_ready"; rank: number }
  | { type: "done" }
  | { type: "error"; error: string };

const EVENT_NAMES = ["phase", "clip_ready", "done", "error"] as const;

export function useFlowJobStream(jobId: string | null, onEvent: (event: FlowJobEvent) => void) {
  const [connected, setConnected] = useState(false);
  // Keep the latest callback without re-subscribing on every parent render.
  const handlerRef = useRef(onEvent);
  useEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!jobId) return;
    let closed = false;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const connect = () => {
      const token = getAuthToken();
      source = new EventSource(`${flowEventsUrl()}&token=${encodeURIComponent(token)}`);

      source.onopen = () => {
        setConnected(true);
        attempt = 0;
      };
      source.onerror = () => {
        setConnected(false);
        source?.close();
        source = null;
        if (closed) return;
        const delay = Math.min(1000 * 2 ** attempt, 10000);
        attempt += 1;
        timer = setTimeout(connect, delay);
      };

      for (const name of EVENT_NAMES) {
        source.addEventListener(name, (raw) => {
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse((raw as MessageEvent).data);
          } catch {
            return;
          }
          // The channel carries every job of this user; ignore the other ones.
          if (payload.job_id !== jobId) return;
          if (name === "phase") handlerRef.current({ type: "phase", phase: String(payload.phase ?? "") });
          else if (name === "clip_ready") handlerRef.current({ type: "clip_ready", rank: Number(payload.rank ?? 0) });
          else if (name === "done") handlerRef.current({ type: "done" });
          else handlerRef.current({ type: "error", error: String(payload.error ?? "Job lỗi") });
        });
      }
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      source?.close();
      setConnected(false);
    };
  }, [jobId]);

  return { connected };
}
