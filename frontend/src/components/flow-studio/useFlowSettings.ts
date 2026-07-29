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
};

export const DEFAULT_FLOW_SETTINGS: FlowSettings = {
  topN: 3,
  clipMinSec: 30,
  clipMaxSec: 90,
  scoringBackend: "gemini",
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
