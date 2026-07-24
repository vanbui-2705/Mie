# Flow Studio v1 — Long-to-Short tiếng Việt (Web)

**Ngày:** 2026-07-24
**Trạng thái:** Design (đã duyệt hướng, chờ review spec)
**Phạm vi:** UC1 — ném 1 video dài vào web tool → tự tách các đoạn "hay nhất" thành clip dọc 2–5 phút → chỉnh sửa trong editor (OpenCut) → render server → tải. Chạy **CPU-only** (không có NVIDIA GPU). Mục tiêu phục vụ xây kênh nên chất lượng phải chắc.

---

## 1. Mục tiêu & phi mục tiêu

**Mục tiêu:**
- Input: upload file video **hoặc** dán link (YouTube/Drive), tự tải.
- Auto-cut: chọn các đoạn "hay nhất" (highlight), cắt thành clip dọc 9:16 dài 2–5 phút, phụ đề tiếng Việt đủ dấu.
- **Editor**: nhúng **OpenCut classic** để tinh chỉnh biên/crop/chữ → xuất edit-decision → **server FFmpeg render** (non-destructive).
- Chạy CPU-only, không phụ thuộc GPU. Giảm tối đa công đoạn nặng (ASR, re-encode).
- Chất lượng tiếng Việt: ASR đúng dấu, phụ đề không vỡ chữ, chấm điểm hợp cách nói Việt.
- **Tích hợp vào app hiện có** (FastAPI + Next.js + Postgres), tái dùng auth/RBAC/task_queue.

**Phi mục tiêu (v1):**
- Không train model riêng.
- Không viết pipeline xử lý từ đầu — fork `SamurAIGPT/AI-Youtube-Shorts-Generator`, Việt-hoá, dùng làm lõi worker.
- **Không tự code timeline editor** — nhúng OpenCut classic (MIT).
- Không làm kênh Telegram/OpenClaw ở v1 — nhưng pipeline thiết kế dạng **service có API sạch** để Telegram/OpenClaw (hoặc OpenCut mới qua MCP) cắm vào sau.
- Không multi-nguồn phức tạp; chỉ upload + link.

---

## 2. Kiến trúc tổng

```
Frontend (Next.js, frontend/src)
  - Trang tạo job: upload/link + tham số
  - Trang job: tiến độ (SSE), list clip highlight, điểm + hook
  - Editor: NHÚNG OpenCut classic → user tinh chỉnh → xuất edit-decision (→ clipspec)
        │ REST + SSE
Backend (FastAPI, backend/app)
  - routers/clip_jobs.py     : POST /clip-jobs, GET /clip-jobs/{id}, POST /clips/{id}/render
  - services/clip_runner.py  : worker chạy lõi Flow Studio (pattern task_runner)
  - services/clip_pipeline/  : lõi fork Việt-hoá (prefilter, asr, score, cut, subtitle)
  - EventBus SSE             : báo tiến độ từng phase
        │
Postgres (SQLModel) : ClipJob, Clip, ClipEdit  (pattern TaskRun/TaskItem)
Storage             : MinIO/S3 (hoặc disk) — video gốc + proxy 360p + clip xuất
CPU-only            : PhoWhisper int8 (CPU) + libx264 (CPU). Không GPU/NVENC.
```

Chia vai rõ:
- **Pipeline mình** = phần AI: tìm đoạn hay, ASR tiếng Việt, chấm điểm, cắt thô, render. OpenCut **không** làm.
- **OpenCut** = editor người dùng: tinh chỉnh + xuất edit-decision. Mình **không** tự code timeline.
- Web là client đầu tiên; Telegram/OpenClaw/OpenCut-MCP sau này gọi cùng REST API.

---

## 3. Pipeline & data flow

