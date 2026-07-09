# 02 — Backend Architecture: FlowMeta Web App

> FastAPI backend architecture design for FlowMeta (Facebook AutoComment tool)
> Stack: FastAPI + SQLAlchemy 2.0 async + PostgreSQL 16 + Redis 7
> Generated: 2026-07-06

---

## 1. Folder Structure

```
backend/
├── requirements.txt                    # Python deps (pinned)
├── .env.example                        # Env vars template
├── app/
│   ├── __init__.py                     # Package init
│   ├── main.py                         # FastAPI app bootstrap, lifespan, routes
│   ├── config.py                       # Settings from env vars
│   ├── event_bus.py                    # In-memory SSE event bus
│   ├── crypto.py                       # Fernet encryption utilities
│   ├── models/
│   │   ├── __init__.py                 # Re-exports
│   │   └── sqlmodels.py                # SQLAlchemy ORM models
│   ├── schemas/
│   │   ├── __init__.py                 # All Pydantic DTOs
│   │   └── proxy.py                    # Proxy-specific DTOs (re-exported from __init__)
│   ├── db/
│   │   ├── __init__.py                 # get_session async generator
│   │   ├── postgres.py                 # AsyncEngine, session factory
│   │   └── redis.py                    # Sync Redis client wrapper
│   ├── services/
│   │   ├── __init__.py                 # Re-exports
│   │   ├── facebook_graph.py           # Graph API client (edit/delete/create)
│   │   ├── kiotproxy_client.py         # KiotProxy HTTP client
│   │   ├── proxy_manager.py            # Proxy lease pool (ported from C#)
│   │   ├── profile_manager.py          # Profile CRUD (ported from C#)
│   │   └── task_runner.py              # Core task execution engine
│   └── routers/
│       ├── __init__.py                 # Re-exports
│       ├── health.py                   # GET /health
│       ├── profiles.py                 # CRUD + token check
│       ├── tasks.py                    # Start/stop task, watchdog
│       ├── proxy.py                    # Proxy CRUD + monitor control
│       ├── graph.py                    # resolve-author, direct graph ops
│       └── settings.py                 # Get/put app settings
```

---

## 2. Database Schema

All tables live in the `public` schema. Single-user: no `user_id` FK — isolation is by deployment.

### 2.1 `profiles`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `uid` | VARCHAR(64) | PK, NOT NULL, CASE-INSENSITIVE (CITEXT) | Facebook UID |
| `token` | TEXT | NOT NULL | Encrypted (Fernet) at service layer before INSERT |
| `token_status` | VARCHAR(32) | NOT NULL DEFAULT 'Chua kiem tra' | Live/Die/Checkpoint/Chua kiem tra... |
| `task_count` | INTEGER | NOT NULL DEFAULT 0 | Cumulative tasks run |
| `last_error` | TEXT | NULL | Last error message |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | Updated by trigger |

Indexes:
- `CREATE UNIQUE INDEX idx_profiles_uid_ci ON profiles (LOWER(uid));` — case-insensitive uniqueness

### 2.2 `task_runs`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | UUID | PK, DEFAULT gen_random_uuid() | |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'running' | running|stopped|done|error |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |
| `finished_at` | TIMESTAMPTZ | NULL | |
| `action` | VARCHAR(16) | NOT NULL | edit\|delete\|new_comment |
| `max_threads` | INTEGER | NOT NULL | Concurrency per round |
| `delay_min` | INTEGER | NOT NULL DEFAULT 0 | Seconds |
| `delay_max` | INTEGER | NOT NULL DEFAULT 0 | Seconds |
| `delay_every_rounds` | INTEGER | NOT NULL DEFAULT 1 | Delay every N rounds |
| `text_input` | TEXT | NULL | Raw text (blurred in response) |
| `image_path` | TEXT | NULL | Server-side image folder path (in future: S3) |

