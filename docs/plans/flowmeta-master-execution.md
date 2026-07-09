# FlowMeta SaaS Migration — Master Execution Plan

## MODULE A — Backend (Python FastAPI)

### A1. Codebase Scout (1 subagent, sequential)
Prompt: Xem file docs/plans/flowmeta-agents-gen-plan.md section "Subagent 1.1".
Output: docs/plans/01-codebase-scout.md

### A2. Backend Architect (3 subagents song song)
**A2a. FastAPI Scaffold + SQLAlchemy Models**
```
Build core scaffolding:
- app/main.py (FastAPI app + CORS + SSE middleware)
- app/db/postgres.py (SQLAlchemy async engine + session)
- app/db/redis.py (Redis sync client)
- app/models/sqlmodels.py: Profile, TaskRun, TaskLog, AppSetting, ProxyKey
- app/schemas.py: Pydantic DTOs for request/response
- requirements.txt
Output: code files + docs/plans/03a-backend-scaffold.md
```

**A2b. Profile Service + Task Engine**
```
Build business logic core:
- app/services/profile_service.py: CRUD, uid|token parse, dedup, token check
- app/services/task_service.py: BuildTasks → RunGroupedByUidAsync → ProcessSingleTaskAsync
  * Round-robin batches, delay rounds, blocked profile tracking
  * SSE log/stat publisher
- app/services/graph_service.py: Facebook Graph API v19.0
  * EditComment, DeleteComment, CreateComment
  * ExtractCommentId/ExtractPostId regex
  * Token issue detection (Checkpoint/Token out)
- app/routes/profiles.py: CRUD endpoints
- app/routes/tasks.py: /run, /stop, /logs/stream (SSE)
Output: code files + docs/plans/03b-backend-services.md
```

**A2c. KiotProxy Service + Redis State**
```
Build proxy layer:
- app/services/kproxy_client.py: KiotProxy API HTTP client
  * GetNewProxyAsync, GetCurrentProxyAsync
  * JSON expiry field normalization (Vietnamese/English/numeric/unix)
- app/services/proxy_service.py: round-robin, acquire/release, monitor
  * Redis CAS key + SET NX lock for lease
  * Auto-rotate uses=0, auto-refresh IP expire
  * Background asyncio task
- app/routes/proxy.py: /config, /start, /stop, /status
Output: code files + docs/plans/03c-backend-proxy.md
```

### A3. Backend Integration Test (1 subagent)
```
Stich A2a + A2b + A2c together:
- Verify all routes resolve
- SSE log streaming works
- Docker compose builds and runs
Output: docs/plans/04-backend-integration.md
```

---

## MODULE B — Frontend (Next.js 15)

### B1. Frontend Architect (1 subagent, sequential after A1)
Prompt: Xem file docs/plans/flowmeta-agents-gen-plan.md section "Subagent 2.2".
Output: docs/plans/05-frontend-architecture.md

### B2. Frontend Implementation (1 subagent)
```
Build all pages + SSE integration:
- app/accounts/page.tsx: profile table, import modal, token check
- app/auto-comment/page.tsx: 4-section form, Run/Stop, SSE log console
- app/proxy/page.tsx: proxy grid, IP countdown, Start/Stop
- app/settings/page.tsx: API keys, delay settings
- app/api/* routes: Next.js API routes as proxy to FastAPI BE
  * /api/profiles/*, /api/tasks/*, /api/proxy/*
  * SSE proxy endpoint for log streaming
- lib/api-client.ts: fetch wrapper
- lib/sse-client.ts: EventSource log streaming hook
UI: Tailwind v4 + shadcn/ui + Frost theme
Output: code files + docs/plans/06-frontend-pages.md
```

### B3. Frontend Polish (1 subagent)
```
- Error boundaries, loading skeletons, empty states
- Toast notifications (sonner)
- Responsive test at 1280px minimum
Output: docs/plans/07-frontend-polish.md
```

---

## MODULE C — DevOps + Quality (1 subagent)

### C1. Docker + CI (run after A3 + B3 done)
```
Build deployment:
- docker-compose.yml: fastapi + postgres + redis + nextjs
- backend/Dockerfile: python:3.12-slim multi-stage
- frontend/Dockerfile: node:alpine → nginx
- .env.example
- .github/workflows/ci.yml: build + test on push
- README-DEPLOY.md
Output: code files + docs/plans/08-devops.md
```

### C2. Final Audit (run after C1)
```
Run end-to-end checklist:
- Feature parity matrix
- docker compose up --build works from clean
- E2E test: import profiles → run task → see SSE logs
Output: docs/plans/09-final-audit.md
```

---

## Execution Order

```
A1 (Codebase Scout)
  ↓ CHECKPOINT: duyệt docs/plans/01-codebase-scout.md

A2a + A2b + A2c (song song — 3 subagents)
A2a: Scaffold + Models
A2b: Services + Routes
A2c: Proxy + KiotProxyClient

B1 (Architect) ─── song song với A2

  ↓ CHECKPOINT: duyệt 02 + 03 + 05

A3 (Integration)
B2 (FE Implementation) ─── song song với A3

  ↓ CHECKPOINT: duyệt 04 + 06

B3 (FE Polish) ─── song song với A3 (nếu còn)

  ↓ CHECKPOINT: duyệt 07

C1 (Docker + CI) ─── sau A3 + B2 + B3 xong

  ↓ CHECKPOINT: duyệt 08

C2 (Audit)
  ↓ DONE
```

---

## Output Directory Convention

```
docs/plans/
├── 01-codebase-scout.md          (A1)
├── 03a-backend-scaffold.md       (A2a)
├── 03b-backend-services.md       (A2b)
├── 03c-backend-proxy.md          (A2c)
├── 04-backend-integration.md     (A3)
├── 05-frontend-architecture.md   (B1)
├── 06-frontend-pages.md          (B2)
├── 07-frontend-polish.md         (B3)
├── 08-devops.md                  (C1)
└── 09-final-audit.md             (C2)
```

---

## Key Constraints
- Mỗi subagent phải báo cáo tiến độ sau mỗi task/phase: đã làm gì, sửa file/module nào, đã chạy check/test gì và kết quả, còn gì chưa xong hoặc bị block.
- Mỗi subagent output code hoàn chỉnh, không TODO/TBD
- FastAPI backend: async/await, SQLAlchemy 2.0 async, Redis via redis-py
- Next.js: App Router (app/), TypeScript, Tailwind v4, shadcn/ui
- SSE cho log streaming (đơn giản hơn SignalR)
- Single-user: không auth/JWT, không multi-tenant
- KiotProxy: giữ nguyên logic parsing từ WinForms

---

**SAO CHEP PHAN NAY QUA Moi subagent khac de lam theo.
