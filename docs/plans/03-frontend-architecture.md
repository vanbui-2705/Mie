# 03 — Frontend Architecture: FlowMeta Web

> Next.js 16 + React 19 + TailwindCSS 4 + shadcn/ui + SSE streaming
> Frozen: 2026-07-06

---

## 1. Frost Theme CSS Token System

All tokens defined as CSS custom properties in `globals.css` under `:root`. TailwindCSS 4 `@theme inline` maps them to utility classes. No color used inline — every value references a token.

### 1.1 Surface & Background

| Token | Value | Usage |
|-------|-------|-------|
| `--background` | `#F8FAFC` | App main background |
| `--foreground` | `#0F172A` | Primary text |
| `--panel` | `#FFFFFF` | Card, panel, table row even |
| `--surface-row` | `#F1F5F9` | Grid alternating row, hover row |
| `--surface-dark` | `#1E293B` | Grid header, stats bar, section eyebrow |
| `--surface-dark-foreground` | `#FFFFFF` | Text on dark surfaces |

### 1.2 Brand

| Token | Value | Usage |
|-------|-------|-------|
| `--accent` | `#2563EB` | Primary buttons, links, focus ring, active tab |
| `--accent-hover` | `#1D4ED8` | Button hover state |
| `--accent-soft` | `#DBEAFE` | Badge background, tag background |
| `--accent-foreground-on-soft` | `#1E40AF` | Text on accent-soft bg |

### 1.3 Semantic Status

| Token | Value | Usage |
|-------|-------|-------|
| `--success` | `#059669` | Live/Thành công status text |
| `--success-soft` | `#D1FAE5` | Success badge bg |
| `--success-foreground-on-soft` | `#065F46` | Text on success-soft |
| `--warning` | `#D97706` | Warning status text (ĐIỂM NHẤN ẤM DUY NHẤT) |
| `--warning-soft` | `#FEF3C7` | Warning badge bg |
| `--warning-foreground-on-soft` | `#92400E` | Text on warning-soft |
| `--danger` | `#DC2626` | Error/die status, delete button |
| `--danger-soft` | `#FEE2E2` | Danger badge bg |
| `--danger-foreground-on-soft` | `#991B1B` | Text on danger-soft |
| `--info` | `#0891B2` | Running/waiting proxy status |
| `--info-soft` | `#CFFAFE` | Info badge bg |
| `--info-foreground-on-soft` | `#155E75` | Text on info-soft |

### 1.4 Neutral

| Token | Value | Usage |
|-------|-------|-------|
| `--text` | `#0F172A` | Primary label, body text |
| `--text-sub` | `#64748B` | Secondary label, placeholder |
| `--border` | `#E2E8F0` | Input border, panel border |
| `--divider` | `#F1F5F9` | Thin row separator |
| `--input-bg` | `#FFFFFF` | Input field background |

### 1.5 Typography

| Token | Value | Usage |
|-------|-------|-------|
| `--font-sans` | `'Inter', 'Segoe UI', system-ui, sans-serif` | All UI text |
| `--font-mono` | `'JetBrains Mono', 'Cascadia Code', Consolas, monospace` | UID, token, link, ID |

### 1.6 Motion

| Token | Value | Usage |
|-------|-------|-------|
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | Hover lift |
| `--duration-fast` | `80ms` | Button press |
| `--duration-normal` | `120ms` | Hover, tab switch |

### 1.7 Layout

| Token | Value | Usage |
|-------|-------|-------|
| `--sidebar-width` | `250px` | Sidebar fixed width |
| `--topbar-height` | `56px` | TopNav height |
| `--min-viewport-width` | `1180px` | v1 desktop only |

---

## 2. Directory Tree