Indexes:
- `CREATE INDEX idx_task_runs_created_at ON task_runs (created_at DESC);`

### 2.3 `task_logs`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | BIGSERIAL | PK | Auto-increment for ordering |
| `run_id` | UUID | FK → task_runs.id ON DELETE CASCADE | Parent run |
| `log_index` | INTEGER | NOT NULL | Sequential within run (for ordering) |
| `uid` | VARCHAR(64) | NULL | Profile UID (blank = unresolved) |
| `comment_link` | TEXT | NOT NULL | Original input link/post_id |
| `action` | VARCHAR(16) | NOT NULL | Edit/Delete/Comment moi |
| `proxy` | VARCHAR(128) | NOT NULL DEFAULT '' | Proxy display string |
| `status` | VARCHAR(32) | NOT NULL | Cho chay|Dang chay|Thanh cong|That bai|... |
| `error` | TEXT | NULL | Error/warning detail |
| `output_link` | TEXT | NULL | For create-comment: the new comment URL |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

Indexes:
- `CREATE INDEX idx_task_logs_run_id ON task_logs (run_id, log_index);`

### 2.4 `proxy_keys`

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | SERIAL | PK | |
| `api_key` | TEXT | NOT NULL | Encrypted (Fernet) at INSERT/UPDATE |
| `masked_key` | VARCHAR(32) | NOT NULL | For display (`First4***Last4`) |
| `current_proxy` | VARCHAR(128) | NULL | Last known proxy string |
| `remaining_uses` | INTEGER | NOT NULL DEFAULT 0 | Available slots |
| `reserved_uses` | INTEGER | NOT NULL DEFAULT 0 | Currently leased |
| `status` | VARCHAR(16) | NOT NULL DEFAULT 'Stopped' | Ready\|Waiting\|GettingNew\|Error\|Stopped\|Starting |
| `last_get_ip_at` | TIMESTAMPTZ | NULL | |
| `ip_expires_at` | TIMESTAMPTZ | NULL | |
| `last_checked_at` | TIMESTAMPTZ | NULL | Last health check |
| `next_get_new_at` | TIMESTAMPTZ | NULL | Retry backoff expiry |
| `last_error` | TEXT | NULL | |
| `endpoint_host` | VARCHAR(255) | NULL | Denormalized from endpoint JSON |
| `endpoint_port` | INTEGER | NULL | |
| `endpoint_username` | VARCHAR(128) | NULL | Encrypted |
| `endpoint_password` | VARCHAR(128) | NULL | Encrypted |
| `endpoint_display` | VARCHAR(255) | NULL | |
| `endpoint_expires_at` | TIMESTAMPTZ | NULL | |
| `created_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

Unique: `UNIQUE(masked_key)` — display dedup only; `api_key` itself is deduped by encryption.

### 2.5 `app_settings` (singleton table — exactly 1 row)

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `id` | SERIAL | PK, CHECK (id = 1) | Singleton constraint |
| `kiot_auth_token` | TEXT | NULL | Encrypted (Fernet) |
| `proxy_api_keys_enc` | TEXT | NULL | Encrypted bulk text |
| `get_new_url_template` | VARCHAR(512) | NOT NULL DEFAULT 'https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}' | |
| `get_current_url_template` | VARCHAR(512) | NOT NULL DEFAULT 'https://api.kioutproxy.com/api/v1/proxies/current?key={apiKey}' | |
| `uses_per_proxy` | INTEGER | NOT NULL DEFAULT 4 | |
| `proxy_check_interval` | INTEGER | NOT NULL DEFAULT 5 | Seconds |
| `interaction_threads` | INTEGER | NOT NULL DEFAULT 5 | |
| `posts_per_uid` | INTEGER | NOT NULL DEFAULT 1 | |
| `delay_min_seconds` | INTEGER | NOT NULL DEFAULT 0 | |
| `delay_max_seconds` | INTEGER | NOT NULL DEFAULT 0 | |
| `delay_every_rounds` | INTEGER | NOT NULL DEFAULT 1 | |
| `updated_at` | TIMESTAMPTZ | NOT NULL DEFAULT now() | |

---

## 3. API Route Mapping

| WinForms Action | Method | Path | Request Body | Response |
|----------------|--------|------|--------------|----------|
| Profiles: Load + Merge | `POST` | `/api/profiles/import` | `{ raw_text: str }` | `ProfileImportResult` (added/duplicate/errors) |
| Profiles: List all | `GET` | `/api/profiles` | — | `List[ProfileResponse]` |
| Profiles: Remove | `DELETE` | `/api/profiles` | `{ uids: list[str] }` | `{ removed: int }` |
| Profiles: Export text | `GET` | `/api/profiles/export` | — | `{ text: str }` |
| Profiles: Export states | `GET` | `/api/profiles/states` | — | `dict[str, SavedProfileState]` |
| Profiles: Apply states | `PUT` | `/api/profiles/states` | `{ states: dict }` | `{ applied: int }` |
| Profiles: Token check (all) | `POST` | `/api/profiles/check-tokens` | — | SSE stream (log entries) |
| Start task | `POST` | `/api/tasks/start` | `TaskStartRequest` | `{ run_id: str, status: str }` |
| Stop task | `POST` | `/api/tasks/{run_id}/stop` | — | `{ status: str }` |
| Task status | `GET` | `/api/tasks/{run_id}` | — | `TaskRunResponse` |
| List recent runs | `GET` | `/api/tasks` | — | `List[TaskRunSummary]` |
| SSE log stream | `GET` | `/api/logs/stream` | ?run_id=... | `text/event-stream` |
| SSE stats stream | `GET` | `/api/stats/stream` | — | `text/event-stream` |
| Proxy: list | `GET` | `/api/proxy/keys` | — | `List[ProxyKeyResponse]` |
| Proxy: add | `POST` | `/api/proxy/keys` | `{ api_key: str }` | `ProxyKeyResponse` |
| Proxy: remove | `DELETE` | `/api/proxy/keys/{key_id}` | — | `{ removed: bool }` |
| Proxy: start monitor | `POST` | `/api/proxy/monitor/start` | — | `{ started: bool }` |
| Proxy: stop monitor | `POST` | `/api/proxy/monitor/stop` | — | `{ stopped: bool }` |
| Proxy status | `GET` | `/api/proxy/status` | — | `List[ProxyKeyResponse]` |
| Graph: resolve author | `GET` | `/api/graph/resolve-author` | ?comment_link=&token= | `{ uid: str \| null }` |
| Settings: get | `GET` | `/api/settings` | — | `AppSettingsResponse` |
| Settings: put | `PUT` | `/api/settings` | `AppSettingsUpdate` | `{ updated: bool }` |
| Health check | `GET` | `/api/health` | — | `{ status, postgres, redis }` |

---

## 4. SSE Contract

### 4.1 Endpoints

| SSE Channel | Path | Publishes from |
|------------|------|----------------|
| Logs | `GET /api/logs/stream?run_id=<uuid>` | `TaskRunner` during task execution |
| Stats | `GET /api/stats/stream` | `TaskRunner` (task-wide counters) |
| Proxy | `GET /api/proxy/stream` | `ProxyManager` (monitor state changes) |
| Profile | `GET /api/profiles/stream` | `ProfileManager` (token status updates) |

Query param: `?channel=<name>` on `/api/events/stream` — a single multiplexed endpoint.

### 4.2 Unified Event Stream (preferred multiplexed endpoint)

```
GET /api/events/stream?channels=log,stats,proxy,profile
```

Event format (Server-Sent Events / `text/event-stream`):

```
event: log
id: log-00042
data: {"run_id":"a1b2c3...","log_index":42,"uid":"1000123","comment_link":"https://...","action":"Edit","proxy":"103.x.x.x:8080","status":"Thanh cong","error":"","output_link":"https://...","created_at":"2026-07-06T10:30:00Z"}

