# Thiết kế: Giảm thời gian chạy pipeline video Flow Studio (reup + gen)

- **Ngày:** 2026-08-10
- **Nhánh:** dev-web-tool
- **Trạng thái:** Đã duyệt thiết kế, chuẩn bị lập kế hoạch triển khai

## 1. Mục tiêu

Giảm thời gian chờ của **một job** trên nguồn video dài (30–120 phút), và giảm CPU tiêu thụ cho mỗi job — mà **không đổi chất lượng đầu ra**.

Hình dạng tải đã xác định với người dùng:

- Video nguồn dài 30–120 phút.
- Một job chạy tại một thời điểm (không phải bài toán throughput nhiều user).
- Production chưa chốt máy; hiện chạy local Windows. Thiết kế phải không phụ thuộc phần cứng, và chỉnh được bằng cấu hình.

**Ngoài phạm vi, cố ý:**

- Không đổi thuật toán chấm điểm, chọn đoạn, dịch, hay style phụ đề.
- Không đổi độ phân giải hay chất lượng output.
- Không GPU, không cloud ASR. Chỉ chừa interface backend để cắm sau khi chốt máy production.
- Không đụng tới Face (comment/account/proxy).

## 2. Hiện trạng

Đường chạy reup (`backend/app/services/clip_runner.py`) và gen (`gen_runner.py`) đúng về thuật toán nhưng **tuần tự tuyệt đối**. Ngân sách thời gian ước lượng từ code cho nguồn 2 giờ:

| Stage | Hiện tại | Vấn đề |
|---|---|---|
| `resolve_source` (link) | yt-dlp tải 1080p, 2–4 GB | Chặn toàn bộ pipeline, dù phân tích chỉ cần audio |
| `extract_audio` | ffmpeg demux cả 2 giờ | Bắt buộc, nhưng đang chạy cả khi đã có transcript cũ |
| `detect_hot_regions` | `read_pcm16_mono` lần 1 | ~460 MB float32 cho 2 giờ ở 16 kHz |
| `detect_silences` | `read_pcm16_mono` **lần 2** | Decode lại y hệt; thêm vòng `for` Python trên ~72 000 frame |
| `transcribe_regions` | `read_pcm16_mono` **lần 3**, whisper **tuần tự** ~12 region × ≤90 s | Stage nặng nhất |
| `select_clips` | 1 call LLM | Không đáng kể |
| Mỗi clip × N | vòng `for` **tuần tự**: keyframe → cut → crop OpenCV → TTS **từng cue tuần tự** → burn x264 | Việc chờ mạng (TTS) đang khoá CPU và ngược lại |

Nguyên nhân gốc không phải thuật toán, mà là **lịch chạy**: mọi loại tài nguyên (CPU, mạng, I/O) dùng chung một luồng tuần tự, cộng với decode audio lặp ba lần và không tái dùng kết quả phân tích giữa các lần chạy.

`ClipJob.source_sha256` đã được lưu (`clip_runner._record_source`) nhưng chưa được dùng vào việc gì.

Tài sản có sẵn cần tái dùng:

- `backend/scripts/eval_pipeline.py` — harness offline đã đo per-stage wall clock, realtime factor, hot-region coverage/recall, mid-word-cut rate.
- `app.services.ai_pipeline.procs` — `spawn`/`communicate`/`kill_live` đã theo dõi tiến trình sống để huỷ job giết được ffmpeg.
- Event bus + SSE `phase` event, `frontend/src/components/flow-studio/JobProgress.tsx`.
- Retention sweeper trong `app/flow_worker.py`.

## 3. Kiến trúc lịch chạy

Nguyên tắc: **tách phân tích khỏi dựng, mỗi loại tài nguyên có hàng đợi riêng.**

| Loại việc | Ví dụ | Chính sách |
|---|---|---|
| CPU nặng | whisper, x264, OpenCV | Semaphore `FLOW_CPU_SLOTS`, mặc định `max(1, cores - 1)` |
| Chờ mạng | yt-dlp, edge-TTS, Pexels/Commons | Semaphore `FLOW_NET_SLOTS`, mặc định 8; riêng TTS `FLOW_TTS_SLOTS` mặc định 4 |
| Nhẹ | LLM, DB, ffprobe | Không giới hạn |

### 3.1 Module mới

**`backend/app/services/ai_pipeline/audio.py`**

```python
@dataclass(frozen=True)
class AudioTrack:
    samples: np.ndarray   # float32, mono, [-1, 1]
    sample_rate: int

    @property
    def duration_sec(self) -> float: ...

def load_track(wav_path: str) -> AudioTrack: ...
```

