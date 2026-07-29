"use client";

import { apiFetch, getAuthToken } from "./api-client";

/**
 * Flow Studio runs as its own process on its own port (see backend/app/flow_app.py),
 * so it needs a base of its own. Everything else — token, 401 handling, error
 * normalisation — is shared with the Face API through apiFetch.
 */
export const FLOW_BASE = process.env.NEXT_PUBLIC_FLOW_API_URL ?? "http://localhost:8001";

export function getFlowBase() {
  if (typeof window === "undefined") return FLOW_BASE;
  try {
    const configured = new URL(FLOW_BASE, window.location.origin);
    const configuredIsLocal = configured.hostname === "localhost" || configured.hostname === "127.0.0.1";
    const browserIsLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    // A localhost default is meaningless to a browser on another machine; fall
    // back to the origin serving the page, mirroring getApiBase().
    return configuredIsLocal && !browserIsLocal ? window.location.origin : FLOW_BASE;
  } catch {
    return FLOW_BASE;
  }
}

export type ClipStatus = "PENDING" | "RENDERING" | "READY" | "ERROR";
export type ClipJobStatus = "QUEUED" | "ANALYZING" | "SCORING" | "RENDERING" | "DONE" | "ERROR";

export type ClipWord = { start: number; end: number; word: string };

export type ClipSpec = {
  version?: number;
  video_url?: string;
  subtitle_url?: string;
  duration?: number;
  hook_text?: string;
  subtitle_text?: string;
  words?: ClipWord[];
  cues?: { start: number; end: number; text: string }[];
  style?: Record<string, string | number>;
  error?: string;
};

export type Clip = {
  id: string;
  rank: number;
  score: number | null;
  hook_text: string | null;
  start_sec: number;
  end_sec: number;
  status: ClipStatus;
  output_ref: string | null;
  clipspec: ClipSpec | null;
};

export type ClipJob = {
  id: string;
  source_type: "UPLOAD" | "LINK";
  status: ClipJobStatus;
  error: string | null;
  clips: Clip[];
};

export type ClipJobSummary = {
  id: string;
  source_type: "UPLOAD" | "LINK";
  source_name: string;
  status: ClipJobStatus;
  error: string | null;
  clip_count: number;
  created_at: string | null;
  finished_at: string | null;
};

export type CreateClipJobInput = {
  file?: File | null;
  sourceLink?: string;
  topN: number;
  clipMinSec: number;
  clipMaxSec: number;
  scoringBackend: string;
};

function flowFetch<T>(path: string, options?: { method?: string; body?: unknown; signal?: AbortSignal }) {
  return apiFetch<T>(path, { ...options, base: getFlowBase() });
}

export function createClipJob(input: CreateClipJobInput, signal?: AbortSignal) {
  const form = new FormData();
  if (input.file) form.append("file", input.file);
  if (input.sourceLink) form.append("source_link", input.sourceLink);
  form.append("top_n", String(input.topN));
  form.append("clip_min_sec", String(input.clipMinSec));
  form.append("clip_max_sec", String(input.clipMaxSec));
  form.append("scoring_backend", input.scoringBackend);
  return flowFetch<{ job_id: string; status: ClipJobStatus }>("/api/clip-jobs", {
    method: "POST",
    body: form,
    signal,
  });
}

export function getClipJob(jobId: string, signal?: AbortSignal) {
  return flowFetch<ClipJob>(`/api/clip-jobs/${jobId}`, { signal });
}

export function listClipJobs(limit = 20, offset = 0, signal?: AbortSignal) {
  return flowFetch<ClipJobSummary[]>(`/api/clip-jobs?limit=${limit}&offset=${offset}`, { signal });
}

/** URL a <video> tag can load: the token rides the query string because a media
 * element cannot set an Authorization header. */
export function clipStreamUrl(clipId: string) {
  return `${getFlowBase()}/api/clips/${clipId}/stream?token=${encodeURIComponent(getAuthToken())}`;
}

export function clipDownloadUrl(clipId: string) {
  return `${getFlowBase()}/api/clips/${clipId}/stream?token=${encodeURIComponent(getAuthToken())}`;
}

export function flowEventsUrl() {
  return `${getFlowBase()}/api/events/stream?channels=clip`;
}