event: stats
id: stats-0015
data: {"total":50,"processed":23,"success":20,"failed":2,"waiting_proxy":1}

event: proxy
id: proxy-0003
data: {"key_id":3,"masked_key":"abcd***wxyz","status":"Ready","remaining_uses":4,"reserved_uses":0,"last_error":"","endpoint":{"host":"103.x.x.x","port":8080,"display":"103.x.x.x:8080","expires_at":"2026-07-06T10:55:00Z"}}

event: profile
id: profile-0007
data: {"uid":"1000123","token_status":"Checkpoint 282","last_error":"...","task_count":5}
```

### 4.3 Retry & Disconnect

- Server sends `: ping\n\n` every 25s to keep connections alive.
- Client reconnects with `Last-Event-ID` header; server replays from that ID if events are buffered (max 5 min backlog).
- Max 100 subscribers per channel; 429 if exceeded.

---

## 5. Redis Data Model

All keys use prefix `flowmeta:`.

### 5.1 Proxy Lease Locks (CAS — SET NX EX)

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `flowmeta:proxy:lock:{api_key_hash}` | String | 10s | CAS lock during `CompleteLease`. `SET key val NX EX 10` with UUID value, check with GET + Lua script |

Lua script for atomic CompleteLease (called from Python):

```lua
local key = KEYS[1]
local token = ARGV[1]
local current = redis.call('GET', key)
if current == token then
  redis.call('DEL', key)
  return 1 -- success
