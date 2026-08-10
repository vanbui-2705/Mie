"use client";

import { ApiError, apiFetch, getAuthToken } from "./api-client";

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

// PURGED / CANCELLED come from the retention sweeper: the server deletes a
// job's files once no tab has heartbeaten it for CLIP_SESSION_GRACE_SECONDS.
export type ClipStatus = "PENDING" | "RENDERING" | "READY" | "ERROR" | "PURGED";
export type ClipJobStatus =
  | "QUEUED" | "ANALYZING" | "SCORING" | "RENDERING" | "DONE" | "ERROR" | "CANCELLED";

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
  // PROMPT = created on the gen tab; it has no file behind it.
  source_type: "UPLOAD" | "LINK" | "PROMPT";
  status: ClipJobStatus;
  error: string | null;
  purged_at: string | null;
  clips: Clip[];
};

export type ClipJobSummary = {
  id: string;
  // PROMPT = created on the gen tab; it has no file behind it.
  source_type: "UPLOAD" | "LINK" | "PROMPT";
  source_name: string;
  status: ClipJobStatus;
  error: string | null;
  clip_count: number;
  created_at: string | null;
  finished_at: string | null;
  purged_at: string | null;
};

export type CreateClipJobInput = {
  file?: File | null;
  sourceLink?: string;
  topN: number;
  clipMinSec: number;
  clipMaxSec: number;
  scoringBackend: string;
  voiceover?: boolean;
  voice?: VoiceId;
  editInstructions?: string;
};

/** Matches ai_pipeline/tts_engine.VOICES — the server rejects anything else. */
export const VOICE_OPTIONS = [
  { id: "vi-female", label: "Nữ (tiếng Việt)" },
  { id: "vi-male", label: "Nam (tiếng Việt)" },
] as const;

export type VoiceId = (typeof VOICE_OPTIONS)[number]["id"];

function detailFromError(error: unknown): string {
  if (error instanceof Error && error.cause instanceof ApiError) {
    const body = error.cause.body;
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  }
  return error instanceof Error ? error.message : String(error ?? "");
}

/** Turn pipeline/upstream failures into something actionable for the operator. */
export function describeFlowError(error: unknown): string {
  const raw = detailFromError(error).trim();
  const lower = raw.toLowerCase();
  if (!raw) return "Không xử lý được video. Vui lòng thử lại.";
  if (lower.includes("gemini model") && lower.includes("unavailable")) {
    return "Model Gemini đang cấu hình không khả dụng. Kiểm tra GEMINI_MODEL trên máy chủ.";
  }
  if (lower.includes("rejected the api key") || lower.includes("api key")) {
    return "Gemini API key không hợp lệ hoặc chưa được cấp quyền.";
  }
  if (lower.includes("quota") || lower.includes("rate limit") || lower.includes("http 429")) {
    return "Gemini đang hết hạn mức hoặc bị giới hạn tốc độ. Chờ một lúc rồi thử lại.";
  }
  if (lower.includes("http 503") || lower.includes("service unavailable")) {
    return "Dịch vụ AI đang tạm gián đoạn. Hệ thống đã tự thử lại nhưng chưa thành công.";
  }
  if (lower.includes("network request failed")) {
    return "Máy chủ không kết nối được tới Gemini sau nhiều lần thử.";
  }
  if (lower.includes("asr produced no usable speech")) {
    return "Không nhận diện được đoạn có lời nói trong video. Hãy chọn video có tiếng rõ hơn.";
  }
  if (lower.includes("failed to extract audio")) {
    return "Không đọc được âm thanh của video. Hãy đổi video hoặc chuyển file sang MP4/H.264.";
  }
  if (lower.includes("download failed")) {
    return "Không tải được video từ liên kết này. Hãy kiểm tra link hoặc tải file trực tiếp.";
  }
  if (lower.includes("could not obtain a backdrop")) {
    return "Không lấy được hình nền cho một cảnh. Hãy thử lại hoặc cấu hình nguồn ảnh.";
  }
  return raw;
}

function flowFetch<T>(path: string, options?: { method?: string; body?: unknown; signal?: AbortSignal }) {
  return apiFetch<T>(path, { ...options, base: getFlowBase() });
}

/**
 * The API serialises enums by value — "done", "ready", "upload" — while every
 * component here compares against the uppercase member names. Normalise once at
 * the boundary instead of sprinkling toUpperCase() through the UI.
 */
