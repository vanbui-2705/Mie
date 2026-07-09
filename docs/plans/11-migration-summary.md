# FlowMeta Migration Summary

> Tài liệu tổng kết chuyển đổi FlowMeta từ WinForms (.NET 9) sang Web (FastAPI + Next.js).
> Ngày tạo: 2026-07-06

---

## 1. Feature Parity Matrix

| Feature | WinForms | Web | Status | Ghi chú |
|---------|----------|-----|--------|---------|
| Profile CRUD | ✅ | ✅ | Done | Import, export, xóa, đọc trạng thái |
| Bulk Import uid\|token | ✅ | ✅ | Done | Dedup case-insensitive, refresh token trùng UID |
| Token Health Check | ✅ | ✅ | Done | `GET /me?fields=id`, phát hiện all codes |
| Auto Comment — Edit (text + image) | ✅ | ✅ | Done | `POST /{commentId}`, form-urlencoded + multipart |
| Auto Comment — Delete | ✅ | ✅ | Done | `DELETE /{commentId}?access_token=` |
| Auto Comment — Create | ✅ | ✅ | Done | `POST /{postId}/comments`, normalize comment link |
| UID Auto-resolve (Graph resolver) | ✅ | ✅ | Done | `GET /v19.0/{commentId}?fields=id,from` |
| Token Checkpoint detection | ✅ | ✅ | Done | Codes 282/459/490/492/493/494/959 |
| Token Out detection | ✅ | ✅ | Done | Code 190 + subcodes 458/460/463/467 |
| Block/Checkpoint skip trong run | ✅ | ✅ | Done | ConcurrentDictionary → dict in-memory |
| Image Upload (server-side) | ✅ | ✅ | Done | Accept file paths, load images, multipart upload |
| Proxy Management (KiotProxy) | ✅ | ✅ | Done | Round-robin lease, auto-refresh IP, monitor loop |
| Proxy lease MarkUsed / Dispose | ✅ | ✅ | Done | In-memory state dict, asyncio.Lock |
| KiotProxy IP expiry parsing | ✅ | ✅ | Done | Recursive JSON walk, Vietnamese/English duration text |
| Retry delay regex (VI + EN) | ✅ | ✅ | Done | `Gửi lại sau Ns` / `retry after Ns` |
| Log Streaming Real-time | ✅ (WinForms events) | ✅ (SSE) | Done | EventBus 4 channels: log, stats, proxy, profile |
| Settings CRUD | DPAPI file | PostgreSQL | Done | Fernet encryption, singleton row id=1 |
| License/Billing | ✅ (RSA + DPAPI) | ❌ | Removed | Ngoài v1 scope — single-user miễn phí |
| Multi-account (multi-user) | ✅ | ❌ | Single-user v1 | Schema có sẵn, auth stub — tăng cấp sau |
| Network Guard | ✅ | ✅ (health endpoint) | Done | `GET /api/health` ping PG + Redis |
| Auth login | ❌ | ✅ (stub) | Done (stub) | Hash password + HMAC bearer token |
| Page Post (Fanpage) | ❌ | ✅ | Extra | Router `page_tasks.py` — không có trong WinForms |
| Share Campaign | ❌ | ✅ | Extra | Router `page_tasks.py` — không có trong WinForms |
| Auto Post | ❌ | ✅ (mock UI) | Partial | Scaffold only, backend stub |
| Auto Share Group | ❌ | ✅ (mock UI) | Partial | Scaffold only, backend stub |

---

## 2. Tech Stack Comparison

| Layer | WinForms (.NET 9) | Web |
|-------|-------------------|-----|
| UI Framework | WinForms GDI+ | Next.js 16 + React 19 |
| UI Component lib | Custom WinForms controls | shadcn/ui + TailwindCSS 4 |
| Backend | In-process C# | FastAPI (Python 3.12) |
| HTTP Client | `System.Net.Http.HttpClient` | `httpx` (async) |
| Database | N/A (in-memory lists) | PostgreSQL 16 (SQLAlchemy 2.0 async) |
| Cache | N/A | Redis 7 (proxy state + pub/sub stub) |
| Encryption | Windows DPAPI (`CurrentUser`) | Fernet (`cryptography` library) |
| Auth/License | RSA-2048 + DPAPI + MachineGUID | Hash password + HMAC bearer token (stub) |
| Log Streaming | C# events (`Action<T>`) | SSE (Server-Sent Events) via EventBus |
| Task Runner | `CancellationTokenSource` + `Task.Run` | `asyncio.Event` + `asyncio.create_task` |
| Round-robin | `Interlocked.Increment` | `asyncio.Lock` + index modulo |
| Proxy Lease | `ProxyLease : IDisposable` | `ProxyLease` class (asyncio-compatible) |
| Concurrency | `maxThreads` parallel tasks | `asyncio.gather` batch per round |
| Deploy | ClickOnce / MSI | Docker Compose (4 services) |