```
frontend/src/
├── app/
│   ├── globals.css                          ← Frost theme tokens + Tailwind
│   ├── layout.tsx                           ← Root layout (Inter font, DashboardShell)
│   ├── page.tsx                             ← Redirect → /accounts
│   ├── accounts/
│   │   └── page.tsx                         ← Profile management page
│   ├── auto-comment/
│   │   └── page.tsx                         ← Auto-comment task page
│   ├── proxy/
│   │   └── page.tsx                         ← Proxy management page
│   └── settings/
│       └── page.tsx                         ← Settings page
├── components/
│   ├── layout/
│   │   ├── DashboardShell.tsx               ← Left sidebar + topbar + page slot
│   │   ├── TopBar.tsx                       ← Logo/title/status indicators
│   │   └── SideNav.tsx                      ← 4 nav items (Accounts, AutoComment, Proxy, Settings)
│   ├── accounts/
│   │   ├── ProfileTable.tsx                 ← Data table: UID, masked token, status, task count, error
│   │   ├── BulkImportDialog.tsx              ← Textarea modal for uid|token bulk paste
│   │   └── TokenCheckButton.tsx              ← "Kiểm tra token" with loading/result states
│   ├── auto-comment/
│   │   ├── TaskConfigForm.tsx               ← 4-section form: threads, UIDs, links/posts, content
│   │   ├── LogConsole.tsx                   ← SSE-driven log grid with color-coded rows
│   │   └── StatsBar.tsx                     ← Dark bar: Tổng | Đã chạy | Thành công | Thất bại | Chờ proxy
│   ├── proxy/
│   │   ├── ProxyGrid.tsx                    ← Grid: key, endpoint display, remaining, IP countdown, status
│   │   └── ProxyControls.tsx                ← Start/Stop/Delete buttons + config inputs
│   └── shared/
│       ├── StatusBadge.tsx                  ← Flat tag with left border, soft bg, colored text
│       ├── EmptyState.tsx                   ← Centered message for empty data
│       └── SectionEyebrow.tsx               ← [blue bar][label] section header component
├── lib/
│   ├── api-client.ts                        ← Fetch wrapper: base URL, auth header, error normalization
│   ├── sse-client.ts                        ← useSSE hook: EventSource, auto-reconnect, color-coded types
│   └── utils.ts                              ← cn() helper (existing)
└── types/
    └── index.ts                              ← Shared TypeScript interfaces
```

---

## 3. Component Specs

### 3.1 Layout Shell

**File:** `src/components/layout/DashboardShell.tsx`

**Logic:**
- Renders `<aside>` (SideNav) + `<div>` (TopBar + `<main>` children slot)
- `min-width: 1180px` enforced on root container
- No routing logic — children are rendered by App Router page

**State:** None (static shell)

---

**File:** `src/components/layout/TopBar.tsx`

**Props:** None

**Logic:**
- Left: FlowMeta wordmark (text "FlowMeta" + subtitle "Comment Edit Delete")
- Center: nothing (breathing room)
- Right: system status dot (green "Online" via polling `GET /api/health` every 30s)
- Height: 56px; bg: `var(--panel)`; border-bottom: 1px `var(--border)`

**State:** `status: 'online' | 'offline' | 'checking'`

---

**File:** `src/components/layout/SideNav.tsx`

**Props:** None

**Logic:**
- Uses `usePathname()` for active state
- 4 items: Accounts, AutoComment, Proxy, Settings
- Each item: icon + label; active: left border 3px accent + bg accent-soft + text accent

**Nav items:**

| Label | Href | Icon |
|-------|------|------|
| Hồ sơ | /accounts | Users |
| Tương tác | /auto-comment | MessageSquare |
| Proxy | /proxy | Globe2 |
| Cài đặt | /settings | Settings |

**State:** `pathname` from `usePathname()`

---

### 3.2 Accounts Page

**File:** `src/app/accounts/page.tsx`

**Page-level state:**
- `profiles: ProfileRow[]` — fetched on mount
- `selectedUids: Set<string>` — checkbox selections
- `importDialogOpen: boolean`
- `loading: boolean`
- `error: string | null`

**Sub-components:**

**ProfileTable** (`src/components/accounts/ProfileTable.tsx`)
- Props: `profiles`, `selectedUids`, `onSelectionChange`
- Columns (matching FRONTEND_DESIGN spec):
  - Checkbox (44px) — header checkbox selects all
  - STT (50px, center) — row index
  - UID (150px, mono)
  - Token (masked, mono) — masked via `maskToken()` before render
  - Trạng thái (140px) — `<StatusBadge>`
  - Tác vụ (70px) — task count number
  - Lỗi gần nhất (auto) — wrapped text, color = status
- Rows: even=panel, odd=surface-row
- Empty state: "Nhấn chuột phải → Nhập dữ liệu để bắt đầu" (TextSub italic)
- Loading skeleton: 5 shimmer rows
- Error: "Không thể tải danh sách profile" with retry button