Decode **một lần**, truyền object đi tiếp. Không biết gì về job, DB, hay video.

**`backend/app/services/ai_pipeline/scheduling.py`**

Hai (ba) semaphore ở trên, cộng helper `run_cpu(coro)` / `run_net(coro)` / `run_tts(coro)`. Đặt cạnh `procs` để tiến trình bị `kill_live()` vẫn nhả slot. Slot **phải** nhả trong `finally`, không phải sau khi `await` trả về.

**`backend/app/services/ai_pipeline/analysis_cache.py`**

`get(cache_key) -> AnalysisPayload | None` và `put(cache_key, owner_id, payload)`. Không chứa logic pipeline, chỉ đọc/ghi bảng.

### 3.2 Module sửa

- **`prefilter.py`** — `detect_hot_regions` và `detect_silences` nhận `AudioTrack` thay vì đường dẫn WAV. Thuật toán không đổi. `detect_silences` vector hoá bằng `np.diff` trên mảng bool thay vòng `for` Python.
- **`asr_engine.py`** — `transcribe_regions` nhận `AudioTrack`; gom region thành batch (xem §5 bước D).
- **`source.py`** — thêm `resolve_source_audio_first()` cho nguồn LINK: tải `-f ba` (audio-only, ~50 MB cho 2 giờ) trước và trả về ngay, đồng thời khởi động task tải video 1080p chạy nền. Nguồn UPLOAD đi đường cũ không đổi.
- **`renderer.build_render_command`** và **`slideshow.build_slideshow_command`** — thêm `-threads`, giá trị `ceil(cores / FLOW_CPU_SLOTS)`.
- **`tts_engine.build_voice_track`** — vòng `for cue` thành `asyncio.gather` qua `run_tts`. Hành vi lỗi giữ nguyên: cue hỏng thì bỏ qua im lặng, hỏng hết thì trả `None` và clip giữ audio gốc.
- **`clip_runner._process`** — vòng `for segment in segments` thành `asyncio.gather` qua `run_cpu`. Lỗi một clip vẫn chỉ đánh `ClipStatus.ERROR` cho clip đó, đúng như hiện tại.
- **`gen_runner`** — `synthesize_scene_tracks` chạy song song qua `run_tts`; `resolve_backdrop` các scene chạy song song qua `run_net`.

### 3.3 Thứ tự chạy mới (reup)

```
resolve audio ──► decode 1 lần ──► prefilter ──► ASR ──► LLM score ──┐
     │                                                               │
     └─ tải video 1080p (task nền, song song) ──────────────────► join┘
                                                                     │
                                                                     ▼
                          gather N clip: [keyframe ▸ cut ▸ crop ▸ TTS ▸ burn] × N
```

`join` xảy ra ngay trước phase `RENDERING`. Nguồn UPLOAD bỏ qua nhánh tải, vào thẳng nhánh trên.

Ranh giới giữ nguyên quy ước sẵn có của repo: `clip_runner` chỉ điều phối, mọi thuật toán nằm trong `ai_pipeline.*`.

## 4. Cache phân tích

Transcript chỉ phụ thuộc audio và tham số ASR/prefilter. Nó **không** phụ thuộc `top_n`, `clip_min_sec`, `clip_max_sec`, `edit_instructions`, giọng đọc, hay backend LLM. Chạy lại cùng một video với chỉ thị biên tập khác đang trả giá full ASR một cách vô ích — và đó là vòng lặp thường gặp nhất của người dùng.

### 4.1 Bảng `clip_analysis`

Alembic migration, cùng Postgres, cùng module Flow.

| Cột | Kiểu | Ghi chú |
|---|---|---|
| `id` | UUID PK | |
| `cache_key` | text, unique index | sha256 của `(owner_id, audio_sha256, ASR_WHISPER_MODEL, ASR_COMPUTE_TYPE, CLIP_PIPELINE_VERSION, prefilter params)` |
| `owner_id` | UUID, **NOT NULL** | Cache tách theo user |
| `payload` | JSONB | `{version, language, regions[], words[], silences[]}` — giây tuyệt đối |
| `created_at`, `last_used_at` | timestamptz | |
| `hit_count` | int | Đo hiệu quả cache |

### 4.2 Khoá phải tính được **trước** khi làm việc nặng

- **UPLOAD**: `sha256` của file video, đã có sẵn ngay sau `resolve_source`.
- **LINK**: `sha256` của **file audio-only** vừa tải ở §3.2 — có trước khi video 1080p về.