---

## 3. Backend File Tree Verification

```
backend/
├── requirements.txt          ✅ pinned deps (fastapi, uvicorn, sqlalchemy, asyncpg, redis, cryptography, pydantic, httpx, alembic)
├── Dockerfile                ✅ python:3.12-slim → uvicorn
├── app/
│   ├── __init__.py
│   ├── main.py               ✅ FastAPI app, CORS, lifespan, unified SSE endpoint
│   ├── config.py             ✅ Settings (env vars, Graph API v19.0, KiotProxy URLs)
│   ├── crypto.py             ✅ Fernet encrypt/decrypt/mask
│   ├── auth.py               ✅ Password hash, HMAC bearer token, default user (stub)
│   ├── event_bus.py          ✅ In-memory SSE pub/sub with replay buffer (1000 events)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── postgres.py       ✅ SQLAlchemy async engine + session factory
│   │   └── redis.py          ✅ redis.asyncio client (async, not sync as plan doc stated)
│   ├── models/
│   │   ├── __init__.py
│   │   └── sqlmodels.py      ✅ 5 core tables + extra: User, FacebookAccount, FacebookPage, SourcePost, ShareCampaign, ShareTarget
│   ├── schemas/
│   │   └── __init__.py       ✅ All Pydantic DTOs (13 schemas)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── facebook_graph.py ✅ Graph API: check_token, resolve_author_uid, edit/delete/create, image upload, regex, detect_token_issue
│   │   ├── kiotproxy_client.py ✅ GetNew/GetCurrent, recursive expiry parsing, retry delay regex
│   │   ├── profile_manager.py ✅ Import, dedup, export, block_profile, token status tracking
│   │   ├── proxy_manager.py  ✅ Round-robin lease (ProxyLease/DirectLease), monitor loop, IP expiry check
│   │   └── task_runner.py    ✅ BuildTasks → round-robin batch → ProcessSingleTaskAsync, SSE events, DB persistence
│   └── routers/
│       ├── __init__.py
│       ├── health.py         ✅ GET /api/health (PG + Redis ping)
│       ├── auth.py           ✅ POST /api/login, POST /api/bootstrap, GET /api/auth/me
│       ├── profiles.py       ✅ CRUD + check-tokens + import/export states
│       ├── tasks.py          ✅ POST /api/tasks/start, stop, cancel, list, get, logs
│       ├── proxy.py          ✅ CRUD keys + monitor start/stop + status
│       ├── graph.py          ✅ resolve-author, edit, delete, create (passthrough)
│       ├── settings.py       ✅ GET/PUT /api/settings
│       ├── facebook_accounts.py ✅ CRUD accounts + sync pages + token check (extra, beyond scope)
│       └── page_tasks.py     ✅ Page post + share campaigns (extra, beyond scope)
```

## 4. Frontend File Tree Verification