**BulkImportDialog** (`src/components/accounts/BulkImportDialog.tsx`)
- Props: `open`, `onClose`, `onImport`
- Textarea 8 rows, placeholder "1000123456|EAAG...\n1000654321|EAAG..."
- "Nhập dữ liệu" + "Hủy" buttons
- On import: POST `/api/profiles/import`, body `{ text }`

**TokenCheckButton** (`src/components/accounts/TokenCheckButton.tsx`)
- Props: `profileIds: string[]`, `disabled: boolean`
- Calls `POST /api/profiles/check-tokens` with selected UIDs
- States: idle → loading (spinning) → result (count of live/die/checkpoint flashed in toast)
- Uses `toast` from `sonner`

---

### 3.3 Auto Comment Page

**File:** `src/app/auto-comment/page.tsx`

**Page-level state:**
- `running: boolean`
- `stats: TaskStats | null` — updated via SSE
- `logs: LogEntry[]` — updated via SSE (bounded array, max 500)
- `config: TaskConfigFormData` — form state

**Sub-components:**

**TaskConfigForm** (`src/components/auto-comment/TaskConfigForm.tsx`)
- Props: `onStart: (config) => void`, `onStop: () => void`, `running: boolean`
- 4 sections (per FRONTEND_DESIGN):
  1. Luồng — numeric input "Số luồng", [Bắt đầu]/[Dừng] buttons
  2. UID + Link — two textareas: "UID Profile" (placeholder: auto-check if empty) and "Link bài viết"
  3. Nội dung — textarea for comment text + optional image folder input
  4. Delay — "Delay từ [0] đến [0] sau mỗi vòng: [1]"
- Validation: all fields pass before start fires
- Button states: disabled while running (except Stop)

**LogConsole** (`src/components/auto-comment/LogConsole.tsx`)
- Props: `logs: LogEntry[]`, `running: boolean`
- SSE-driven: new entries scroll into view
- Columns: STT, UID, Link, Hành động, Proxy, Trạng thái, Lỗi
- Row color: background tint matches status (success-soft, danger-soft, info-soft, warning-soft)
- Max height: 400px, scrollable, auto-scrolls to bottom when `running` is true
- Pause scroll toggle button

**StatsBar** (`src/components/auto-comment/StatsBar.tsx`)
- Props: `stats: TaskStats | null`
- Renders: "Tổng: N | Đã chạy: N | Thành công: N | Thất bại: N | Đang chờ proxy: N"
- Each number colored: accent, success, danger, info
- Background: `var(--surface-dark)`, text: white, padding: 10px

---

### 3.4 Proxy Page

**File:** `src/app/proxy/page.tsx`

**Page-level state:**
- `proxyKeys: ProxyKeyState[]`
- `config: ProxyConfig` — KiotProxy token, API keys, URLs, check interval
- `running: boolean`

**Sub-components:**

**ProxyGrid** (`src/components/proxy/ProxyGrid.tsx`)
- Props: `keys: ProxyKeyState[]`
- Columns: STT, Key (masked), Proxy endpoint, Remaining/IP countdown, Trạng thái
- Each row: status badge (`<StatusBadge>`), remaining uses with countdown indicator
- "Đang chạy" = info status; "Ready" = success; "Waiting" = warning; "Lỗi" = danger

**ProxyControls** (`src/components/proxy/ProxyControls.tsx`)
- Props: `config`, `onConfigChange`, `running`, `onStart`, `onStop`
- Inputs: Token Kiot (password masked), Lượt mỗi IP (number), API keys textarea, URLs, check interval
- [Lưu cấu hình] [Bắt đầu proxy] [Dừng] [Xóa] buttons

---

### 3.5 Settings Page

**File:** `src/app/settings/page.tsx`

**Page-level state:**
- `settings: AppSettings | null`
- `saving: boolean`
- `saved: boolean` (triggers toast)

**Content:**
- API Keys section: KiotProxy auth token input (password type)
- Delay defaults section: min, max, every rounds inputs
- Behavior section: interactions per round, threads default
- Each section: label group + inputs + "Lưu" button per section
- Save fires `PUT /api/settings` with partial payload
- Success: Sonner toast "Đã lưu cài đặt"