function upper<T extends string>(value: unknown, fallback: T): T {
  return (typeof value === "string" ? (value.toUpperCase() as T) : fallback);
}

function normalizeClip(clip: Clip): Clip {
  return { ...clip, status: upper<ClipStatus>(clip.status, "PENDING") };
}

function normalizeJob(job: ClipJob): ClipJob {
  return {
    ...job,
    status: upper<ClipJobStatus>(job.status, "QUEUED"),
    source_type: upper<ClipJob["source_type"]>(job.source_type, "UPLOAD"),
    clips: (job.clips ?? []).map(normalizeClip),
  };
}

function normalizeSummary(summary: ClipJobSummary): ClipJobSummary {
  return {
    ...summary,
    status: upper<ClipJobStatus>(summary.status, "QUEUED"),
    source_type: upper<ClipJobSummary["source_type"]>(summary.source_type, "UPLOAD"),
  };
}

export function createClipJob(input: CreateClipJobInput, signal?: AbortSignal) {
  const form = new FormData();
  if (input.file) form.append("file", input.file);
  if (input.sourceLink) form.append("source_link", input.sourceLink);
  form.append("top_n", String(input.topN));
  form.append("clip_min_sec", String(input.clipMinSec));
  form.append("clip_max_sec", String(input.clipMaxSec));
  form.append("scoring_backend", input.scoringBackend);
  form.append("voiceover", String(Boolean(input.voiceover)));
  form.append("voice", input.voice ?? "vi-female");
  form.append("edit_instructions", input.editInstructions ?? "");
  return flowFetch<{ job_id: string; status: ClipJobStatus }>("/api/clip-jobs", {
    method: "POST",
    body: form,
    signal,
  }).then((result) => ({ ...result, status: upper<ClipJobStatus>(result.status, "QUEUED") }));
}

export type CreateGenJobInput = {
  prompt: string;
  negativePrompt?: string;
  durationSec: number;
  voice: VoiceId;
  scoringBackend?: string;
  images?: File[];
};

/** Prompt -> video. The server stores it as a clip job, so the progress card,
 *  the gallery and the history list all work on the returned id unchanged. */
export function createGenJob(input: CreateGenJobInput, signal?: AbortSignal) {
  if (input.images?.length) {
    const form = new FormData();
    form.append("prompt", input.prompt);
    form.append("negative_prompt", input.negativePrompt ?? "");
    form.append("duration_sec", String(input.durationSec));
    form.append("voice", input.voice);
    form.append("scoring_backend", input.scoringBackend ?? "gemini");
    input.images.forEach((image) => form.append("images", image));
    return flowFetch<{ job_id: string; status: ClipJobStatus }>("/api/gen-jobs/from-images", {
      method: "POST",
      body: form,
      signal,
    }).then((result) => ({ ...result, status: upper<ClipJobStatus>(result.status, "QUEUED") }));
  }
  return flowFetch<{ job_id: string; status: ClipJobStatus }>("/api/gen-jobs", {
    method: "POST",
    body: {
      prompt: input.prompt,
      negative_prompt: input.negativePrompt || null,
      duration_sec: input.durationSec,
      voice: input.voice,
      scoring_backend: input.scoringBackend ?? null,
    },
    signal,
  }).then((result) => ({ ...result, status: upper<ClipJobStatus>(result.status, "QUEUED") }));
}

export function getClipJob(jobId: string, signal?: AbortSignal) {
  return flowFetch<ClipJob>(`/api/clip-jobs/${jobId}`, { signal }).then(normalizeJob);
}

/**
 * "These jobs are still on screen." The server deletes the source and the
 * rendered mp4s of any job it has not heard about for one day, so an open
 * tab must keep beating; a refresh is back well inside that window.
 */
export function heartbeatClipJobs(jobIds: string[], signal?: AbortSignal) {
  return flowFetch<{ touched: number }>("/api/clip-jobs/heartbeat", {
    method: "POST",
    body: { job_ids: jobIds },
    signal,
  });
}

export function listClipJobs(limit = 20, offset = 0, signal?: AbortSignal) {
  return flowFetch<ClipJobSummary[]>(`/api/clip-jobs?limit=${limit}&offset=${offset}`, { signal })
    .then((rows) => rows.map(normalizeSummary));
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