elseif current == false then
  return 0 -- key expired (TTL race)
else
  return -1 -- token mismatch (concurrent lease)
end
```

### 5.2 Task Runner Lock (single-task-at-a-time)

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `flowmeta:task:lock:active` | String | 0 (no expiry) | `SET active_run_id NX` — ensures one active task run only |

### 5.3 Rate-limit / Backoff Tracking

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `flowmeta:proxy:backoff:{key_id}` | String | Dynamic | Stores next retry timestamp; checked by monitor before re-requesting |

---

## 6. API Route Mapping — Detailed

### Profiles

| Operation | Method | Path | Notes |
|-----------|--------|------|-------|
| Import / merge | `POST` | `/api/profiles/import` | Body: `{ raw_text: str }`. Parses `uid|token` lines. Dedup by UID (case-insensitive). Duplicates refresh token, status = "Da refresh token" |
| List all | `GET` | `/api/profiles` | Returns `ProfileResponse[]` — token is **never** returned plain; use `masked_token` |
| Delete | `DELETE` | `/api/profiles` | Body: `{ uids: list[str] }` |
| Export raw | `GET` | `/api/profiles/export` | Returns `{ text: "uid1|token1\nuid2|token2\n" }` |
| Export states | `GET` | `/api/profiles/states` | Returns `{ states: { uid: { token_status, task_count, last_error } } }` |
| Apply states | `PUT` | `/api/profiles/states` | Body: `{ states: dict }`. Restore after reload |
| Check tokens (all) | `POST` | `/api/profiles/check-tokens` | SSES: publishes per-profile check result on `profile` channel |

### Tasks

| Operation | Method | Path | Notes |
|-----------|--------|------|-------|
| Start | `POST` | `/api/tasks/start` | Body: `TaskStartRequest`. Creates `task_run`, fires `asyncio.create_task(_runner.run(...))`, SSE pushes logs |
| Stop | `POST` | `/api/tasks/{run_id}/stop` | Sets `_stop_event` on runner, logs "Đã dừng" |
| Get status | `GET` | `/api/tasks/{run_id}` | Returns `TaskRunResponse` with aggregated stats |
| List recent | `GET` | `/api/tasks` | `?limit=10&offset=0` — list of `TaskRunSummary` |

### Proxy

| Operation | Method | Path | Notes |
|-----------|--------|------|-------|
| List keys | `GET` | `/api/proxy/keys` | Returns `ProxyKeyResponse[]` (masked api_key) |
| Add key | `POST` | `/api/proxy/keys` | Body: `{ api_key: str }`. Encrypts before INSERT |
| Remove | `DELETE` | `/api/proxy/keys/{key_id}` | |
| Start monitor | `POST` | `/api/proxy/monitor/start` | Calls `proxy_manager.start()` |
| Stop monitor | `POST` | `/api/proxy/monitor/stop` | Calls `proxy_manager.stop()` |
| Status | `GET` | `/api/proxy/status` | Returns live `ProxyKeyResponse[]` from manager snapshot |

### Settings

| Operation | Method | Path | Notes |
|-----------|--------|------|-------|
| Get | `GET` | `/api/settings` | single row, kiot_auth_token decrypted |
| Update | `PUT` | `/api/settings` | Body: `AppSettingsUpdate`. Encrypts sensitive fields before UPDATE |

### Graph (direct passthrough)

| Operation | Method | Path | Notes |
|-----------|--------|------|-------|
| Resolve author UID | `GET` | `/api/graph/resolve-author?comment_link=&token=&proxy_host=` | Calls Graph API, returns `{ uid }` |
| Edit comment | `POST` | `/api/graph/edit` | Body: `{ comment_id, access_token, new_text, image_path? }` |
| Delete comment | `DELETE` | `/api/graph/delete` | Body: `{ comment_id, access_token }` |
| Create comment | `POST` | `/api/graph/create` | Body: `{ post_id, access_token, text, image_path? }` |

---

## 7. Key Constants (ported from C#)

```python
# Graph API
GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}/"
GRAPH_API_TIMEOUT = httpx.Timeout(connect=5.0, read=45.0, write=5.0, pool=5.0)

