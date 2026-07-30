"use client";

import { useEffect } from "react";
import { heartbeatClipJobs } from "@/lib/flow-api";

/** Matches CLIP_SESSION_GRACE_SECONDS=120 on the server with room for one
 *  missed beat: two failures in a row still leave 60s before the sweeper runs. */
export const HEARTBEAT_INTERVAL_MS = 30_000;

/**
 * Tells the server that these jobs are still on someone's screen.
 *
 * The server deletes a job's upload and rendered clips once nothing has claimed
 * them for two minutes, which is how a closed tab (or a crashed browser) frees
 * its disk without anyone pressing delete. A refresh re-mounts this hook within
 * a second, so it keeps its files.
 */
export function useSessionHeartbeat(jobIds: (string | null | undefined)[]) {
  // Join, so the effect re-runs on a real change instead of on every render
  // (a fresh array literal is a new reference each time).
  const key = jobIds.filter(Boolean).join(",");

  useEffect(() => {
    if (!key) return;
    const ids = key.split(",");
    const controller = new AbortController();

    const beat = () => {
      heartbeatClipJobs(ids, controller.signal).catch(() => {
        // Offline or the API is restarting; the next beat retries.
      });
    };

    beat();
    const timer = setInterval(beat, HEARTBEAT_INTERVAL_MS);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [key]);
}