```
Input (upload file | link → tải)
  → prefilter : quét audio (RMS peak, cười/vỗ tay, pitch, tốc độ nói) → ~30 vùng nóng
  → asr       : PhoWhisper int8 (CPU) CHỈ trên vùng nóng + khôi phục dấu câu
  → score     : LLM chấm rubric tiếng Việt (0–100) + hook sentence trên vùng nóng
  → dedupe+topN : overlap >50% giữ điểm cao (logic repo)
  → clipspec  : sinh clipspec JSON mỗi clip (biên, crop path, sub cues) — CHƯA render
  → render    : FFmpeg đọc clipspec → stream copy cắt + burn sub ASS 9:16 (libx264 CPU)
  → clip nháp → user mở OpenCut sửa → xuất clipspec mới → render lại
```

**Khác repo gốc:** chèn **prefilter (tầng 1) TRƯỚC ASR**, vứt ~80% phần nhạt để PhoWhisper chỉ chạy vùng nóng (~10–20% thời lượng) — cắt thời gian ASR 5–10 lần, **cực quan trọng vì chạy CPU**. Và tách **clipspec** làm ranh giới data/render để OpenCut sửa được mà không phải xử lý pixel ở client.

---

## 4. Ba tầng lọc "đoạn hay"

| Tầng | Kỹ thuật | Chi phí | Vai trò |
|---|---|---|---|
| 1 — Tín hiệu | RMS/loudness peak, cười/vỗ tay (decision tree trên spectrogram), pitch variance, tốc độ nói, khoảng lặng | Rất rẻ, audio-only, vài giây/1h, không GPU | Lọc thô ~30 vùng nóng trước ASR |
| 2 — Transcript heuristic | Cặp hỏi–đáp, từ cảm xúc/số liệu, câu mở hook độc lập | Rẻ | Xếp hạng phụ |
| 3 — LLM chấm | Rubric virality tiếng Việt, structured output 0–100 + hook | Tuỳ backend (§5) | Chấm chất lượng cuối, chọn clip |

Rubric (Việt-hoá từ repo): hook, cảm xúc cao trào, quan điểm, tiết lộ, xung đột, câu trích dẫn được, cao trào câu chuyện, giá trị thực dụng.

---

## 5. Engine chấm — pluggable, mặc định local

`SCORING_BACKEND`:
- **`ollama`** — mặc định. SeaLLM/Sailor (hoặc Vistral/PhoGPT) qua Ollama, chạy CPU. Miễn phí, offline, tiếng Việt tốt.
- **`claude`** — `claude-opus-4-8` chất lượng cao nhất, ~$0.1/video (prefilter + prompt cache + batch), critic tuỳ chọn.
- **`heuristic`** — bỏ LLM, chỉ tầng 1+2. Nhanh nhất, nông nhất; cũng là fallback khi Ollama không chạy.

Đổi backend = đổi một dòng config; pipeline không đổi.

---

## 6. ASR — CPU-only (không NVIDIA), pluggable

Máy **không có NVIDIA GPU** → ASR phải tối ưu cho CPU. Cứu cánh chính: **prefilter chỉ ASR ~10–20% thời lượng** (chỉ vùng nóng).

`ASR_BACKEND`:
- **`local`** — mặc định. **faster-whisper int8** (CTranslate2, PhoWhisper-medium/small) hoặc **whisper.cpp** (quantize, tối ưu CPU mạnh). Miễn phí, offline.
- **`cloud`** — Deepgram/AssemblyAI... offload khi CPU không kịp volume. Tốn phí nhẹ; tiếng Việt yếu hơn PhoWhisper.

Sau ASR: **khôi phục dấu câu** tiếng Việt (model punctuation-restoration, hoặc chấm câu dựa VAD-silence). Không có dấu câu thì không snap được ranh giới câu.

---

## 7. Hạ tầng xử lý video (cắt/render) — CPU-only

- **Engine = FFmpeg** (subprocess) trong worker. Một đường render duy nhất cho cả auto-cut lẫn export từ editor.
- Cắt = **stream copy** (`-c copy`), snap điểm cắt tới **keyframe ∩ khoảng lặng** gần mốc mục tiêu; không re-encode phần thân (CPU gần như rảnh).
- **Re-encode chỉ khi burn phụ đề**: `libx264` **`veryfast`/`ultrafast` CPU**. Không NVENC. Clip 2–5 phút nên nhẹ.
- **Crop dọc 9:16**: OpenCV face-tracking + motion smoothing (local mode repo) sinh **crop path** vào clipspec; render áp path.
- **Storage**: MinIO/S3 (hoặc disk) — video gốc + clip + proxy 360p (dùng cho scene/preview OpenCut). Không nhét file vào Postgres.