# Token health check
TOKEN_CHECK_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)

# Author resolver
AUTHOR_RESOLVER_TIMEOUT = httpx.Timeout(connect=5.0, read=35.0, write=5.0, pool=5.0)

# KiotProxy
KIOTPROXY_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
KIOTPROXY_GET_NEW_TIMEOUT = 15.0  # seconds
KIOTPROXY_IP_LIFETIME = timedelta(minutes=30)

# Retry delay regex (Vietnamese + English)
RETRY_DELAY_RE = (
    r"(?:Gửi lại sau|Gui lai sau|retry after|try again in)"
    r"\s*(\d+)\s*(?:giây|giay|s|sec|secs|second|seconds)?"
)

# Token issue detection — Checkpoint
CHECKPOINT_CODES = {282, 459, 490, 492, 493, 494, 959}
CHECKPOINT_SUBCODES = {282, 459, 490, 492, 493, 494, 959}
CHECKPOINT_TEXT_MATCHES = ["checkpoint", "security check"]

# Token issue detection — TokenOut
TOKEN_OUT_CODE = 190
TOKEN_OUT_SUBCODES = {458, 460, 463, 467}
TOKEN_OUT_TEXT_PATTERNS = [
    ("access token", "expired"),
    "invalid oauth",
    "session has expired",
]

# Proxy monitor
PROXY_MONITOR_DEFAULT_INTERVAL = 5  # seconds
PROXY_ACQUIRE_RETRY_MS = 1000  # poll interval
IP_LIFETIME = timedelta(minutes=30)

# Defaults
USES_PER_PROXY_DEFAULT = 4
INTERACTION_THREADS_DEFAULT = 5
DELAY_DEFAULT = DelaySettings(min=0, max=0, every_rounds=1)

# Image extensions
IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".jfif", ".pjpeg", ".pjp",
    ".png", ".gif", ".webp", ".bmp", ".dib",
    ".tif", ".tiff", ".heic", ".heif", ".avif",
    ".ico", ".svg",
})

