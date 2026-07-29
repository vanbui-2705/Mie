"use client";

import React from "react";
import { ClipPlayer, ClipSpec } from "./ClipPlayer";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Badge } from "../ui/badge";

export interface ClipData {
  id: string;
  rank: number;
  score: number;
  hook_text: string;
  clipspec: ClipSpec;
}

interface ResultGalleryProps {
  clips: ClipData[];
}

export function ResultGallery({ clips }: ResultGalleryProps) {
  if (!clips || clips.length === 0) {
    return null;
  }

  // Sort by rank (1 is best)
  const sortedClips = [...clips].sort((a, b) => a.rank - b.rank);

  return (
    <div className="mt-8 space-y-6">
      <h3 className="text-2xl font-bold">🎉 Clips Đã Hoàn Thành</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {sortedClips.map((clip) => (
          <Card key={clip.id} className="overflow-hidden flex flex-col bg-slate-900 border-slate-800 text-white">
            <CardHeader className="p-4 pb-2">
              <div className="flex justify-between items-start mb-2">
                <Badge variant={clip.rank === 1 ? "default" : "secondary"} className={clip.rank === 1 ? "bg-amber-500 hover:bg-amber-600" : ""}>
                  Top {clip.rank}
                </Badge>
                <Badge variant="outline" className="text-green-400 border-green-400">
                  Điểm: {clip.score}/100
                </Badge>
              </div>
              <CardTitle className="text-lg line-clamp-2 leading-tight">
                {clip.hook_text}
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 pt-2 flex-grow">
              <ClipPlayer spec={clip.clipspec} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