---

### 3.6 Shared Components

**StatusBadge** (`src/components/shared/StatusBadge.tsx`)
- Props: `status: ProfileStatus | string`, `className?: string`
- Maps status string to token variant:
  - "Live"/"Thành công"/"Ready" → success
  - "Checkpoint"/"Token out" → danger
  - "Đang chờ" → warning
  - "Đang chạy" → info
  - Default → text-sub
- Render: span with `border-left: 3px solid {color}`, `background: {soft}`, `color: {color}`, padding 3px 8px, font-semibold 8pt

**EmptyState** (`src/components/shared/EmptyState.tsx`)
- Props: `message: string`, `icon?: React.ReactNode`
- Centered vertically in parent, color: text-sub, italic

**SectionEyebrow** (`src/components/shared/SectionEyebrow.tsx`)
- Props: `label: string`
- Render: `<div>` with left border 4px solid accent + label text: font-semibold 9pt, padding 0 12px

---

## 4. Page Routing Map

| Route | File | Purpose |
|-------|------|---------|
| `/` | `app/page.tsx` | Redirect to `/accounts` |
| `/accounts` | `app/accounts/page.tsx` | Profile management (bulk import, token check, table) |
| `/auto-comment` | `app/auto-comment/page.tsx` | Task config form + SSE log console + stats bar |
| `/proxy` | `app/proxy/page.tsx` | KiotProxy config + proxy grid + start/stop controls |
| `/settings` | `app/settings/page.tsx` | API keys, delay defaults, behavior settings |

---

## 5. SSE Client Hook

**File:** `src/lib/sse-client.ts`

```typescript
export type SSELogType = 'info' | 'success' | 'error' | 'warning';

export interface LogEvent {
  index: number;
  uid: string;
  link: string;
  action: string;
  proxy: string;
  status: string;
  error: string;
  timestamp: number;
}

export interface StatsEvent {
  total: number;
  processed: number;
  success: number;
  failed: number;
  waitingProxy: number;
}

export function useSSE(url: string, options?: { reconnect?: boolean; reconnectInterval?: number }) {
  // Returns: { data, connected, error, close }
  // Internally: EventSource, auto-reconnect on close (if enabled)
  // Parses SSE `event:` field to determine type (log, stats, proxy_status)
  // Parses `data:` field as JSON
  // Calls onMessage callback per event type
}
```

**Pattern:**
1. On mount: `new EventSource(url)`
2. `source.onmessage` → parse JSON, call typed callback
3. `source.onerror` → set `error` state, schedule reconnect if enabled
4. `source.onopen` → clear error, set `connected = true`
5. On unmount: `source.close()`, clear reconnect timeout
6. Reconnect: exponential backoff capped at 5000ms

**Log color mapping (SSE → UI):**

| SSE status string | LogType | Badge color | Row bg tint |
|---|---|---|---|
| "Thành công" | success | success | transparent |
| "Thất bại" | error | danger | danger-soft/20 |
| "Đang chạy" | info | info | info-soft/20 |
| "Đang chờ proxy" | warning | warning | warning-soft/20 |
| "Đã dừng" | info | info | transparent |
| "Checkpoint ..." | error | danger | danger-soft/20 |
| "Token out ..." | error | danger | danger-soft/20 |

---

## 6. Mock API Layer

**File:** `src/lib/api-client.ts`

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export interface ApiResponse<T> {
  data: T;
  ok: boolean;
  status: number;
}

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`API error ${status}`);
  }
}

