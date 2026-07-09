# PHASE 2 — PROMPTS READY (chờ Phase 1 xong rồi spawn)

## 2a. Backend Architect
```
Scope: FastAPI backend cho FlowMeta web app.
Input: Đọc docs/plans/01-codebase-scout.md (kết quả Phase 1) trước khi code.

Tech stack:
- FastAPI (Python 3.12+)
- SQLAlchemy 2.0 async (asyncpg)
- PostgreSQL 16
- Redis 7 (redis-py) cho proxy lease state + caching
- SSE (Server-Sent Events) cho realtime log streaming
- httpx cho HTTP client (Graph API + KiotProxy)

Output 1 — Thiết kế kiến trúc:
```
backend/
├── app/
│   ├── main.py              # FastAPI app + CORS + SSE middleware
│   ├── config.py
│   ├── db/
│   │   ├── postgres.py      # async engine + session factory
│   │   └── redis.py         # sync Redis client
│   ├── models/
│   │   └── sqlmodels.py     # SQLAlchemy models (Profile, TaskRun, TaskLog, ProxyKey, AppSetting)
│   ├── schemas/
│   │   ├── profile.py       # Pydantic request/response DTOs
│   │   ├── task.py
│   │   └── proxy.py
│   ├── services/
│   │   ├── profile_service.py
│   │   ├── task_service.py
│   │   ├── graph_service.py
│   │   ├── proxy_service.py
│   │   └── kproxy_client.py
│   └── routes/
│       ├── profiles.py
│       ├── tasks.py
│       └── proxy.py
├── alembic/
├── requirements.txt
├── Dockerfile
└── .env.example
```

Output 2 — Code đầy đủ cho 3 file cốt lõi:
- app/main.py (bootstrap + SSE route pattern)
- app/db/postgres.py
- app/models/sqlmodels.py

Output 3 — API contract table (endpoint | method | path | request | response)

Lưu vào: docs/plans/02-backend-architecture.md
```

## 2b. Frontend Architect
```
Scope: Next.js 15 frontend cho FlowMeta web app.
Input: Đọc FRONTEND_DESIGN.md + frontend/AGENTS.md + frontend/src/* hiện có trước khi code.

Tech stack (đã có sẵn trong frontend/):
- Next.js 15 App Router
- React 19 + TypeScript
- TailwindCSS 4
- shadcn/ui
- Sonner (toast)
- TanStack Table

Output 1 — Directory tree:
```
frontend/src/
├── app/
│   ├── (dashboard)/
│   │   ├── page.tsx              # Dashboard
│   │   ├── accounts/page.tsx     # Profile management
│   │   ├── auto-comment/page.tsx # Auto comment
│   │   ├── proxy/page.tsx        # Proxy management
│   │   └── settings/page.tsx     # Settings
│   └── layout.tsx
├── components/
│   ├── layout/
│   │   ├── topbar.tsx
│   │   └── sidebar.tsx
│   ├── ui/                      # shadcn components
│   └── features/
│       ├── profile-table.tsx
│       ├── task-form.tsx
│       └── proxy-grid.tsx
├── lib/
│   ├── api-client.ts            # fetch wrapper
│   └── sse-client.ts            # EventSource hook
└── styles/
    └── globals.css              # Frost theme tokens
```

Output 2 — Frost theme CSS variables:
- --background: #f0f2f5 ( frost-blue-50 )
- --foreground: #1a1a2e
- --primary: #1a56db ( frost-blue-800 )
- --accent: #e4e6eb ( frost-blue-100 )
- --success: #22c55e
- --warning: #f59e0b
- --danger: #ef4444

Output 3 — Component specs (mỗi component 1 file, đủ props + logic):
- TopBar: logo + title + status indicator
- Sidebar: 5 nav items với active state
- ProfileTable: TanStack table, checkbox select, token masked, status badge
- TaskForm: 4-section form (UID, Links, Action, Content), Run/Stop buttons
- ProxyGrid: key masked, IP countdown, Start/Stop toggle

Output 4 — SSE client hook: useSSE(url) → { logs, connected, error }

Lưu vào: docs/plans/03-frontend-architecture.md
```
