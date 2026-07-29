"use client";

import { useRef, useState } from "react";
import { clipStreamUrl, type Clip } from "@/lib/flow-api";

/**
 * The rendered file already has the ASS subtitles burned in (see
 * ai_pipeline/renderer.py), so the player must NOT draw them again on top.
 * The word list below the frame is a transcript, not an overlay: it follows
 * playback so the editor can see which word is on screen right now.
 */
export function ClipPlayer({ clip }: { clip: Clip }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [failed, setFailed] = useState(false);

  const words = clip.clipspec?.words ?? [];

  if (clip.status !== "READY" || !clip.output_ref) {
    return (
      <div className="flex aspect-[9/16] w-full items-center justify-center rounded-lg border border-dashed border-foreground/15 text-xs text-muted-foreground">
        {clip.status === "ERROR" ? "Render lỗi" : "Chưa render xong"}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="relative aspect-[9/16] w-full overflow-hidden rounded-lg bg-black">
        {failed ? (
          <div className="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
            Không tải được video. Kiểm tra Flow API còn chạy không.
          </div>
        ) : (
          <video
            ref={videoRef}
            src={clipStreamUrl(clip.id)}
            controls
            preload="metadata"
            playsInline
            className="absolute inset-0 h-full w-full object-contain"
            onTimeUpdate={() => setCurrentTime(videoRef.current?.currentTime ?? 0)}
            onError={() => setFailed(true)}
          />
        )}
      </div>

      {words.length > 0 && (
        <p className="max-h-24 overflow-y-auto text-[13px] leading-relaxed">
          {words.map((w, i) => {
            const isActive = currentTime >= w.start && currentTime <= w.end;
            return (
              <span
                key={`${i}-${w.start}`}
                className={isActive ? "font-semibold text-foreground" : "text-muted-foreground"}
              >
                {w.word}{" "}
              </span>
            );
          })}
        </p>
      )}
    </div>
  );
}