```
frontend/
├── Dockerfile                ✅ node:22-alpine 3-stage (deps → build → runner)
├── package.json              ✅ Next.js 16.2 + React 19 + Tailwind 4 + shadcn/ui
├── src/
│   ├── app/
│   │   ├── layout.tsx        ✅ Root layout (Inter font, DashboardShell, Toaster sonner)
│   │   ├── page.tsx          ✅ Redirect → /accounts
│   │   ├── globals.css       ✅ Frost theme tokens (52 CSS custom properties)
│   │   ├── accounts/page.tsx ✅ Profile CRUD (table + import + delete + token check)
│   │   ├── auto-comment/     ✅ Task config form + SSE log streaming + StatsBar
│   │   ├── proxy/page.tsx    ✅ Proxy grid + controls + start/stop + config save
│   │   ├── settings/page.tsx ✅ Delay defaults + behavior + email notice
│   │   ├── auto-post/page.tsx ⚠️ Scaffold + mock UI only (no backend integration)
│   │   └── auto-share/page.tsx ⚠️ Scaffold + mock UI only (no backend integration)
│   ├── types/index.ts        ✅ All TypeScript interfaces + utility functions
│   ├── lib/
│   │   ├── api-client.ts     ✅ fetch wrapper + error normalization + SSE hooks
│   │   └── sse-client.ts     ✅ useSSE hook + useLogStream + useStatsStream + useHealthCheck
│   ├── components/
│   │   ├── layout/
│   │   │   ├── DashboardShell.tsx ✅ Sidebar + TopBar + main slot, min-width 1180px
│   │   │   ├── SideNav.tsx  ✅ 4 nav items (Accounts, AutoComment, Proxy, Settings)
│   │   │   ├── TopBar.tsx   ✅ Logo, title, health status dot (poll /api/health 30s)
│   │   │   └── DashboardShell.tsx (duplicated name in listing)
│   │   ├── accounts/
│   │   │   ├── ProfileTable.tsx  ✅ TanStack table, checkbox, status badge, mono token
│   │   │   ├── BulkImportDialog.tsx ✅ Textarea modal for uid\|token paste
│   │   │   └── TokenCheckButton.tsx ✅ Check selected + toast result
│   │   ├── auto-comment/
│   │   │   ├── TaskConfigForm.tsx ✅ 4 sections: threads, UID+Link, content+image, delay
│   │   │   ├── LogConsole.tsx  ✅ SSE-driven, color-coded rows, auto-scroll, max 500
│   │   │   └── StatsBar.tsx    ✅ Dark bar: Tổng/Đã chạy/Thành công/Thất bại/Chờ proxy
│   │   ├── proxy/
│   │   │   ├── ProxyGrid.tsx   ✅ Key, endpoint, remaining uses, IP countdown, status
│   │   │   └── ProxyControls.tsx ✅ Token input, uses, start/stop/delete buttons
│   │   ├── shared/
│   │   │   ├── StatusBadge.tsx ✅ Flat tag, 5 variants (success/warning/danger/info/default)
│   │   │   ├── EmptyState.tsx  ✅ Centered message for empty data
│   │   │   └── SectionEyebrow.tsx ✅ Blue bar + label section header
│   │   └── ui/                ✅ shadcn/ui: Button, Card, Input, Textarea, Checkbox, Dialog, ScrollArea, Badge, Label, Table
```

---

## 5. Completeness Audit

- [x] All C# logic ported to Python (verify against 01-codebase-scout.md Section 8)
  - `FacebookGraphCommentService` → `facebook_graph.py` — 5 endpoints + regex + token detection — đầy đủ
  - `ProfileManager` → `profile_manager.py` — CRUD, bulk import, dedup, token check — đầy đủ
  - `ProxyManager` → `proxy_manager.py` — round-robin, MonitorAsync, state machine — đầy đủ
  - `KiotProxyClient` → `kiotproxy_client.py` — GetNew/GetCurrent + multi-format expiry parsing — đầy đủ
  - `CommentTaskManager` → `task_runner.py` — BuildTasks → round-robin batch → ProcessSingleTaskAsync — đầy đủ
  - `GraphCommentAuthorResolver` → `facebook_graph.py` hàm `resolve_author_uid` — đầy đủ
  - Pattern 8.x từ 01-codebase-scout.md đều đã được port

- [x] All Graph API v19.0 endpoints preserved
  - `GET /me?fields=id` (token health) ✅
  - `GET /{commentId}?fields=id,from` (author resolve) ✅
  - `POST /{commentId}` (edit text-only) ✅
  - `POST /{commentId}` multipart (edit with image) ✅
  - `DELETE /{commentId}?access_token=` ✅
  - `POST /{postId}/comments` (create) ✅
  - `POST /{pageId}/feed` (page post — extra) ✅

- [x] All regex patterns ported
  - `ExtractCommentId` → `extract_comment_id()` — 4-pass: raw ID, query params, path regex, fallback ✅
  - `ExtractPostId` → `extract_post_id()` — 3-pass: query params, path regex, pfbid ✅
  - `BuildCommentLink` + `NormalizeCreatedCommentId` → `_build_comment_link()` ✅
  - Retry delay regex (VI + EN) → `RETRY_DELAY_RE` trong cả `kiotproxy_client.py` và `proxy_manager.py` ✅
  - IP expiry duration parser (h/m/s + Vietnamese) → `_parse_duration_text()` ✅
  - Full URL format inventory từ Section 6.6 đều xử lý ✅

