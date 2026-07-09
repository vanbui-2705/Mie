# FlowMeta SaaS Migration — Execution Plan

> **Goal:** Chuyển FlowMeta từ WinForms desktop → Next.js Web SaaS, giữ nguyên business logic cốt lõi (Graph API task engine, KiotProxy lease, log streaming). Scope giảm: bỏ license/billing module, đơn giản hóa auth.
>
> **Scope đã confirm:**
> ciac
>
> - Stack: **Next.js 15** + **Python FastAPI** + **PostgreSQL** + **Redis**
> - Features: Core only — Profiles, Auto Comment (Edit/Delete/Create), Proxy management
> - Proxy: KiotProxy only (giống WinForms)
> - Deploy: Self-host Docker Compose
> - License/Billing: **ĐÃ BỎ** — không có subscription, không có RSA license hệ thống
> - Multi-tenant: Single-user app (giảm độ phức tạo cho v1)

---

## Phase 0 — Scope Confirmation ✅ DONE

**Đã trả lời 7 câu:**
| # | Question | Answer |
|---|----------|--------|
| 1 | Tech Stack | **Python FastAPI** + Next.js + PostgreSQL + Redis |
| 2 | Feature Parity | Giảm scope — Core only (Profiles + AutoComment + Proxy) |
| 3 | Multi-tenant | Single-user app (v1) |
| 4 | Auth/License | Giảm scope — JWT đơn giản, bỏ license/billing |
| 5 | Proxy | Chỉ KiotProxy (giống WinForms) |
| 6 | Deploy | Self-host Docker Compose |
| 7 | License model | Không có license — open usage |

**→ Chuyển sang Phase 1: Codebase Scout**

---

## Phase 1 — Codebase Scout (1 subagent, sequential)

**Subagent 1.1: Codebase Explorer**

Prompt gửi c.ho subagent:

```
Bạn là kỹ sư nghiên cứu FlowMeta codebase. Đọc toàn bộ file quan trọng,
trả về bản đồ đầy đủ cho migration web sang FastAPI + Next.js.

Đọc:
1. CLAUDE.md, fb_automator_design_spec.md, FRONTEND_DESIGN.md
2. Form1.cs — flow chính, event wiring, service construction
3. Models.cs — tất cả models/enums
4. CommentService.cs, ProfileManager.cs, ProxyManager.cs, KiotProxyClient.cs
5. GraphCommentAuthorResolver.cs — resolve UID từ comment link

Trả về:
- File path, description, responsibilities
- Startup flow: Program.Main → NetworkGuard → Form1
- Graph execution flow: BuildTasks → RunGroupedByUidAsync → ProcessSingleTaskAsync
- Proxy lease lifecycle: ProxyLease.MarkUsed/Dispose → ProxyManager.AcquireAsync
- Error paths: checkpoint, token out, network timeout
- Facebook Graph API endpoints (method, path, params) — v19.0 hard-coded
- Tech patterns: No DI, round-robin, CancellationToken ownership
- Các regex extraction: ExtractCommentId, ExtractPostId

Lưu: docs/plans/01-codebase-scout.md (đầy đủ, không TODOs)
```

**Checkpoint 1:** Chủ project duyệt `docs/plans/01-codebase-scout.md`.

---

## Phase 2 — Architecture Design (2 subagents song song)

**Subagent 2.1: Backend Architect**

```
Đọc docs/plans/01-codebase-scout.md, trả về thiết kế backend FastAPI.
Tech: FastAPI + SQLAlchemy + PostgreSQL + Redis + SSE (Server-Sent Events)
Giữ nguyên logic: proxy lease, Graph API calls, token detection.
Single-user app — không cần JWT, auth đơn giản.

Trả về:
1. Folder tree: app/main.py, app/routes/, app/services/, app/models/, app/core/, app/db/
2. REST API route mapping từ WinForms action sang REST
3. SSE endpoint contract cho log streaming
4. Redis data model (keys, TTL, CAS cho proxy lease)
5. COMPLETE code: main.py bootstrap, SQLAlchemy models, sample routes,
   Redis client, KiotProxy client pattern
6. PR plan: PR1 scaffold, PR2 profiles CRUD, PR3 task engine + proxy

Lưu: docs/plans/02-backend-architecture.md
```

**Subagent 2.2: Frontend Architect**

```
Đọc FRONTEND_DESIGN.md, fb_automator_design_spec.md,
frontend/AGENTS.md, frontend/src/* hiện có.
Stack confirm: Next.js 15 App Router + TS + Tailwind v4 + shadcn/ui + Sonner

Trả về:
1. Init script cho shadcn/ui + component list đầy đủ
2. Complete tailwind.config.ts + globals.css (Frost theme)
3. Directory tree: app/(dashboard)/, components/layout/, components/ui/
4. Layout shell: TopBar + Sidebar + Outlet, collapse mobile, active path
5. 6 page skeletons: /dashboard, /accounts, /auto-comment,
   /auto-post, /auto-share, /proxy, /settings
6. Mock API layer (frontend/lib/api/*.ts) — SSE client cho log streaming
7. PR plan: PR1 scaffold, PR2 layout+pages, PR3 API integration

Lưu: docs/plans/03-frontend-architecture.md
```

**Checkpoint 2:** Duyệt `docs/plans/02-backend-architecture.md` + `docs/plans/03-frontend-architecture.md`.

---

## Phase 3 — Implementation (3 subagents song song)

**Subagent 3.1: Backend — Profile + Task Engine**

