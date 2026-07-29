"use client";

import React, { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ProgressTracker } from "@/components/flow-studio/ProgressTracker";
import { ResultGallery, ClipData } from "@/components/flow-studio/ResultGallery";

export default function FlowStudioPage() {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [results, setResults] = useState<ClipData[] | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!videoFile) return;

    setIsSubmitting(true);
    setResults(null);
    setActiveJobId(null);

    try {
      const formData = new FormData();
      formData.append("file", videoFile);
      formData.append("top_n", "3");
      // Add other params if needed...

      // Normally we call FastAPI backend here
      // const res = await fetch("/api/clips/jobs", { method: "POST", body: formData });
      // const data = await res.json();
      // setActiveJobId(data.job_id);
      
      // For demonstration, simulating an active job:
      setActiveJobId("demo-job-123");
    } catch (err) {
      console.error(err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const fetchResults = async () => {
    if (!activeJobId) return;
    try {
      // Normally fetch the job results from backend
      // const res = await fetch(`/api/clips/jobs/${activeJobId}`);
      // const data = await res.json();
      // setResults(data.clips);

      // MOCK DATA for preview until API is fully linked
      setResults([
        {
          id: "clip1",
          rank: 1,
          score: 95,
          hook_text: "Bí quyết hút ngàn View",
          clipspec: {
            video_url: "/mov_bbb.mp4", // Using the mock video we downloaded
            clip_duration: 10,
            translated_text: "Đây là bí quyết giúp bạn hút hàng ngàn lượt xem.",
            hook_text: "Bí quyết hút ngàn View",
            style: { color: "#FFF", highlightColor: "#FFD700" },
            original_words: [
              { word: "Đây", start: 1, end: 1.5 },
              { word: "là", start: 1.5, end: 2 },
              { word: "bí", start: 2, end: 2.5 },
              { word: "quyết", start: 2.5, end: 3 },
            ]
          }
        }
      ]);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="container mx-auto py-10 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-4xl font-black mb-2">🎬 Flow Studio</h1>
        <p className="text-slate-400">Hệ thống AI tự động cắt và dịch thuật video siêu tốc.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-1">
          <Card className="bg-slate-900 border-slate-800 text-white">
            <CardHeader>
              <CardTitle>Tạo Clip Mới</CardTitle>
              <CardDescription className="text-slate-400">Tải lên video thô để AI xử lý.</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="video">File Video (.mp4)</Label>
                  <Input 
                    id="video" 
                    type="file" 
                    accept="video/mp4" 
                    onChange={(e) => setVideoFile(e.target.files?.[0] || null)}
                    className="bg-slate-800 border-slate-700"
                  />
                </div>
                
                <Button 
                  type="submit" 
                  disabled={!videoFile || isSubmitting || !!activeJobId}
                  className="w-full bg-blue-600 hover:bg-blue-700"
                >
                  {isSubmitting ? "Đang đẩy lên..." : "Tạo Clip Bằng AI"}
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>

        <div className="lg:col-span-2">
          {activeJobId && !results && (
            <ProgressTracker 
              jobId={activeJobId} 
              onComplete={fetchResults} 
            />
          )}

          {results && <ResultGallery clips={results} />}

          {!activeJobId && !results && (
            <div className="h-full min-h-[200px] border-2 border-dashed border-slate-800 rounded-lg flex items-center justify-center text-slate-500">
              <p>Chưa có video nào đang xử lý.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