export async function apiFetch<T>(
  path: string,
  options?: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
  }
): Promise<ApiResponse<T>>
```

**Endpoints mapped:**

| FE Call | BE Endpoint | Method |
|---------|------------|--------|
| `importProfiles(text)` | `/api/profiles/import` | POST |
| `loadProfiles()` | `/api/profiles` | GET |
| `checkTokens(uids)` | `/api/profiles/check-tokens` | POST |
| `deleteProfiles(uids)` | `/api/profiles` | DELETE |
| `startTask(config)` | `/api/tasks/start` | POST |
| `stopTask()` | `/api/tasks/stop` | POST |
| `loadSettings()` | `/api/settings` | GET |
| `saveSettings(patch)` | `/api/settings` | PUT |
| `proxyStart()` | `/api/proxy/start` | POST |
| `proxyStop()` | `/api/proxy/stop` | POST |
| `proxyStatus()` | `/api/proxy/status` | GET |
| saveProxyConfig(data) | `/api/proxy/config` | PUT |
| `healthCheck()` | `/api/health` | GET |

**Error normalization:**
- HTTP 401 → "Phiên đăng nhập hết hạn, vui lòng tải lại trang"
- HTTP 422 → parse `detail` field, return first message
- HTTP 500 → "Lỗi máy chủ nội bộ"
- Network error → "Không thể kết nối đến máy chủ"

**Token masking (ported from C# SecretMasker):**
- Input: `token: string`, output: first 4 chars + `****` + last 4 chars
- If length < 9: show first 2 + `****` + last 2
- If length < 5: all masked as `****`

---

## 7. TypeScript Types

**File:** `src/types/index.ts`

```typescript
export interface ProfileRow {
  uid: string;
  token: string;
  tokenStatus: 'live' | 'die' | 'checkpoint' | 'unknown';
  taskCount: number;
  lastError: string | null;
}

export interface TaskStats {
  total: number;
  processed: number;
  success: number;
  failed: number;
  waitingProxy: number;
}

export interface LogEntry {
  index: number;
  uid: string;
  link: string;
  action: string;
  proxy: string;
  status: string;
  error: string;
  timestamp: number;
}

export interface ProxyKeyState {
  apiKey: string;
  display: string;
  remainingUses: number;
  status: 'ready' | 'waiting' | 'error' | 'starting';
  lastError: string | null;
  ipExpiresAt: string | null;
}

export interface AppSettings {
  kiotAuthToken: string;
  proxyApiKeys: string;
  getNewProxyUrl: string;
  getCurrentProxyUrl: string;
  usesPerProxy: number;
  checkInterval: number;
  interactionThreads: number;
  postsPerUid: number;
  delayMin: number;
  delayMax: number;
  delayEveryRounds: number;
}
```

---

## 8. Data Flow Diagrams

### 8.1 Accounts → Backend

```
[ProfileTable]
    │  on mount
    ▼
[apiFetch GET /api/profiles]
    │
    ▼
[set profiles state]
    │
    ▼
[render rows ← maskToken(token)]
```

### 8.2 Auto Comment Task Start

```
[TaskConfigForm] --onStart(config)--> [set running=true, POST /api/tasks/start]
    │
    ▼
[useSSE hook subscribes to /api/logs/stream]
    │
    ▼
[on log event] → append to logs[], update stats[]
[on stats event] → update stats state
[on close/disconnect] → set running=false, toast notification
```

### 8.3 SSE Reconnect

```
[EventSource] --onclose--> [if reconnect enabled]
    │                              │
    ▼                              ▼
[set connected=false]      [setTimeout(reconnectDelay)]
                                  │
                                  ▼
                          [new EventSource(url)]
                                  │
                                  ▼
                          [onopen → connected=true]
```

---

## 9. Known Constraints & Decisions

| # | Decision | Reason |
|---|----------|--------|
| 1 | Next.js 16.2 (current) not 15 | Use installed version |
| 2 | Base UI (`@base-ui/react`) — Button already migrating | Keep existing Button component, extend variants |
| 3 | `shadcn` v4 CLI available | Add components as needed |
| 4 | No dark mode | Per spec — light only for v1 |
| 5 | Min-width 1180px | Enforced via DashboardShell container |
| 6 | Font: Inter (matching Segoe UI metrics) | Already configured in layout.tsx |
| 7 | Token masking: 4***4 pattern | Current FE uses Inter via next/font/google; keep |
| 8 | sonner already in shadcn/tailwind.css | Use `<Toaster />` in layout |
| 9 | TanStack Table (`@tanstack/react-table`) already installed | Use for ProfileTable and LogConsole (replaces shadcn Table for complex grids) |
| 10 | SSE uses native EventSource | No extra dependency; native browser API |
| 11 | shadcn/ui Tabs → FlatTabControl equivalent | Use existing shadcn Tabs component for section switching |
| 12 | No pagination in v1 — client-side full render | Grid data volumes are manageable (< 10K profiles) |

---

*Document generated: 2026-07-06*