---

## 8. Editor = nhúng OpenCut classic (scope B)

Không tự code timeline. Dùng **`opencut-app/opencut-classic`** (MIT, web-based Next.js) nhúng vào app.

```
Auto-cut xong → clip nháp + clipspec
     │ nạp vào
OpenCut editor (nhúng frontend/src)
  - kéo biên cắt, dời/scale crop, sửa chữ/timing sub, effect
     │ export edit-decision
Map: OpenCut project ↔ clipspec  (adapter 2 chiều)
     │ POST /clips/{id}/render { clipspec }
Backend FFmpeg render server-side → clip cuối
```

**Vì sao render server, không dùng export client của OpenCut:**
- Tái dùng đúng engine FFmpeg đã có cho auto-cut = một đường render, một chất lượng.
- Burn phụ đề tiếng Việt trong browser (ffmpeg.wasm/WebCodecs) **hay vỡ dấu**; server render với font nhúng (Be Vietnam Pro) chắc chắn đúng.
- Kênh = volume + đồng nhất; server render không phụ thuộc máy user.

OpenCut classic dùng làm **UI chỉnh sửa + xuất edit-decision**. Preview trong OpenCut chạy client (WebCodecs trên proxy 360p) là đủ nhẹ. Render thật luôn server.

**Adapter clipspec ↔ OpenCut** là mảnh tích hợp chính cần làm; giữ clipspec là schema chuẩn của mình, map sang/từ định dạng project OpenCut.

---

## 9. Data model (SQLModel, pattern TaskRun/TaskItem)

- **`ClipJob`**: id, user_id, source_type(upload|link), source_ref, status(enum: queued|analyzing|scoring|rendering|done|error), params(json), source_sha256, created_at. Cache theo `source_sha256 + model_version` để phân tích một lần.
- **`Clip`**: id, job_id, rank, score, hook_text, bounds(start/end), clipspec(json), output_ref, status.
- **`ClipEdit`**: id, clip_id, version, clipspec(json), source(auto|opencut), created_at — lịch sử chỉnh sửa (từ auto-cut hoặc từ OpenCut), revert được.
- Enum status đặt cùng kiểu `TaskRunStatus`/`TaskItemStatus` hiện có.

---

## 10. API (REST + SSE)

| Method | Path | Việc |
|---|---|---|
| POST | `/clip-jobs` | Tạo job (upload multipart hoặc `{link}`) + params |
| GET | `/clip-jobs/{id}` | Trạng thái + list clip |
| GET | `/clip-jobs/{id}/events` | SSE tiến độ từng phase (EventBus sẵn) |
| GET | `/clips/{id}` | Chi tiết clip + clipspec |
| POST | `/clips/{id}/render` | Re-render theo clipspec (từ editor) |
| GET | `/clips/{id}/download` | Tải clip |

API này là hợp đồng ổn định — Telegram/OpenClaw/OpenCut-MCP sau gọi y hệt.

---

## 11. Tích hợp app hiện có

- Router `backend/app/routers/clip_jobs.py`, đăng ký trong `main.py`.
- Service `backend/app/services/clip_runner.py` theo pattern `task_runner.py` (async, `session_context`, EventBus SSE, single/queue run).
- Lõi pipeline `backend/app/services/clip_pipeline/` (prefilter.py, asr.py, score.py, cut.py, subtitle.py) — port từ fork.
- RBAC: permission `clip:create`/`clip:read` qua `permission_service` + `rbac_seed`.
- Frontend: trang mới `frontend/src/app`, nhúng OpenCut trong `frontend/src/components`, type `frontend/src/types`, gọi API qua `frontend/src/lib`.
- Phụ thuộc mới: `ffmpeg` trong image; `faster-whisper`/`whisper.cpp`, PhoWhisper weights, `librosa`, `ollama` client; nhúng OpenCut classic (submodule/package). Ghi vào requirements + Docker.

