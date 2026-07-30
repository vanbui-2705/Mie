"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Every Reup knob lives here instead of on the create form: the form asks for a
 * source and nothing else, and the numbers that rarely change sit in Settings.
 * Kept in localStorage — the backend has no per-user preference store yet.
 */
export type FlowSettings = {
  topN: number;
  clipMinSec: number;
  clipMaxSec: number;
  scoringBackend: string;
  aiEditInstructions: string;
};

export const DEFAULT_AI_EDIT_INSTRUCTIONS = `Mục tiêu: tạo clip ngắn có khả năng giữ chân người xem nhưng vẫn trung thực với video gốc.
- Ưu tiên đoạn mở đầu đi thẳng vào vấn đề, có câu gây tò mò hoặc lợi ích rõ trong 3 giây đầu.
- Chọn đoạn tự đủ ý, có diễn biến và kết luận; người xem không cần biết phần trước vẫn hiểu được.
- Loại bỏ lời chào, giới thiệu dài, quảng cáo lan man, khoảng lặng và nội dung lặp.
- Ưu tiên thông tin hữu ích, cảm xúc thật, bất ngờ, tranh luận hoặc câu nói dễ chia sẻ.
- Hook tiếng Việt ngắn, cụ thể, không giật tít sai và không bịa thêm dữ kiện.
- Phụ đề tiếng Việt tự nhiên, giữ đúng nghĩa, câu ngắn và dễ đọc trên màn hình điện thoại.`;

export const DEFAULT_FLOW_SETTINGS: FlowSettings = {
  topN: 3,
  clipMinSec: 30,
  clipMaxSec: 90,
  scoringBackend: "gemini",
  aiEditInstructions: DEFAULT_AI_EDIT_INSTRUCTIONS,
};

const STORAGE_KEY = "flowmeta_flow_settings";

// useSyncExternalStore compares snapshots by identity, so the parsed value has
// to be cached until something actually writes to the store.
let cache: FlowSettings = DEFAULT_FLOW_SETTINGS;
let cacheValid = false;
const listeners = new Set<() => void>();

function notify() {
  cacheValid = false;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Another tab writing the same key should update this one too.
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) notify();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function getSnapshot(): FlowSettings {
  if (cacheValid) return cache;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    cache = raw ? { ...DEFAULT_FLOW_SETTINGS, ...(JSON.parse(raw) as Partial<FlowSettings>) } : DEFAULT_FLOW_SETTINGS;
  } catch {
    cache = DEFAULT_FLOW_SETTINGS;
  }
  cacheValid = true;
  return cache;
}

function getServerSnapshot(): FlowSettings {
  return DEFAULT_FLOW_SETTINGS;
}

export function useFlowSettings() {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const save = useCallback((next: FlowSettings) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* private mode — fall through, the store still reports the old value */
    }
    notify();
  }, []);

  const reset = useCallback(() => {
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    notify();
  }, []);

  return { settings, save, reset };
}