`ClipJob.source_sha256` giữ nguyên ý nghĩa cũ (sha của video). Cache dùng cột riêng trong bảng riêng; schema hiện có không đổi.

### 4.3 Hành vi

- **Hit**: bỏ `extract_audio`, decode, prefilter, ASR. Vào thẳng scoring. Job 2 giờ chạy lại chỉ còn LLM + dựng clip.
- **Miss**: chạy như thường, ghi cache ở cuối stage phân tích.
- **Vô hiệu hoá**: đổi model, compute type, `CLIP_PIPELINE_VERSION`, hay tham số prefilter làm key đổi theo. Không cần xoá tay.
- **Lệch schema**: `payload.version` không khớp thì coi như miss, không đọc bừa.
- **TTL**: sweeper trong `flow_worker` xoá row có `last_used_at` cũ hơn `CLIP_ANALYSIS_TTL_DAYS` (mặc định 14).

**Không cache kết quả scoring.** Nó phụ thuộc `top_n`/`min`/`max`/`edit_instructions`/backend và chỉ tốn vài giây; cache vào là chuốc lấy bug vô hiệu hoá đổi lấy gần như không có lợi.

## 5. Lộ trình

Bảy bước, mỗi bước ship và đo độc lập. Thứ tự theo **rủi ro tăng dần**, không theo lợi ích — bước rẻ và an toàn đi trước để baseline vững trước khi động vào cái có thể đổi chất lượng.

| # | Bước | Cổng chấp nhận |
|---|---|---|
| A | Baseline: `eval_pipeline.py` xuất JSON per-stage; timing có cấu trúc ghi vào `ClipJob.params["timings"]` | Có số thật cho video mẫu dài |
| B | `AudioTrack` decode một lần; vector hoá `detect_silences` | Output **y hệt**; stage phân tích giảm |
| C | `scheduling.py`; clip song song; TTS song song; ghim `-threads` | Output **y hệt**; stage dựng giảm |
| D | ASR batched | Cổng chất lượng, không phải cổng "y hệt" — xem §6.3 |
| E | LINK: tải audio trước, video nền | Job link giảm; job upload không đổi |
| F | Bảng `clip_analysis` + migration + TTL trong sweeper | Chạy lại cùng video = hit, bỏ hẳn extract + prefilter + ASR |
| G | `progress` % trong SSE + `JobProgress.tsx` | Thanh tiến độ nhúc nhích suốt job |

## 6. Đo lường

Hai thứ khác nhau, cùng thuộc "nhanh": **nhanh thật** (đo được) và **có vẻ nhanh** (thấy được).

### 6.1 Baseline

Chưa có số nào — mọi ước lượng ở §2 suy ra từ code, không phải từ đo. Việc đầu tiên là baseline, không phải tối ưu.

- `scripts/eval_pipeline.py` xuất JSON per-stage (`seconds`, `realtime_factor`, `peak_rss`) ra `eval_out/<sha>-<git-rev>.json`.
- **Cần một video mẫu dài cố định (30–120 phút)** để so trước/sau. Không có nó thì không kết luận được gì. Đây là điều kiện tiên quyết của bước A.

### 6.2 Cổng chấp nhận (bước B, C, E, F)

Hai vế, **cả hai bắt buộc**:

1. **Nhanh hơn** — tổng wall clock giảm, so theo từng stage. Đo ở cấu hình thật (`SCORING_BACKEND=gemini`).
2. **Không đổi kết quả** — `start_sec`, `end_sec`, `subtitle_text` của mọi clip **giống hệt** baseline.

Vế 2 là hàng rào chính: đổi lịch chạy mà kết quả đổi nghĩa là đã lỡ tay đổi thuật toán.

**Vế 2 chỉ so được khi pipeline tất định**, nên nó chạy ở một cấu hình riêng, không phải cấu hình đo tốc độ:

- **Chỉ áp cho reup**, không áp cho gen: toàn bộ script của gen do LLM viết, chạy hai lần ra hai kết quả khác nhau một cách hợp lệ.
- **Chạy với `SCORING_BACKEND=heuristic`**. Tier heuristic của `scorer.py` thuần numpy, không mạng, tất định — nhờ vậy nó cô lập được thay đổi lịch chạy khỏi phương sai của LLM. Chạy vế 2 với backend `gemini` là tự tạo ra chênh lệch giả rồi đi truy nó.
- Với gen, cổng thay thế là: cùng một `VideoScript` cố định (fixture) thì timeline, cue, và độ dài video ra giống hệt.