---

## 12. Xử lý lỗi

- PhoWhisper fail vùng nào → skip vùng, log, chạy tiếp (không đổ cả job).
- Ollama không chạy / thiếu model → fallback `heuristic`, cảnh báo trên UI.
- `claude` backend thiếu API key → báo lỗi sớm, gợi ý đổi `ollama`.
- ASR `local` quá chậm cho volume → gợi ý bật `cloud`.
- Link tải fail (private/giới hạn) → báo lỗi rõ, không treo job.
- GOP thưa, không có keyframe gần điểm cắt → nới cửa sổ tìm keyframe; nếu vẫn lệch nhiều, đánh dấu smartcut (re-encode 1 GOP mép) là mở rộng tương lai.
- File quá lớn / hết storage → chặn sớm, thông báo giới hạn.
- Adapter clipspec↔OpenCut gặp field lạ → bỏ qua an toàn, giữ giá trị auto-cut.

---

## 13. Test / eval

- **Golden set**: 3–5 video tiếng Việt (podcast + talking-head), người chọn tay đoạn "hay" làm ground-truth.
- **Metric**:
  - Recall vùng nóng so ground-truth (tầng 1 + LLM bắt đúng đoạn hay không).
  - Tỉ lệ cắt cụt từ (mid-word cut rate).
  - Tỉ lệ sai dấu câu / vỡ phụ đề.
  - Round-trip clipspec↔OpenCut không mất dữ liệu.
  - Thời gian end-to-end/1h **trên CPU**.
- `pytest` trong `backend/tests`. Chưa CI ở v1.

---

## 14. Rủi ro & giả định

- **Không GPU:** ASR chạy CPU (int8) — chấp nhận chậm hơn; prefilter-first bù lại. Volume lớn thì bật `cloud`.
- **Khôi phục dấu câu tiếng Việt chưa hoàn hảo** → ranh giới câu lệch; giảm bằng snap tới VAD-silence thay vì chỉ dựa dấu câu.
- **OpenCut classic vs mới:** v1 dùng classic (ổn định); bản mới (Rust, headless render, MCP) để mắt sau — hợp cho server render + agent nhưng "đang viết lại".
- **License:** repo lõi + OpenCut đều cần kiểm tra/tuân thủ (AI-Youtube-Shorts-Generator; OpenCut MIT). Ghi rõ nguồn.
- **Adapter clipspec↔OpenCut** là điểm tích hợp rủi ro nhất — cần test round-trip kỹ.
- **SeaLLM/Sailor chấm kém hơn Claude ở sắc thái** → cho chuyển `claude` khi cần.
- **Storage phình** (video gốc lớn) → xoá source sau khi xong, giữ clip.

---

## 15. Lộ trình xây (thứ tự cho writing-plans)

1. Data model + router + storage skeleton (ClipJob/Clip/ClipEdit, POST/GET, upload/link).
2. Fork repo, port lõi vào `clip_pipeline/`, chạy được trong worker.
3. prefilter (tầng 1) → giảm tải ASR.
4. PhoWhisper int8 CPU (faster-whisper/whisper.cpp) + khôi phục dấu câu.
5. Việt-hoá rubric + backend chấm (ollama mặc định, claude tuỳ chọn).
6. FFmpeg cut stream-copy + snap keyframe∩silence + sinh clipspec.
7. Burn sub ASS font đủ dấu (server render).
8. Frontend: trang job + tiến độ SSE + list clip.
9. Nhúng OpenCut classic + adapter clipspec↔OpenCut + re-render server.
10. Eval harness + golden set.

**Mở rộng sau v1:** kênh Telegram/OpenClaw qua REST API; OpenCut mới (headless render + MCP agent); smartcut GOP mép; multi-nguồn; ASR cloud khi scale.