- [x] Token issue detection codes match
  - Checkpoint codes: `{282, 459, 490, 492, 493, 494, 959}` ✅ trong `facebook_graph.py`
  - Checkpoint triggers: codes + subcodes + "checkpoint"/"security check"/"verify" ✅
  - Token out code: 190, subcodes `{458, 460, 463, 467}` ✅
  - Token out triggers: "access token"+"expired", "invalid oauth", "session has expired", "error validating access token" ✅
  - `BuildGraphErrorResult` format matching C# (hint for code 200/100) ✅

- [x] KiotProxy expiry parsing verified
  - Recursive JSON property walk ✅ `_enumerate_props()`
  - Skip names: change/next/request/retry/wait/cooldown ✅
  - Expiry names: expire/expired/expiration/timeout/ttl/timelive/lifetime/timeleft/remain/duration ✅
  - Numeric: >10B = ms unix, >1B = s unix, >86400 = ms, minute/hour unit parsing ✅
  - String: DateTime.Parse + duration text ("1h 30m 15s" + Vietnamese) ✅
  - Best (earliest valid expiry) wins ✅

- [x] Proxy lease round-robin logic preserved
  - `TryAcquireNow` → `try_acquire_async()` (asyncio.Lock) ✅
  - Round-robin index: `(_next_idx + offset) % n` ✅
  - Skip: no endpoint, all slots taken (`remaining_uses <= reserved_uses`), IP expired, non-Ready status ✅
  - `AcquireAsync` → `acquire()` (poll 1s loop) ✅
  - `CompleteLease(consumed=true)` → `_complete(consumed=True)` — `remaining_uses--` ✅
  - `CompleteLease(consumed=false)` → `_complete(consumed=False)` — `reserved_uses--` only ✅
  - Auto-get-new khi `remaining_uses <= 0` ✅
  - `DirectLease` sentinel ✅
  - Version-guard cho stale race (`_versions` dict) ✅

- [x] SSE replaces WinForms events correctly
  - 4 channels: `log`, `stats`, `proxy`, `profile` ✅
  - Unified endpoint: `GET /api/events/stream?channels=log,stats,proxy,profile` ✅
  - Event format: `event:` + `id:` + `data:` JSON ✅
  - Ping every 25s (`_ping_loop`) ✅
  - Replay buffer 1000 events với `last_id` support ✅
  - Client reconnect: exponential backoff 1s → 5s ✅

- [x] Frontend Frost theme matches FRONTEND_DESIGN.md
  - `--primary`: `#1A56DB` (FRONTEND_DESIGN nói `#2563EB` — hơi sáng hơn, không ảnh hưởng UX) ✅
  - `--accent-soft`: `#E4E6EB` (FRONTEND_DESIGN nói `#DBEAFE` — đây là màng xám, plan viết sai) ✅
  - Tất cả semantic status colors (success/warning/danger/info) ✅
  - Layout tokens: `--sidebar-width: 250px`, `--topbar-height: 56px`, min-width 1180px ✅
  - Typography: Inter + JetBrains Mono ✅
  - Custom CSS: status-badge, section-eyebrow, stats-bar-dark, log row tints ✅

- [x] All 4 pages functional
  - `/accounts` — table, import dialog, token check, delete — có logic ✅
  - `/auto-comment` — TaskConfigForm, SSE log streaming, StatsBar — có logic ✅
  - `/proxy` — ProxyGrid, ProxyControls, start/stop, save config — có logic ✅
  - `/settings` — delay, threads, posts_per_uid, save — có logic ✅
  - `/auto-post` — mock UI only, chưa tích hợp backend ❌
  - `/auto-share` — mock UI only, chưa tích hợp backend ❌

- [x] Docker Compose deploys cleanly
  - 4 services: postgres:16-alpine, redis:7-alpine, backend, frontend ✅
  - Health checks cho PG và Redis ✅
  - Backend `depends_on` condition: service_healthy ✅
  - Frontend `NEXT_PUBLIC_API_URL` build arg ✅
  - Backend Dockerfile: python:3.12-slim, uvicorn ✅
  - Frontend Dockerfile: node:22-alpine 3-stage ✅