### 6.3 Cổng riêng cho bước D

ASR batched có thể trả word timestamp lệch nhẹ so với đường tuần tự, nên **không** áp cổng "y hệt". Thay bằng cổng chất lượng sẵn có của harness: **mid-word-cut rate** và **hot-region recall** không được tệ đi so với baseline. Kèm cờ `ASR_BATCH_SIZE=0` để tắt về đường cũ nếu số xấu.

### 6.4 Đo trong production

Mỗi stage ghi timing có cấu trúc và lưu vào `ClipJob.params["timings"]`. Job chậm ở khách gỡ được mà không cần dựng lại.

### 6.5 Tiến độ hiển thị

Hiện SSE chỉ phát 4 phase. Job 15 phút thì thanh tiến độ đứng im hàng chục phút — người dùng tưởng treo. Thêm trường `progress` vào event `phase` đang có:

- Tải: % byte, parse từ `yt-dlp --newline`.
- ASR: region k/n.
- Dựng: clip k/n xong.

`JobProgress.tsx` đã có khung, chỉ thêm phần trăm. Với job dài, đây là thay đổi người dùng cảm nhận rõ nhất.

## 7. Rủi ro

Xếp theo mức độ sắc.

1. **x264 song song không ghim thread thì chậm hơn tuần tự.** Mỗi ffmpeg mặc định chiếm hết core; N tiến trình × N thread tranh nhau. Bắt buộc `-threads ceil(cores / FLOW_CPU_SLOTS)` trong cả `build_render_command` và `build_slideshow_command`. Bỏ sót là bước C phản tác dụng.

2. **Semaphore không nhả khi job bị huỷ thì worker kẹt vĩnh viễn.** `kill_live()` giết tiến trình đang giữ slot. Slot phải nhả trong `finally`. Lỗi này câm: job sau chỉ đơn giản là không bao giờ chạy. Cần test riêng cho đường huỷ.

3. **`BatchedInferencePipeline` chưa chắc dùng được ở phiên bản đang pin.** `backend/requirements.txt` đang ghim `faster-whisper==1.0.3`; API batched và khả năng trả `word_timestamps` trong chế độ batched khác nhau giữa các bản. Bước D **phải mở bằng việc xác minh** trên bản đang pin, và nâng pin lên ≥1.1.0 nếu cần. Pipeline bắt buộc có word timestamp — nếu chế độ batched không trả được, bước D chuyển sang phương án dự phòng (chạy nhiều instance model song song có giới hạn, hoặc chỉ tinh chỉnh `ASR_CPU_THREADS`/`ASR_BEAM_SIZE`) và ghi rõ lý do.

4. **edge-TTS là endpoint không chính thức.** Bắn song song nhiều có thể ăn 429 hoặc bị chặn IP. Slot TTS riêng mặc định 4, giữ nguyên retry backoff và hành vi bỏ qua im lặng hiện tại.

5. **RAM.** Whisper batch + N OpenCV + N ffmpeg cùng lúc. `FLOW_CPU_SLOTS` mặc định thận trọng; eval ghi `peak_rss`.

6. **Cache lệch schema.** `payload.version` không khớp thì coi như miss.

7. **Audio-first gọi yt-dlp hai lần.** Vài site giới hạn. Audio-only lỗi thì quay về đường tải video như cũ.

## 8. Cấu hình mới

Thêm vào `backend/app/config.py`, tất cả có mặc định an toàn:

| Khoá | Mặc định | Ý nghĩa |
|---|---|---|
| `FLOW_CPU_SLOTS` | `max(1, cores - 1)` | Số việc CPU nặng chạy đồng thời |
| `FLOW_NET_SLOTS` | `8` | Số việc chờ mạng chạy đồng thời |
| `FLOW_TTS_SLOTS` | `4` | Riêng cho edge-TTS |
| `ASR_BATCH_SIZE` | `8` | `0` = tắt batching, về đường tuần tự |
| `CLIP_ANALYSIS_CACHE_ENABLED` | `True` | |
| `CLIP_ANALYSIS_TTL_DAYS` | `14` | |
| `CLIP_SOURCE_AUDIO_FIRST` | `True` | Chỉ ảnh hưởng nguồn LINK |

`ASR_BACKEND` hiện đã khai báo `"local | cloud"` trong config nhưng `asr_engine.py` **chỉ hiện thực `local`** — nhánh `cloud` là stub. Thiết kế này không hiện thực nó, chỉ giữ nguyên chỗ cắm.
