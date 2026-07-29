"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ClipPlayer } from "./ClipPlayer";
import { clipDownloadUrl, type Clip } from "@/lib/flow-api";
import { Download } from "lucide-react";

function seconds(value: number) {
  const total = Math.max(0, Math.round(value));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export function ResultGallery({ clips }: { clips: Clip[] }) {
  if (clips.length === 0) return null;
  const sorted = [...clips].sort((a, b) => a.rank - b.rank);

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      {sorted.map((clip) => (
        <Card key={clip.id} className="flex flex-col">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <Badge variant={clip.rank === 1 ? "default" : "secondary"}>Top {clip.rank}</Badge>
              <span className="text-xs text-muted-foreground">
                {seconds(clip.start_sec)} – {seconds(clip.end_sec)}
                {clip.score !== null ? ` · ${clip.score}đ` : ""}
              </span>
            </div>
            <CardTitle className="line-clamp-2">{clip.hook_text || "Không có hook"}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-3">
            <ClipPlayer clip={clip} />
            {clip.status === "READY" && clip.output_ref && (
              <Button
                variant="outline"
                size="sm"
                render={<a href={clipDownloadUrl(clip.id)} download={`clip-${clip.rank}.mp4`} />}
              >
                <Download className="h-4 w-4" />
                Tải về
              </Button>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