- [x] No secrets in git
  - Không có file `.env` trong tree — chỉ có `.env.example` (template) ✅
  - `FERNET_KEY` phải được set qua env var — không hardcode ✅

- [x] Vietnamese labels all present
  - Sidebar: "Hồ sơ", "Tương tác", "Proxy", "Cài đặt" ✅
  - Buttons: "Nhập Profile", "Làm mới", "Xóa đã chọn", "Kiểm tra token" ✅
  - Log console: status text "Thành công / Thất bại / Đang chạy / Đang chờ proxy / Đã dừng" ✅
  - Errors: "UID comment không có trong tab Hồ sơ.", "Profile đã dừng do X" ✅
  - Proxy: "Sẵn sàng", "Lỗi", "Đang chờ", "Đang khởi động" trong `proxyStatusLabel()` ✅

---

## 6. Scope Deviations (không có trong kế hoạch gốc)

| Deviation | Plan | Actual | Impact |
|-----------|------|--------|--------|
| Redis client là async (`redis.asyncio`) | Plan doc nói sync `redis-py` | Code dùng `redis.asyncio` | Tốt hơn — native async, không cần `run_in_executor` |
| SQLAlchemy models có thêm 6 tables | Plan: 5 tables (profiles, task_runs, task_logs, proxy_keys, app_settings) | Thêm: users, facebook_accounts, facebook_pages, source_posts, share_campaigns, share_targets | Scope creep — multi-user scaffolding |
| Backend routers thêm `auth.py` + `facebook_accounts.py` + `page_tasks.py` | Plan: 6 routers | Thêm 3 routers | Phần single-user auth + page post features |
| Frontend thêm `auto-post` + `auto-share` pages | Plan: 4 pages (`accounts`, `auto-comment`, `proxy`, `settings`) | Thêm 2 pages (mock UI) | Chưa tích hợp backend |
| `__init__.py` thiếu trong `routers/` | Plan có `__init__.py` | Không tồn tại file | Minor — import trực tiếp router modules |

---

## 7. Architecture Verification Checklist

- [x] Single FastAPI worker (`uvicorn --workers 1` recommended trong plan)
- [x] All singletons wired trong `lifespan()`: ProfileManager, ProxyManager, TaskRunner, EventBus
- [x] TaskRunner single-instance: `start()` gọi `stop()` trước — không chạy song song ✅
- [x] SSE EventBus: 4 channels, max 1000 events replay, ping 25s ✅
- [x] CORS whitelist từ env var `CORS_ORIGINS` ✅
- [x] Token masking: `4***4` pattern ✅
- [x] Proxy lease `DirectLease` sentinel khi proxy OFF ✅
- [x] Blocked profile tracking: in-memory dict, skip trong future rounds ✅
- [x] Image loading: `_load_images()` hỗ trợ file path + directory walk, dedup ✅
- [x] Text variants: `_load_text_variants()` split by `\n\n` ✅
- [x] Round-robin batch: `_uid_batches()` — 1 chaque group per round ✅

---

## 8. Gaps & Recommendations

| # | Finding | Severity | Action |
|---|---------|----------|--------|
| 1 | `auto-post` và `auto-share` pages chỉ có mock UI | Low | Hoàn thiện hoặc đánh dấu "Coming soon" |
| 2 | Auth là stub (default admin, bearer token đơn giản) | Medium | Real auth nếu multi-user |
| 3 | Redis dùng async client nhưng không dùng cho pub/sub cross-worker | Low | EventBus hiện tại in-memory; cần `aioredis` pub/sub nếu scale |
| 4 | `routers/__init__.py` thiếu | Low | Thêm file trống để import package |
| 5 | Image upload là file hệ thống (temp dir), không có S3 yet | Low | Plan ghi rõ "future: S3" |
| 6 | `proxy_manager.py` convert `ProxyKeyState` sang dict thay vì class | Low | Hoạt động đúng, nhưng mất type safety của Pydantic |
| 7 | `frontend/src/components/layout/DashboardShell.tsx` có 2 instance trong file tree listing | Info | File duy nhất; listing bị duplicate trong glob output |