```
Đọc docs/plans/02-backend-architecture.md + reference WinForms files.
Code COMPLETE (FastAPI):

1. models/sqlmodels.py: SQLAlchemy models (Profile, TaskRun, TaskLog, AppSetting)
2. services/profile_service.py: CRUD, bulk import uid|token, dedup, token health check
3. services/task_service.py: BuildTasks → RunGroupedByUidAsync → ProcessSingleTaskAsync
   - ResolveTasksAsync, GroupBy UID, batch rounds
   - AcquireAsync proxy lease từ Redis
   - ExecuteAsync qua Graph API abstraction
   - Log + Stats → SSE queue
4. services/graph_service.py: Facebook Graph API client
   - Edit/Delete/CreateComment, image upload
   - Token issue detection (Checkpoint 282/459, Token out 190/458)
   - ExtractCommentId/ExtractPostId regex
5. routes/profiles.py: CRUD endpoints
6. routes/tasks.py: /run, /stop, /logs/stream (SSE)
7. main.py: FastAPI app bootstrap + CORS + SSE middleware

Lưu: docs/plans/04-backend-core.md + code files
```

**Subagent 3.2: Backend — Proxy + Infrastructure**

```
Đọc docs/plans/02-backend-architecture.md + ProxyManager.cs + KiotProxyClient.cs.
Code COMPLETE:

1. services/kproxy_client.py: KiotProxy API client
   - GetNewProxyAsync, GetCurrentProxyAsync (giữ nguyên logic parsing)
   - Expiry detection: recursive JSON walk cho "expire", "ttl", "lifetime"
2. services/proxy_service.py: round-robin, acquire/release, background monitor
   - Redis-based state: CAS key + SET NX lock
   - ProxyLease pattern: MarkUsed → decrement, Dispose → return
   - Auto-rotate khi uses=0, auto-refresh khi IP expire
3. services/storage.py: PostgreSQL + Redis clients, session management
4. routes/proxy.py: config CRUD, start/stop, status

Lưu: docs/plans/05-backend-proxy.md + code files
```

**Subagent 3.3: Frontend — Pages + SSE Integration**

```
Đọc docs/plans/03-frontend-architecture.md + design specs + frontend/src/ hiện có.
Code COMPLETE:

1. app/accounts/page.tsx: profile table, import modal, token check button
2. app/auto-comment/page.tsx: 4-section form
   (UID, Links, Action, Content+Images) + proxy+delay config
3. app/proxy/page.tsx: proxy grid, status badge, IP countdown, Start/Stop
4. app/settings/page.tsx: API keys, proxy default, delay settings
5. SSE client integration: EventSource log streaming, color-coded console
6. Shadcn components đầy đủ: table, dialog, badge, toast, tabs, textarea

Lưu: docs/plans/06-frontend-pages.md + component/page files
```

**Checkpoint 3:** Duyệt `docs/plans/04`, `05`, `06`.

---

## Phase 4 — Integration + Polish (1 subagent)

**Subagent 4.1: Integration Bridge**

```
Đọc outputs Phase 2 + Phase 3.
Code COMPLETE:

1. API Integration: connect tất cả pages → backend API
   - React Query / fetch với interceptors
   - Log streaming từ SSE vào console component
   - Token check → table state machine
2. Realtime: SSE client, auto-scroll log, color-coded
3. Settings flow hoàn chỉnh
4. Responsive test, error boundary, empty states

Lưu: docs/plans/08-integration.md
```

**Checkpoint 4:** End-to-end test pass.

---

## Phase 5 — Deploy + Documentation (2 subagents song song)

**Subagent 5.1: DevOps**

```
Docker + CI.
Output COMPLETE:

1. docker-compose.yml: backend + postgres + redis + frontend
2. .env.example
3. Frontend Dockerfile: node:alpine multi-stage
4. Backend Dockerfile: python:3.12-slim multi-stage
5. .github/workflows/ci.yml

Lưu: docs/plans/09-devops.md + docker files
```

**Subagent 5.2: Docs + Audit**

```
Review toàn bộ. Output:
1. Feature parity matrix
2. Migration guide (user-facing)
3. Known limitations + roadmap
4. Final audit: security, perf, realtime contract

Lưu: docs/plans/10-final-audit.md
```

**Checkpoint 5 (Final):** docker compose up thành công, E2E flow pass.

---

## Concurrency Diagram

```
Phase 0: Confirm scope (input only) ─── DONE
  ↓
Phase 1 ── 1 subagent chạy tuần tự (Codebase Scout)
  ↓ CHECKPOINT 1
Phase 2 ── 2 subagents song song (BE Architect + FE Architect)
  ↓ CHECKPOINT 2
Phase 3 ── 3 subagents song song (BE core + BE proxy + FE pages)
  ↓ CHECKPOINT 3
Phase 4 ── 1 subagent (Integration + Polish)
  ↓ CHECKPOINT 4
Phase 5 ── 2 subagents song song (DevOps + Docs+Audit)
  ↓ DONE
```

---

## Key Principles

- Mỗi subagent phải báo cáo tiến độ sau mỗi task/phase: đã làm gì, sửa file/module nào, đã chạy check/test gì và kết quả, còn gì chưa xong hoặc bị block.
- Output mỗi phase vào `docs/plans/{nn}-{ten}.md`
- Mỗi subagent code đầy đủ, không TODO/TBD
- Backend + Frontend chia rõ contracts qua Phase 2 API spec
- Single-user app — không cũi multi-tenant overhead
- Proxy lease pattern Redis-backed, single-instance safe