# SSE
SSE_PING_INTERVAL = 25  # seconds
SSE_MAX_SUBSCRIBERS_PER_CHANNEL = 100
SSE_EVENT_BUFFER_MAXSIZE = 1000  # per channel queue
SSE_EVENT_BUFFER_TTL = 300  # seconds (5 min replay window)
```

---

## 8. Authentication

None. Single-user app — no JWT, no session. The backend trusts all requests from the frontend origin (CORS restriction only). In production, place a reverse proxy (nginx/Caddy) in front for TLS termination.

---

## 9. Concurrency Model

```
Single uvicorn worker (--workers 1 recommended)
┌──────────────────────────────────────────────────┐
│  asyncio Event Loop                               │
│                                                   │
│  HTTP handler coroutines (10-50 concurrent)       │
│       │                                           │
│       └──► Shared services (app.state.services)   │
│              ├── ProfileManager (in-memory + DB)   │
│              ├── ProxyManager  (asyncio.Lock)      │
│              └── TaskRunner    (asyncio.Event)     │
│                    └──► fires events → EventBus    │
│                           ├── channel "log"        │
│                           ├── channel "stats"      │
│                           ├── channel "proxy"      │
│                           └── channel "profile"    │
│                                                   │
│  SSE producers (publish to EventBus)              │
│  SSE consumers (long-lived async generator)       │
└──────────────────────────────────────────────────┘
```

**Why single worker:** The original WinForms app had one task runner with at most `maxThreads` concurrent I/O. `uvicorn --workers 1` faithfully reproduces this. Redis is still used for cross-worker SSE pub/sub if scaling to N>1 workers later.

---

## 10. Error Handling Strategy

Matches original C# error semantics exactly:

| C# Error Path | Python Equivalent | HTTP Response |
|---------------|-------------------|---------------|
| `OperationCanceledException` | `asyncio.CancelledError` | Log + SSE event(status="Dung") |
| `IOException` (aborted) | `httpx.NetworkError` | Log + SSE event(status="That bai") |
| Graph API 4xx/5xx | `httpx.HTTPStatusError` | BuildGraphErrorResult → SSE event |
| KiotProxy timeout | `httpx.TimeoutException` | SetWaitingStatus → SSE proxy event |
| Token Checkpoint detected | DetokenIssue → BlockProfile | SSE profile event, skip in next rounds |
| Token Out detected | DetokenIssue → BlockProfile | Same |

---

## 11. PR Split Plan

### PR1: Scaffold + Models + DB + Crypto

Files:
- `requirements.txt`
- `app/config.py`
- `app/crypto.py`
- `app/models/sqlmodels.py`
- `app/db/postgres.py`
- `app/db/redis.py`
- `app/event_bus.py`
- `app/routers/health.py`
- `app/main.py` (app factory + CORS + health only)
- `alembic/` (initial migration, all 5 tables)

Deliverable: `pip install -r requirements.txt && uvicorn main:app --reload` starts, GET /api/health returns 200, empty DB created on first run (SQLAlchemy create_all).

### PR2: Profiles + Task Routes + Core Services

Files:
- `app/schemas/__init__.py`
- `app/services/facebook_graph.py`
- `app/services/profile_manager.py`
- `app/services/task_runner.py`
- `app/routers/profiles.py`
- `app/routers/tasks.py`
- `app/routers/graph.py`

Deliverable: Full profile CRUD via REST, task start/stop with SSE log streaming, direct Graph API passthrough routes.

### PR3: Proxy + Settings + Polish

Files:
- `app/services/kiotproxy_client.py`
- `app/services/proxy_manager.py`
- `app/routers/proxy.py`
- `app/routers/settings.py`
- SSE integration in `main.py` (register all channels)

Deliverable: Full proxy leasing (KiotProxy), settings CRUD with encryption, complete SSE channels (log/stats/proxy/profile).

---

*End of architecture document.*
