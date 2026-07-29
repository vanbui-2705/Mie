"use client";

import React, { useRef, useState, useEffect } from "react";

export interface WordSpec {
  start: number;
  end: number;
  word: string;
}

export interface ClipSpec {
  video_url: string;
  clip_duration: number;
  translated_text: string;
  hook_text: string;
  original_words: WordSpec[];
  style: any;
}

interface ClipPlayerProps {
  spec: ClipSpec;
}

export function ClipPlayer({ spec }: ClipPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  };

  return (
    <div className="relative w-full max-w-md mx-auto aspect-[9/16] bg-black rounded-lg overflow-hidden flex items-center justify-center">
      {/* Video layer */}
      <video
        ref={videoRef}
        src={spec.video_url}
        controls
        className="absolute inset-0 w-full h-full object-contain"
        onTimeUpdate={handleTimeUpdate}
      />

      {/* Subtitles layer overlay (Karaoke Effect) */}
      <div className="absolute bottom-20 left-0 right-0 px-4 pointer-events-none">
        <p className="text-center text-4xl font-black uppercase leading-tight drop-shadow-md" style={{
          WebkitTextStroke: `1px ${spec.style?.stroke || "#000"}`,
          textShadow: "2px 2px 0 #000, -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000"
        }}>
          {spec.original_words.map((w, i) => {
            // Check if this word should be highlighted based on current playback time
            // We use relative time in the clip (assuming video starts at 0 for this clip)
            const isActive = currentTime >= w.start && currentTime <= w.end;
            return (
              <span
                key={i}
                className="mr-2 inline-block transition-colors duration-75"
                style={{
                  color: isActive ? spec.style?.highlightColor || "#FFD700" : spec.style?.color || "#FFFFFF"
                }}
              >
                {w.word}
              </span>
            );
          })}
        </p>
        {/* Optional: Show Vietnamese translation below */}
        {spec.translated_text && (
          <p className="text-center text-xl mt-4 text-white font-bold drop-shadow-md bg-black/50 inline-block px-2 rounded">
            {spec.translated_text}
          </p>
        )}
      </div>
    </div>
  );
}
