# 01 — Codebase Scout: FlowMeta → FastAPI + Next.js Migration Master Plan

> **Mục đích:** Master execution plan. Đọc xong developer code ngay, không cần hỏi lại.
> **Ngày khảo sát:** 2026-07-06
> **Scope:** Core features (Profiles + AutoComment Edit/Delete/Create + Proxy KiotProxy only). Single user. License/Billing bỏ.

---

## SECTION 1: File Inventory

| File path | Mô tả ngắn | Trọng số | Lý do |
|---|---|---|---|
| `Program.cs` | Entry point: network guard → license gate → Form1 | **High** | Xác định startup order — runtime bootstrapping |
| `Models.cs` | Tất cả models: `ProfileAccount`, `ProxyKeyState`, `ProxyLease`, `DirectLease`, `TaskLogEntry`, `DelaySettings`, `AppSettings`, `SavedProfileState`, `TokenIssueInfo`, `SecretMasker` | **High** | Mọi service đều phụ thuộc — port 1:1 sang Pydantic |
| `CommentService.cs` | `ICommentService` + `FacebookGraphCommentService`: tất cả Graph API calls (Edit/Delete/Create), regex (`ExtractCommentId`/`ExtractPostId`), `BuildGraphErrorResult`, `DetectTokenIssue` | **High** | Core business logic — cần port sang backend service |
| `CommentTaskManager.cs` | Orchestrator: `StartAsync → RunGroupedByUidAsync → ResolveTasksAsync → ProcessSingleTaskAsync`. Events: `LogAdded`, `StatsChanged`, `ProfileStatusChanged` | **High** | Engine executor — port sang async runner + SSE events |
| `ProfileManager.cs` | Profile CRUD: parse `uid\|token`, dedup on merge, `NextProfile()` round-robin, export/import | **High** | State management — list/dict → PostgreSQL + Redis cache |
| `ProxyManager.cs` | Proxy state machine: `TryAcquireNow`, `AcquireAsync`, `CompleteLease`, background `MonitorAsync`, `StateChanged` event | **High** | Proxy orchestration — port sang asyncio + Redis |
| `KiotProxyClient.cs` | HTTP client cho KiotProxy API: `GetNewProxyAsync`, `GetCurrentProxyAsync`, JSON multi-format parsing | **High** | External API client — port sang `httpx` |
| `GraphCommentAuthorResolver.cs` | Resolve UID từ comment link qua `GET /v19.0/{commentId}?fields=id,from` | **High** | Auxiliary service — port sang backend endpoint or service |
| `Form1.cs` | WinForms form: constructor wires managers, event handlers, `StartTasksAsync` (line 1351), all UI orchestration | **Medium** | Split: validation logic → API endpoint, UI state → Next.js |
| `SecureSettingsStore.cs` | DPAPI encrypt/decrypt `AppSettings` → `%LOCALAPPDATA%\ToolEditDeleteCmt\settings.dpapi` | **Medium** | Replace bằng PostgreSQL singleton row |
| `NetworkGuard.cs` | Internet check: GET `gstatic.com/generate_204` + `msftconnecttest.com` | **Low** | Optional `/api/health` endpoint |
| `GitHubUpdateChecker.cs` | GitHub Releases API client for auto-update | **Low** | Optional — static page hoặc skip |
| `ToolEditDeleteCmt.csproj` | Project file: `net9.0-windows`, `System.Security.Cryptography.ProtectedData` dep | **High** | Dependency reference |
| `LicenseManager.cs` | RSA license key — DPAPI store | **NONE** | **Bỏ hoàn toàn** theo scope |
| `LicenseDialog.cs` | License activation dialog | **NONE** | **Bỏ** |
| `LicenseGuard.cs` | Runtime license validation timer | **NONE** | **Bỏ** |
| `FlowMetaLicenseAdmin/` | Admin key generation tool | **NONE** | **Bỏ** |
| `Form1.Designer.cs` | Auto-generated WinForms control declarations | **NONE** | **Bỏ** — không serialize sang web |
| `RoundedButton.cs` | Custom WinForms button renderer | **NONE** | **Bỏ** — Tailwind + shadcn/ui Button |
| `FlatTabControl.cs` | Custom WinForms tab control | **NONE** | **Bỏ** — shadcn/ui Tabs |
| `CheckBoxHeaderCell.cs` | DataGridView header checkbox | **NONE** | **Bỏ** — TanStack Table |
| `ProfileImportDialog.cs` | Profile import dialog | **NONE** | **Bỏ** — React modal |
| `UpdateDialog.cs` / `UpdateInstaller.cs` | Desktop auto-update UI + installer | **NONE** | **Bỏ** |
| `frontend/` | Next.js 16 scaffold (shadcn/ui, Tailwind, TanStack Table, Framer Motion) | **High** | Sẵn scaffolding — tận dụng trực tiếp |
| `fb_automator_design_spec.md` | SaaS UI spec (Sidebar + pages) | **High** | Design reference cho Next.js |
| `FRONTEND_DESIGN.md` | "Frost" theme: palette, typography, component specs | **High** | Design system — map sang Tailwind config |
| `frontend/AGENTS.md` | Next.js breaking changes warning | **High** | Next.js 16 rules |

---

## SECTION 2: Startup Flow

```csharp
// C# Program.Main() — exact flow (Program.cs lines 9-58)
static void Main()
{
    ApplicationConfiguration.Initialize();         // A1: High DPI, fonts
    Application.SetUnhandledExceptionMode(...);    // A2: Exception handlers

    // ─── A3: Network Guard ───
    updateChecker = new GitHubUpdateChecker();
    result = updateChecker.GetReleaseHistoryAsync().GetAwaiter().GetResult();
    if (!result.IsSuccess)                        // HTTP fail → abort
        MessageBox → return false;
    if (result.LatestUpdate is not null)           // Update available → notify
        MessageBox → continue;

    // ─── A4: License Gate ───
    licenseManager = new LicenseManager();
    if (!LicenseDialog.EnsureActivated(licenseManager))   // RSA + DPAPI
        return false;                                     // abort

    // ─── A5: License Runtime Guard ───
    licenseGuard = LicenseGuard.ValidateRuntime(licenseManager);
    if (!licenseGuard.IsAllowed)                        // Timer check expiry
        MessageBox → return false;                      // abort

    // ─── A6: Main Form ───
    Application.Run(new Form1(licenseManager));
}
```

```
ASCII Flow Diagram:

  Program.Main()
  │
  ├─ [A1] ApplicationConfiguration.Initialize()
  │         High DPI aware + default font setup
  │
  ├─ [A2] SetUnhandledExceptionMode(CatchException)
  │         ThreadException + AppDomain.UnhandledException handlers
  │
  ├─ [A3] CheckStartupNetworkAndUpdates(updateChecker)
  │         │
  │         ├─ GET https://api.github.com/repos/.../releases
  │         │   Timeout: implicit (GetAwaiter.GetResult blocks)
  │         │
  │         ├─ If !IsSuccess → MessageBox "Không kiểm tra được mạng"
  │         │   → return FALSE → App exits
  │         │
  │         ├─ If latestUpdate != null → MessageBox notify new version
  │         │   → return TRUE → continue
  │         │
  │         └─ return TRUE
  │
  ├─ [A4] LicenseManager + LicenseDialog.EnsureActivated()
  │         │
  │         ├─ Load %LOCALAPPDATA%\FlowMeta\license.dpapi (DPAPI.CurrentUser)
  │         ├─ RSA verify signature with embedded public key
  │         ├─ Check MachineGUID binding
  │         ├─ If expired or invalid → activation dialog
  │         │
  │         ├─ return FALSE → App exits
  │         └─ return TRUE → continue
  │
  ├─ [A5] LicenseGuard.ValidateRuntime(licenseManager)
  │         │
  │         ├─ 1-minute Timer checks expiry every interval
  │         ├─ If !IsAllowed → MessageBox → return FALSE → App exits
  │         └─ (SCOPE DROP: skip entirely, no license in web)
  │
  └─ [A6] Application.Run(new Form1(licenseManager))
              │
              ├─ Form1 Constructor:
              │   ├─ _settingsStore.Load() → DPAPI decrypt → AppSettings
              │   ├─ _profileManager = new ProfileManager()
              │   ├─ _proxyManager = new ProxyManager()
              │   ├─ _taskManager = new CommentTaskManager(              ← DI point
              │   │       _profileManager,
              │   │       _proxyManager,
              │   │       new FacebookGraphCommentService(),
              │   │       new GraphCommentAuthorResolver())
              │   ├─ InitializeComponent() → build all 3 tabs
              │   ├─ WireEvents() → subscribe LogAdded / StatsChanged / StateChanged
              │   └─ LoadSettingsIntoUi() → populate form fields
              │
              └─ (SCOPE DROP: replace Form1 with Next.js pages + API)
```

**Mapping sang FastAPI + Next.js:**

```
FastAPI startup (main.py):
  lifespan startup
    ├─ Load settings from PostgreSQL (user_settings row id=1)
    ├─ Initialize ProfileService, ProxyService, FacebookGraphService
    ├─ Initialize TaskRunner
    ├─ Start proxy monitor loop (if configured)
    └─ app.state.services = { profile_svc, proxy_svc, graph_svc, task_runner }

Next.js /dashboard mount:
  └─ useEffect → GET /api/settings → populate form fields + SSE subscribe
```

```python
# backend/main.py — FastAPI startup equivalent
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await create_db_pool()
    app.state.redis = await create_redis_pool()
    app.state.profile_svc = ProfileService(app.state.db)
    app.state.proxy_svc = ProxyService(app.state.db, app.state.redis)
    app.state.graph_svc = FacebookGraphService()
    app.state.graph_resolver = GraphAuthorResolver(app.state.graph_svc)
    app.state.task_runner = TaskRunner(
        app.state.profile_svc,
        app.state.proxy_svc,
        app.state.graph_svc,
    )
    yield
    await cleanup(app.state.db, app.state.redis)

app = FastAPI(title="FlowMeta API", lifespan=lifespan)
```

---

## SECTION 3: Task Execution Flow

```csharp
// === C# ENTRY: Form1.StartTasksAsync (Form1.cs line 1351) ===
// 1. Validate: profiles not empty, action matches inputs
// 2. IF action is NewComment: BuildNewCommentTasks(uids, posts, postsPerUid)
//    ELSE: Read links from textarea, pair with optional UIDs (1:1 or 1:all)
// 3. Clear log grid, reset sort, set buttons
// 4. Call _taskManager.StartAsync(tasks, action, threads, delay, newText, imagePath)
// 5. On cancel/exception: stop button, refresh grid, popup if not user-stopped
```

```
ASCII Task Execution Flow:

User Input (Next.js form)
│  action: Edit | Delete | NewComment
│  uids: string[] (optional)
│  links: string[] (Edit/Delete) OR posts: string[] (NewComment)
│  newText: string (Edit/NewComment)
│  imageFolder: string | null
│  threads: int (maxThreads)
│  delayMin/Max/Every: DelaySettings
│
├─ [1] BuildTasks (Next.js side)
│     └─ IF NewComment: pair each UID with each post (postsPerUid limit)
│        ELSE: pair UID[i] with link[i] (or same UID for all if single)
│        Output: List<CommentTaskInput> { manualUid?, commentLink }
│
├─ [2] POST /api/tasks/start
│     Body: { profiles: [{uid,token}], action, tasks[], newText, imagePaths[], threads, delay }
│     → FastAPI validates, loads images, starts TaskRunner in background
│     → Returns: { task_id: "uuid" }
│
├─ [3] TaskRunner.start() — equivalent to C# CommentTaskManager.StartAsync()
│     │
│     ├─ Stop previous run (cancel + clear blockedProfiles)
│     ├─ Stats = { Total: tasks.Count }
│     ├─ LoadImages(imagePaths) → List[str] of image file paths
│     ├─ LoadTextVariants(newText) → List[str] (split by \n\n)
│     └─ RunGroupedByUidAsync(tasks, action, threads, delay, variants, images)
│
│     ├─ [3a] ResolveTasksAsync(tasks, action)       ← Per task, parallel-ish
│     │       For each CommentTaskInput:
│     │         IF manualUid is empty:
│     │           └─ Call GraphCommentAuthorResolver
│     │              GET /v19.0/{commentId}?fields=id,from&access_token
│     │              → Extract from.id → uid
│     │              FAIL → log error, skip, failed++
│     │         IF manualUid present → use raw uid
│     │       Output: List<ResolvedCommentTask(uid, commentLink)>
│     │
│     ├─ [3b] GroupBy Uid
│     │       Output: List<UidTaskGroup{uid, tasks[]}>
│     │
│     ├─ [3c] BuildUidRoundBatches(groups, batchSize=maxThreads)
│     │       Round-robin: pop 1 task per group, rotate
│     │       Output: List<List<ResolvedCommentTask>> (each = one round)
│     │
│     └─ [3d] FOR each batch (round):
│           ├─ Filter blockedProfiles → skip
│           ├─ PreAddLogs(activeBatch, status="Cho chay")
│           ├─ await asyncio.gather(*[
│           │      ProcessSingleTaskAsync(t, action, variants, images)
│           │      for t in activeBatch
│           │  ])                         ← concurrent within batch
│           ├─ roundsCompleted++
│           └─ IF ShouldDelay(delay): await asyncio.sleep(random(min, max))
│
├─ [4] ProcessSingleTaskAsync(task) — Per task (parallel by batch)
│     │
│     ├─ [4a] FindByUid(task.uid) → ProfileAccount
│     │       FAIL → log "UID comment không có trong tab Hồ sơ", return
│     │
│     ├─ [4b] IF uid in blockedProfiles
│     │       → log "Profile đã dừng do X", return (skipped)
│     │
│     ├─ [4c] Acquire Proxy
│     │       IF proxy_manager.is_started:
│     │         lease = proxy_svc.try_acquire_now()  ← sync try
│     │         IF null:
│     │           stats.waiting_proxy++
│     │           lease = await proxy_svc.acquire_async(ct)  ← poll 1s
│     │           stats.waiting_proxy--
│     │       ELSE:
│     │         lease = proxy_svc.try_acquire_now()  ← may return None = Direct
│     │
│     ├─ [4d] Pick random text from variants + random image from list
│     │
│     ├─ [4e] Build CommentRequest and execute:
│     │       result = await graph_svc.execute(request)
│     │       └─ Route: Edit/EditImage/Delete/NewComment
│     │          → POST/DELETE /v19.0/{id} or /{postId}/comments
│     │          → Handle form-encoded or multipart form-data
│     │
│     ├─ [4f] Post-execution:
│     │       IF lease acquired:
│     │         IF success → lease.mark_used()  → RemainingUses--
│     │         ELSE     → lease.dispose()     → only release reservation
│     │       profile.task_count++
│     │       profile.last_error = result.Success ? "" : result.Message
│     │       IF result.TokenIssue → BlockProfile(uid, issue)
│     │       └─ Add to blockedProfiles dict → future rounds auto-skip
│     │
│     └─ [4g] Emit events → SSE queue:
│           - LogAdded: { key, index, uid, link, action, proxy, status, error }
│           - StatsChanged: { total, processed, success, failed, waitingProxy }
│           - ProfileStatusChanged: (uid, tokenStatus, lastError)
│
└─ [5] Done → runner clears → SSE stream ends → FE popup "Hoàn thành"
```

### Error Handling tại mỗi bước

| Bước | Error condition | Xử lý |
|---|---|---|
| ResolveTasksAsync | Graph API fail / no UID returned | Log error row, skip task, `Increment(failed=1, processed=1)` |
| ResolveTasksAsync | No checker profile + no manualUid | Log "Chưa có token để kiểm tra UID" + skip |
| AcquireAsync | Proxy getting new IP (not started) | `Increment(waiting_proxy++)`, poll 1s, retry |
| ProcessSingleTaskAsync | `OperationCanceledException` | `lease.Dispose()`, log "Đã nhận lệnh dừng.", `Increment(processed=1)` |
| ProcessSingleTaskAsync | Other exception | `lease.MarkUsed()`, `profile.last_error = ex.Message`, log fail |
| ExecuteAsync | Graph token error (code 190/282) | Return `TokenIssueInfo`, `BlockProfile` → skip rest of run |
| ExecuteAsync | Timeout (45s HttpClient) | Treated as IOException — cancel-style handling |
| ExecuteAsync | HTTP 200 permission denied | Log error, continue (no block) |
| BuildUidRoundBatches | Empty batch | `continue` — no-op |
| StartAsync | `OperationCanceledException` outer | ConcurrentDictionary clear, `_cts = null` |

```csharp
// C# error handling — exact code path (CommentTaskManager.cs lines 313-335)
try { ... lease?.MarkUsed(); }
catch (OperationCanceledException) {
    if (waitingProxyAdded) Increment(waitingProxy: -1);
    lease?.Dispose();   // NOT consumed on cancel
    AddLog(..., "Dung", "Đã nhận lệnh dừng.", ...);
}
catch (Exception ex) {
    if (waitingProxyAdded) Increment(waitingProxy: -1);
    lease?.MarkUsed();  // Consumed even on failure
    profile.LastError = ex.Message;
    AddLog(..., "That bai", ex.Message, ...);
}
```

---

## SECTION 4: Proxy Lease Lifecycle

```csharp
// ─── Models.cs — ProxyLease (line 65-101) ───
public sealed class ProxyLease : IDisposable
{
    private readonly ProxyManager _manager;
    private bool _completed;

    public ProxyLease(ProxyManager manager, ProxyKeyState state, ProxyEndpoint endpoint)
    {
        _manager = manager;
        State = state;
        Endpoint = endpoint;
    }

    public ProxyKeyState State { get; }
    public ProxyEndpoint Endpoint { get; }

    public void MarkUsed()
    {
        if (_completed) return;
        _completed = true;
        _manager.CompleteLease(State, consumed: true);
        // → current.RemainingUses = max(0, RemainingUses - 1)
        // → IF RemainingUses <= 0 → trigger GetNewProxyForKeyAsync
    }

    public void Dispose()
    {
        if (_completed) return;
        _completed = true;
        _manager.CompleteLease(State, consumed: false);
        // → current.ReservedUses = max(0, ReservedUses - 1)
        // → RemainingUses NOT decremented (proxy slot preserved)
    }
}

// CompleteLease (ProxyManager.cs line 172):
//   consumed=true  → RemainingUses--, nếu == 0 → auto-get-new
//   consumed=false → ReservedUses-- only (release reservation without consumption)
```

```csharp
// ─── Models.cs — DirectLease (line 103-115) — proxy OFF fallback ───
public sealed class DirectLease : IDisposable
{
    public ProxyEndpoint? Endpoint => null;   // null → no HTTP proxy
    public string Display => "Direct";        // displayed in log

    public void MarkUsed() { }    // no-op
    public void Dispose() { }     // no-op
}
// Used when ProxyManager.IsStarted == false.
// In ProcessSingleTaskAsync: proxyDisplay = lease?.Endpoint?.Display ?? "Direct"
```

```csharp
// ─── ProxyManager.TryAcquireNow (line 141-170) ───
public ProxyLease? TryAcquireNow()
{
    lock (_sync)
    {
        for (int offset = 0; offset < _states.Count; offset++)
        {
            int index = (_nextProxyIndex + offset) % _states.Count;
            var candidate = _states[index];

            // SKIP if ANY of:
            if (candidate.Endpoint is null) continue;                    // no IP yet
            if (candidate.RemainingUses <= candidate.ReservedUses) continue; // all slots taken
            if (IsIpExpired(candidate)) continue;                       // IpExpiresAt < now
            if (!IsReadyStatus(candidate.Status)) continue;             // status != "Ready"

            // ACQUIRE:
            candidate.ReservedUses++;
            _nextProxyIndex = (index + 1) % _states.Count; // round-robin advance
            StateChanged?.Invoke();
            return new ProxyLease(this, candidate, candidate.Endpoint);
        }
    }
    return null; // all busy or not ready
}

// ─── ProxyManager.AcquireAsync (line 118-132) ───
public async Task<ProxyLease> AcquireAsync(CancellationToken cancellationToken)
{
    while (!cancellationToken.IsCancellationRequested)
    {
        var lease = TryAcquireNow();
        if (lease is not null) return lease;
        await Task.Delay(1000, cancellationToken); // poll every 1s
    }
    throw new OperationCanceledException(cancellationToken);
}

// ─── ProxyManager.CompleteLease (line 172-203) ───
public void CompleteLease(ProxyKeyState state, bool consumed)
{
    lock (_sync)
    {
        var current = _states.FirstOrDefault(s => s.ApiKey == state.ApiKey);
        if (current is null) return;

        current.ReservedUses = Math.Max(0, current.ReservedUses - 1);
        if (consumed)
            current.RemainingUses = Math.Max(0, current.RemainingUses - 1);

        bool needsGetNew = current.RemainingUses <= 0 && _cts is not null;
        if (needsGetNew)
        {
            current.Status = "GettingNew";
            current.LastError = "";
            current.NextGetNewAt = null;
        }
    }
    StateChanged?.Invoke();
    if (needsGetNew) _ = GetNewProxyForKeyAsync(state.ApiKey, _cts.Token);
}
```

```csharp
// ─── KiotProxyClient.RequestProxyAsync (line 37-58) ───
// BOTH GetNewProxyAsync and GetCurrentProxyAsync delegate here
private async Task<ProxyEndpoint> RequestProxyAsync(
    string apiKey, string authToken, string urlTemplate, CancellationToken ct)
{
    var url = urlTemplate.Replace("{apiKey}", Uri.EscapeDataString(apiKey));
    using var request = new HttpRequestMessage(HttpMethod.Get, url);
    if (!string.IsNullOrWhiteSpace(authToken))
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", authToken);

    using var response = await _httpClient.SendAsync(request, ct);
    var body = await response.Content.ReadAsStringAsync(ct);
    if (!response.IsSuccessStatusCode)
        throw new InvalidOperationException(NormalizeErrorMessage(body, (int)response.StatusCode));
    return ParseProxyResponse(body);
}
```

```
Proxy State Machine (status transitions):

  Starting
    │   Monitor starts → CheckCurrentProxiesAsync
    ▼
  Ready ────► Use (RemainingUses > 0)
    │               │
    │               ▼ (RemainingUses hits 0 after MarkUsed)
    │           GettingNew ──► [success]───► Ready
    │               │                    (RemainingUses = UsesPerProxy)
    │               ▼ [timeout/exception]
    │           Waiting ──► [retry delay]───► GettingNew
    │               │                        (delay: random 1-6s or parsed "retry after")
    │               └──► [stale version]───► GettingNew (skip, already newer)
    ▼
  Error (only via IsIpExpired or status check failure)
    │
    └─► Monitor loop re-triggers GetNewProxy
```

---

## SECTION 5: Facebook Graph API v19.0 Endpoints

```csharp
// ─── Endpoint 1: Token Health Check ───
// Used by: Form1.CheckTokensAsync (token status check)
// NOT used by CommentTaskManager (GraphCommentAuthorResolver uses endpoint 2)
GET /me?fields=id
Query: access_token={token}
Timeout: 20s
Success: 200 → {"id": "1000123456"}  → TokenStatus = "Live" | "Chua kiem tra"
Error: 401 → {"error":{"code":190,"error_subcode":460,"message":"Error validating..."}}
         → TokenStatus = "Token out 190"

// ─── Endpoint 2: Resolve Author UID ───
// Used by: GraphCommentAuthorResolver.ReadFromGraphAsync
GET /v19.0/{commentId}?fields=id,from&access_token={token}
Timeout: 35s
Success: 200 → {"id":"comment_123","from":{"id":"1000123456"}} → return from.id
         → Validate: numeric-only, length 5-30
Error: HTTP error → throw InvalidOperationException("Graph read UID 403: ...")

// ─── Endpoint 3: Edit Comment (text only) ───
POST /{commentId}
Content-Type: application/x-www-form-urlencoded
Body: message={newText}&access_token={token}
Timeout: 45s
Success: 200 → "Đã chỉnh sửa comment."
Error → BuildGraphErrorResult → CommentResult with TokenIssueInfo

// ─── Endpoint 4: Edit Comment (with image) ───
POST /{commentId}
Content-Type: multipart/form-data
Fields:
  message = {newText} (StringContent)
  access_token = {token} (StringContent)
  source = {file stream} (StreamContent, Content-Type from extension)
Timeout: 45s
Image MIME mapping (C# GetImageContentType):
  .jpg/.jpeg → image/jpeg   .png → image/png   .gif → image/gif
  .webp → image/webp         .bmp → image/bmp   .svg → image/svg+xml
  .heic/.heif → image/heic   .avif → image/avif
  .ico → image/x-icon        .tiff → image/tiff

// ─── Endpoint 5: Delete Comment ───
DELETE /{commentId}?access_token={token}
Content-Type: (none)
Timeout: 45s
Success: 200 → "Đã xóa comment."
Error → same BuildGraphErrorResult

// ─── Endpoint 6: Create Comment ───
POST /{postId}/comments
Text variant:
  Content-Type: application/x-www-form-urlencoded
  Body: message={text}&access_token={token}
Image variant:
  Content-Type: multipart/form-data
  Fields: message, access_token, source (file)
Timeout: 45s
Success: 200 → {"id":"{postId}_{commentId}"}
  → BuildCommentLink(postId, commentId) → URL with ?comment_id={normalized}
Normalization (NormalizeCreatedCommentId):
  If commentId starts with "{postId}_" → strip prefix
  Else → take substring after last "_"
Error → same BuildGraphErrorResult

// ─── Error Response Format (all endpoints) ───
HTTP 400/401/403/404/500
{
  "error": {
    "message": "Error validating access token...",
    "code": 190,
    "error_subcode": 458,
    "error_user_msg": "Session has expired...",
    "fbtrace_id": "A..."
  }
}
```

```csharp
// ─── BuildGraphErrorResult logic (CommentService.cs line 317-344) ───
private static CommentResult BuildGraphErrorResult(HttpStatusCode statusCode, string body)
{
    using var document = JsonDocument.Parse(body);
    if (document.RootElement.TryGetProperty("error", out var error))
    {
        string message = GetString(error, "message");
        int code = GetInt(error, "code");
        int subcode = GetInt(error, "error_subcode");
        string userMessage = GetString(error, "error_user_msg");

        // Hint for common codes:
        string hint = code switch
        {
            200 => " Token không có quyền với comment này...",
            100 => " Sai ID/link bài viết, bài viết không tồn tại...",
            _ => ""
        };

        string fullMessage = $"Graph API {(int)statusCode}: {message} (code {code}, subcode {subcode}). {userMessage}{hint}".Trim();
        return new CommentResult(false, fullMessage,
            TokenIssue: DetectTokenIssue(message, userMessage, code, subcode));
    }
    return new CommentResult(false, $"Graph API {(int)statusCode}: {Trim(body)}");
}
```

---

## SECTION 6: Regex Patterns

### 6.1 ExtractCommentId

```csharp
// CommentService.cs line 223-256 — FULL SOURCE
public static string? ExtractCommentId(string link)
{
    var trimmed = link.Trim();
    if (string.IsNullOrWhiteSpace(trimmed)) return null;

    // Pass 1: If raw ID (no http prefix) → treat as-is
    if (!trimmed.StartsWith("http", StringComparison.OrdinalIgnoreCase))
        return trimmed;

    // Pass 2: Parse URL, check query params first
    if (Uri.TryCreate(trimmed, UriKind.Absolute, out var uri))
    {
        var query = ParseQuery(uri.Query);
        foreach (var key in new[] { "comment_id", "commentid", "comment", "id" })
        {
            if (query.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value))
                return value;
        }

        // Pass 3: Regex against URL path segments
        var pathMatch = Regex.Match(
            uri.AbsolutePath,
            @"(?:comment_id|comments?|reply_comment_id)[/=:-]([^/?#]+)",
            RegexOptions.IgnoreCase);
        if (pathMatch.Success)
            return Uri.UnescapeDataString(pathMatch.Groups[1].Value);
    }

    // Pass 4: Fallback regex on raw text
    var fallbackMatch = Regex.Match(trimmed, @"comment_id[=:]([^&#\s]+)", RegexOptions.IgnoreCase);
    return fallbackMatch.Success ? Uri.UnescapeDataString(fallbackMatch.Groups[1].Value) : null;
}
```

```
Input → Output examples for ExtractCommentId:
  "1234567890123456"                           → "1234567890123456"  (raw)
  "https://fb.com/photo?fbid=123&comment_id=456"  → "456"
  "https://fb.com/comment_id=789_abc"          → "789_abc"
  "https://fb.com/story.php?commentid=999"     → "999"
  "https://fb.com/posts/123/reply_comment_id/456" → "456"
  "abc def?comment_id=100"                     → "100" (fallback regex)
```

### 6.2 ExtractPostId

```csharp
// CommentService.cs line 258-294 — FULL SOURCE
public static string? ExtractPostId(string value)
{
    var trimmed = value.Trim();
    if (string.IsNullOrWhiteSpace(trimmed)) return null;

    if (!trimmed.StartsWith("http", StringComparison.OrdinalIgnoreCase))
        return trimmed;  // raw ID

    if (!Uri.TryCreate(trimmed, UriKind.Absolute, out var uri)) return null;

    // Pass 1: Query params
    var query = ParseQuery(uri.Query);
    foreach (var key in new[] { "story_fbid", "fbid", "id" })
    {
        if (query.TryGetValue(key, out var qv) && !string.IsNullOrWhiteSpace(qv))
            return qv;
    }

    // Pass 2: Path regex (posts/videos/photos/permalink)
    var path = uri.AbsolutePath.Trim('/');
    var postMatch = Regex.Match(
        path, @"(?:posts|videos|photos|permalink)/([^/?#]+)",
        RegexOptions.IgnoreCase);
    if (postMatch.Success)
        return Uri.UnescapeDataString(postMatch.Groups[1].Value);

    // Pass 3: pfbid special format
    var pfbidMatch = Regex.Match(path, @"(pfbid[^/?#]+)", RegexOptions.IgnoreCase);
    return pfbidMatch.Success ? Uri.UnescapeDataString(pfbidMatch.Groups[1].Value) : null;
}
```

```
Input → Output examples for ExtractPostId:
  "1234567890123456"                    → "1234567890123456" (raw)
  "https://fb.com/1000/posts/123_456"   → "123_456"
  "https://fb.com/1000/videos/789012"   → "789012"
  "https://fb.com/photo?fbid=555666"    → "555666"
  "https://fb.com/story.php?story_fbid=777" → "777"
  "https://fb.com/pfbidAbCdEfGh123456"  → "pfbidAbCdEfGh123456"
```

### 6.3 BuildCommentLink (response → URL)

```csharp
// CommentService.cs line 428-454
private static string BuildCommentLink(string postId, string? commentId)
{
    // Normalize: strip "{postId}_" prefix if present
    var normalized = NormalizeCreatedCommentId(postId, commentId);
    if (string.IsNullOrWhiteSpace(normalized))
        return $"https://www.facebook.com/{Uri.EscapeDataString(postId)}";
    return $"https://www.facebook.com/{postId}?comment_id={Uri.EscapeDataString(normalized)}";
}

private static string NormalizeCreatedCommentId(string postId, string? createdId)
{
    var id = createdId?.Trim() ?? "";
    var prefix = $"{postId.Trim()}_";
    if (id.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        return id[prefix.Length..];  // strip "postId_" prefix
    var lastUnderscore = id.LastIndexOf('_');
    return lastUnderscore >= 0 && lastUnderscore < id.Length - 1
        ? id[(lastUnderscore + 1)..]  // take text after last "_"
        : id;
}
```

### 6.4 Retry Delay Regex (used in KiotProxyClient AND ProxyManager)

```csharp
// KiotProxyClient.cs line 391 + ProxyManager.cs line 469 — IDENTICAL pattern
@"(?:Gửi lại sau|Gui lai sau|retry after|try again in)\s*(\d+)\s*(?:giây|giay|s|sec|secs|second|seconds)?"
```

```
Input → Output examples:
  "retry after 30"      → "30"
  "Gửi lại sau 5giây"   → "5"
  "try again in 10 secs"→ "10"
  "no retry"            → no match
```

### 6.5 IP Expiry Date Parsing (KiotProxyClient.cs)

```csharp
// KiotProxyClient.cs — multi-format expiry parser
// Scans ALL JSON properties recursively. For each property:
//   a. Normalize name: strip non-alpha, lowercase
//   b. Skip if name contains: "change", "next", "request", "retry", "wait", "cooldown"
//   c. Proceed if name contains: "expire", "ttl", "timelive", "lifetime", "timeleft", "remain", "duration"
//   d. Parse value:
//      - Number: if >10B → unix ms, if >1B → unix seconds, else seconds
//      - If name has "ms"/"millisecond" → milliseconds
//      - If name has "min" → minutes
//      - If name has "hour" → hours
//      - String: try DateTime.Parse, or duration text "1h 30m 15s"
// Duration text parser regex:
    @"(\d+)\s*(?:h|hour|hours|giờ|gio)"    → hours
    @"(\d+)\s*(?:m|min|minute|phút|phut)"  → minutes
    @"(\d+)\s*(?:s|sec|giây|giay)"         → seconds
```

### 6.6 Full URL format inventory

| Format | Example | Extractable ID | Method |
|---|---|---|---|
| `/posts/{postId}` | `.../posts/123_456789` | `123_456789` | ExtractPostId regex |
| `/videos/{videoId}` | `.../videos/789012` | `789012` | ExtractPostId regex |
| `/photos/{photoId}` | `.../photos/555666` | `555666` | ExtractPostId regex |
| `/permalink/{postId}` | `.../permalink/123` | `123` | ExtractPostId regex |
| `?fbid={photoId}` | `...?fbid=555666` | `555666` | ExtractPostId query param |
| `?story_fbid={id}` | `...?story_fbid=777` | `777` | ExtractPostId query param |
| `?comment_id={id}` | `...?comment_id=456` | `456` | ExtractCommentId query param |
| `?commentid={id}` | `...?commentid=999` | `999` | ExtractCommentId query param |
| `/comment_id/XYZ` in path | `.../comment_id/abc123` | `abc123` | ExtractCommentId path regex |
| `pfbid` URL | `.../pfbidAbCdEf/` | `pfbidAbCdEf` | ExtractPostId pfbid regex |

---

## SECTION 7: Error Paths & Token Detection

```csharp
// ─── DetectTokenIssue — exact source (CommentService.cs line 346-372) ───
private static TokenIssueInfo? DetectTokenIssue(
    string message, string userMessage, int code, int subcode)
{
    var issueCode = subcode != 0 ? subcode : code;
    var combined = $"{message} {userMessage}";

    // Checkpoint detection
    var checkpointSubcodes = new HashSet<int> { 282, 459, 490, 492, 493, 494, 959 };
    bool isCheckpoint =
        checkpointSubcodes.Contains(code) ||
        checkpointSubcodes.Contains(subcode) ||
        combined.Contains("checkpoint", StringComparison.OrdinalIgnoreCase) ||
        combined.Contains("security check", StringComparison.OrdinalIgnoreCase) ||
        combined.Contains("verify", StringComparison.OrdinalIgnoreCase);

    if (isCheckpoint)
        return new TokenIssueInfo("Checkpoint", code, subcode,
            issueCode != 0 ? $"Checkpoint {issueCode}" : "Checkpoint");

    // Token-out detection
    var tokenOutSubcodes = new HashSet<int> { 458, 460, 463, 467 };
    bool isTokenOut =
        code == 190 ||
        tokenOutSubcodes.Contains(subcode) ||
        (combined.Contains("access token", StringComparison.OrdinalIgnoreCase)
            && combined.Contains("expired", StringComparison.OrdinalIgnoreCase)) ||
        combined.Contains("invalid oauth", StringComparison.OrdinalIgnoreCase) ||
        combined.Contains("error validating access token", StringComparison.OrdinalIgnoreCase) ||
        combined.Contains("session has expired", StringComparison.OrdinalIgnoreCase);

    if (isTokenOut)
        return new TokenIssueInfo("Token out", code, subcode,
            issueCode != 0 ? $"Token out {issueCode}" : "Token out");

    return null; // no token issue classified
}
```

```
Token Issue Summary:

  ┌─────────────────┬───────────────────────┬──────────────────────────────────┬──────────────────────────────┐
  │ Issue Kind      │ Codes                 │ Trigger strings                  │ Effect                      │
  ├─────────────────┼───────────────────────┼──────────────────────────────────┼──────────────────────────────┤
  │ Checkpoint      │ 282, 459, 490, 492,   │ "checkpoint", "security check",  │ Profile blocked for entire   │
  │                 │ 493, 494, 959         │ "verify"                         │ run; status set, skipped     │
  │                 │                       │                                  │ in subsequent rounds         │
  ├─────────────────┼───────────────────────┼──────────────────────────────────┼──────────────────────────────┤
  │ Token out       │ 190, (sub: 458, 460,  │ "access token" + "expired"       │ Same as Checkpoint — blocked  │
  │                 │ 463, 467)             │ "invalid oauth"                  │                              │
  │                 │                       │ "error validating access token"  │                              │
  │                 │                       │ "session has expired"            │                              │
  ├─────────────────┼───────────────────────┼──────────────────────────────────┼──────────────────────────────┤
  │ Permission      │ 200                    │ "doesn't have permission"        │ Task fails; profile NOT      │
  │ denied          │                        │ "permission"                     │ blocked (retry possible)     │
  ├─────────────────┼───────────────────────┼──────────────────────────────────┼──────────────────────────────┤
  │ Invalid input   │ 100                    │ "Invalid parameter"              │ Task fails; profile NOT      │
  │ (wrong ID)      │                        │ "does not exist"                 │ blocked                      │
  └─────────────────┴───────────────────────┴──────────────────────────────────┴──────────────────────────────┘
```

```csharp
// ─── BlockProfile — exact source (CommentTaskManager.cs line 338-344) ───
private void BlockProfile(ProfileAccount profile, TokenIssueInfo issue, string message)
{
    _blockedProfiles.TryAdd(profile.Uid, issue);   // ConcurrentDictionary
    profile.TokenStatus = issue.Status;             // "Checkpoint 282" or "Token out 190"
    profile.LastError = message;
    ProfileStatusChanged?.Invoke(profile.Uid, profile.TokenStatus, profile.LastError);
}

// Effect on subsequent rounds:
//   if (_blockedProfiles.ContainsKey(task.Uid)) { skipped++; continue; }
//   → Profile completely excluded from all future rounds within same run
```

```csharp
// ─── Network Error Handling ───

// FacebookGraphCommentService — top-level timeout (45s)
// CommentTaskManager.ProcessSingleTaskAsync handles:
catch (OperationCanceledException)
    → lease.Dispose()    (release reservation only)
    → log "Đã nhận lệnh dừng."
    → status = "Dung"

catch (IOException ex) when (ex.Message.Contains("aborted", ...))
    → same as cancel (connection reset = treated as user stop)

// Proxy acquisition error path:
//   IF lease is null AND proxy manager running → log "Dang cho proxy"
//   → Increment(waitingProxy) → await AcquireAsync (poll 1s)
//   → On cancellation mid-wait: Increment(waitingProxy: -1), dispose, return
```

### Timeout constants summary

| Component | Timeout | Type |
|---|---|---|
| `FacebookGraphCommentService` | 45s | `HttpClient.Timeout` |
| `GraphCommentAuthorResolver` | 35s | `HttpClient.Timeout` |
| `KiotProxyClient` | 20s | `HttpClient.Timeout` |
| `ProxyManager.GetNewProxy` | 15s | `CancellationTokenSource.CancelAfter(15s)` |
| `ProxyManager.CheckCurrentProxy` | 15s | same |
| `NetworkGuard.HasInternetAsync` | 8s per URL | `HttpClient.Timeout` |
| `ProxyManager.AcquireAsync` retry | 1s poll | `Task.Delay(1000)` |
| Proxy monitor loop idle | 5s (configurable) | `Task.Delay(checkIntervalSeconds)` |

---

## SECTION 8: Tech Patterns (C# → Python/FastAPI Mapping)

### 8.1 No DI Container → Pure Functions / FastAPI Depends

```csharp
// C# — Form1 wires manually (no DI container)
// Form1.cs line 95-99:
_taskManager = new CommentTaskManager(
    _profileManager,
    _proxyManager,
    new FacebookGraphCommentService(),
    new GraphCommentAuthorResolver());
```

```python
# FastAPI — lifespan + Depends
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    app.state.db = await create_db_pool()
    app.state.redis = await create_redis_pool()
    app.state.profile_svc = ProfileService(app.state.db)
    app.state.proxy_svc = ProxyService(app.state.db, app.state.redis)
    app.state.graph_svc = FacebookGraphService()
    app.state.graph_resolver = GraphAuthorResolver(app.state.graph_svc)
    app.state.task_runner = TaskRunner(
        app.state.profile_svc, app.state.proxy_svc, app.state.graph_svc
    )
    yield
    await cleanup_all(app.state.db, app.state.redis)

app = FastAPI(title="FlowMeta", lifespan=lifespan)

# Dependency injection:
async def get_profile_svc(request: Request) -> ProfileService:
    return request.app.state.profile_svc

@app.post("/api/profiles/import")
async def import_profiles(
    req: ProfileImportRequest,
    svc: ProfileService = Depends(get_profile_svc)
):
    return await svc.import_from_text(req.text)
```

### 8.2 Event-driven → SSE (Server-Sent Events)

```csharp
// C# — WinForms events (CommentTaskManager.cs line 29)
public event Action<TaskLogEntry>? LogAdded;
public event Action<TaskStats>? StatsChanged;
public event Action<string, string, string>? ProfileStatusChanged;

// Subscription (Form1 line 901):
_taskManager.LogAdded += entry => { /* update DataGridView */ };
_taskManager.StatsChanged += stats => { /* update status bar */ };
```

```python
# FastAPI SSE — in-memory event bus per task
import asyncio
from collections import defaultdict
from sse_starlette.sse import EventSourceResponse

class SSEManager:
    def __init__(self):
        self._listeners: dict[str, list[asyncio.Queue]] = defaultdict(list)

    async def publish(self, channel: str, data: dict):
        for q in list(self._listeners[channel]):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                self._listeners[channel].remove(q)

    async def subscribe(self, channel: str) -> AsyncGenerator[dict, None]:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._listeners[channel].append(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._listeners[channel].remove(q)

sse = SSEManager()

@app.get("/api/tasks/{task_id}/stream")
async def task_stream(task_id: str, request: Request):
    async def gen(request: Request):
        async for event in sse.subscribe(f"task:{task_id}"):
            if await request.is_disconnected():
                break
            yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
    return EventSourceResponse(gen(request))

# Publishing from TaskRunner:
await sse.publish(f"task:{self.task_id}", {
    "type": "log", "data": {"key": ..., "uid": ..., "status": ...}
})
```

### 8.3 DPAPI + file storage → PostgreSQL

```csharp
// C# — SecureSettingsStore (encrypted file)
var json = JsonSerializer.Serialize(settings);
var bytes = Encoding.UTF8.GetBytes(json);
var protectedBytes = ProtectedData.Protect(bytes, null, DataProtectionScope.CurrentUser);
File.WriteAllBytes(_path, protectedBytes);  // %LOCALAPPDATA%\ToolEditDeleteCmt\settings.dpapi
```

```sql
-- PostgreSQL — single-user singleton settings table
CREATE TABLE user_settings (
    id INT PRIMARY KEY DEFAULT 1,           -- always one row
    profile_text TEXT,                       -- raw uid|token per-line textarea content
    interaction_uids_text TEXT,
    interaction_links_text TEXT,
    interaction_post_ids_text TEXT,
    interaction_action_index INT DEFAULT 0,
    interaction_threads INT DEFAULT 5,
    interaction_delay_min INT DEFAULT 0,
    interaction_delay_max INT DEFAULT 0,
    interaction_delay_every INT DEFAULT 1,
    interaction_posts_per_uid INT DEFAULT 1,
    interaction_edit_text TEXT,
    interaction_image_folder TEXT,
    kiot_auth_token_encrypted TEXT,          -- Fernet encrypted (cryptography.fernet)
    proxy_api_keys_text TEXT,                -- plain per-line text (not sensitive)
    get_new_url_template TEXT DEFAULT 'https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}',
    get_current_url_template TEXT DEFAULT 'https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}',
    uses_per_proxy INT DEFAULT 4,
    proxy_check_interval INT DEFAULT 5,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Load: SELECT * FROM user_settings WHERE id = 1
-- Decrypt kiot_auth_token:  from cryptography.fernet import Fernet; Fernet(key).decrypt(...)
```

### 8.4 CancellationToken → asyncio.CancellationToken

```csharp
// C# — per-manager CancellationTokenSource (Form1 wires all)
private CancellationTokenSource? _cts;
public void Start(...) { _cts = new CancellationTokenSource(); ... }
public void Stop() => _cts?.Cancel();
public async Task ProcessAsync(..., CancellationToken ct) { ... }
```

```python
# Python — asyncio.Event per service/runner
class TaskRunner:
    def __init__(self):
        self._stop_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None

    def start(self, ...) -> str:
        self.stop()                        # cancel previous
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(...))
        return self.task_id

    def stop(self):
        if self._stop_event:
            self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()

    async def _run(self, ...):
        try:
            self._stop_event = asyncio.Event()
            while not self._stop_event.is_set():
                ...  # process one item
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
```

### 8.5 Round-robin (Interlocked.Increment) → asyncio.Lock-protected index

```csharp
// C# — thread-safe round-robin (ProfileManager.cs line 151-153)
private int _nextProfile;
public ProfileAccount? NextProfile()
{
    if (_profiles.Count == 0) return null;
    int index = Interlocked.Increment(ref _nextProfile);
    return _profiles[(index - 1) % _profiles.Count];
}

// C# — round-robin index in proxy (lock protected)
_nextProxyIndex = (index + 1) % _states.Count;
```

```python
# Python — asyncio.Lock (cooperative, no true Interlocked needed)
import asyncio

class RoundRobin:
    def __init__(self, items: list):
        self._items = items
        self._idx = 0
        self._lock = asyncio.Lock()

    def next(self):
        if not self._items: return None
        item = self._items[self._idx % len(self._items)]
        self._idx += 1
        return item

    async def next_async(self):
        async with self._lock:
            return self.next()

# For log index (single event loop — no lock needed):
self._log_index += 1  # effectively atomic in asyncio
```

### 8.6 Background Task.Run → asyncio.create_task + global task store

```csharp
// C# — CommentTaskManager.StartAsync (line 54)
return Task.Run(async () => {
    try { await RunGroupedByUidAsync(...); }
    catch (OperationCanceledException) { }
    catch (IOException ex) when (ex.Message.Contains("aborted")) { }
    finally { _cts?.Dispose(); _cts = null; }
}, _cts.Token);
```

```python
# Python — global task registry (single-user = one runner at a time)
_active_tasks: dict[str, TaskRunner] = {}

@app.post("/api/tasks/start")
async def start_tasks(req: TaskStartRequest):
    # Cancel previous if any
    for tid, runner in list(_active_tasks.items()):
        runner.stop()
        await runner.wait_done()
        del _active_tasks[tid]

    task_id = str(uuid4())
    runner = TaskRunner(task_id, ...)
    runner.configure(req)
    _active_tasks[task_id] = runner

    # Fire-and-forget with SSE notification on completion
    asyncio.create_task(runner.run_and_cleanup(task_id))
    return {"task_id": task_id}

@app.post("/api/tasks/{task_id}/stop")
async def stop_task(task_id: str):
    runner = _active_tasks.get(task_id)
    if runner and not runner.is_done():
        runner.stop()
        return {"status": "stopping"}
    return {"status": "not_running"}
```

### 8.7 ConcurrentDictionary → Shared State (Redis for distributed, dict for single-worker)

```csharp
// C# — ConcurrentDictionary for blocked profiles
private readonly ConcurrentDictionary<string, TokenIssueInfo> _blockedProfiles
    = new(StringComparer.OrdinalIgnoreCase);
_blockedProfiles.TryAdd(profile.Uid, issue);  // thread-safe add
_blockedProfiles.ContainsKey(task.Uid);       // thread-safe check
```

```python
# Single-worker FastAPI (in-memory, safe):
class TaskRunner:
    def __init__(self):
        self._blocked: dict[str, TokenIssueInfo] = {}

    def block_profile(self, uid: str, issue: TokenIssueInfo):
        self._blocked[uid] = issue

    def is_blocked(self, uid: str) -> TokenIssueInfo | None:
        return self._blocked.get(uid)

# For multi-worker production, use Redis SET with TTL:
import aioredis
redis = aioredis.Redis()
BLOCKED_PREFIX = "flowmeta:blocked"

async def block_profile(uid: str, ttl_seconds: int = 86400):
    await redis.setex(f"{BLOCKED_PREFIX}:{uid}", ttl_seconds,
                      json.dumps({"kind": "Checkpoint", "code": 282}))

async def is_blocked(uid: str) -> bool:
    return await redis.exists(f"{BLOCKED_PREFIX}:{uid}") > 0
```

### 8.8 Mutex/lock for stats → asyncio.Lock

```csharp
// C# — CommentTaskManager stats increment (lock protected)
private readonly object _statsSync = new();
private void Increment(int success=0, int failed=0, int processed=0, int waitingProxy=0)
{
    lock (_statsSync)
    {
        Stats = Stats with
        {
            Success = Math.Max(0, Stats.Success + success),
            Failed = Math.Max(0, Stats.Failed + failed),
            ...
        };
    }
    StatsChanged?.Invoke(Stats);
}
```

```python
# Python — asyncio.Lock (cooperative)
class TaskRunner:
    def __init__(self):
        self._stats_lock = asyncio.Lock()
        self._stats = TaskStats()

    async def increment(self, **kwargs):
        async with self._stats_lock:
            self._stats = self._stats.copy(**kwargs)
        await sse.publish(f"task:{self.task_id}", {
            "type": "stats", "data": self._stats.dict()
        })
```

### 8.9 Image file loading → client upload → backend stream

```csharp
// C# — image paths are local filesystem paths from WinForms textbox
// CommentService.cs: File.OpenRead(imagePath) → StreamContent → multipart POST
// CommentTaskManager.LoadImages(imageInput):
//   - Input: multiline text, each line = file path or folder path
//   - Walks directory tree, filters by extension whitelist
public static IReadOnlyList<string> LoadImages(string? imageInput)
{
    // Input: textarea with one path per line
    // Extension whitelist: .jpg .jpeg .jpg .png .gif .webp .bmp .dib .tif .tiff .heic .heif .avif .ico .svg
    // If line is file: add directly
    // If line is directory: enumerate *.jpg etc recursively, catch errors gracefully
    // Return: distinct full paths
}
```

```python
# FastAPI — frontend uploads images as multipart, backend stores in temp dir
from fastapi import UploadFile, File
import tempfile, os

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
                     ".tif", ".tiff", ".heic", ".heif", ".avif", ".ico", ".svg"}

@app.post("/api/tasks/start")
async def start_tasks(req: TaskStartRequest, files: list[UploadFile] = File(default=[])):
    # Save uploads to temp dir, pass paths to task runner
    tmpdir = tempfile.mkdtemp()
    image_paths = []
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext in ALLOWED_IMAGE_EXT:
            path = Path(tmpdir) / f.filename
            await f.seek(0)
            path.write_bytes(await f.read())
            image_paths.append(str(path))
    # Pass image_paths to runner (same semantics as C#)
```

---

## SECTION 9: Self-contained Boundary

```
┌───────────────────────────────────────────────────────────────────────────┐
│  FASTAPI BACKEND (port these)                                             │
│                                                                           │
│  API Endpoints:                                                           │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ POST   /api/profiles/import                                         │  │
│  │ GET    /api/profiles                                                │  │
│  │ DELETE /api/profiles                                                │  │
│  │ POST   /api/profiles/check-tokens                                   │  │
│  │                                                                      │  │
│  │ POST   /api/tasks/start                                             │  │
│  │ POST   /api/tasks/{id}/stop                                         │  │
│  │ GET    /api/tasks/{id}/stream                                       │  │
│  │                                                                      │  │
│  │ POST   /api/proxy/start                                             │  │
│  │ POST   /api/proxy/stop                                              │  │
│  │ GET    /api/proxy/stream                                            │  │
│  │                                                                      │  │
│  │ GET    /api/settings                                                │  │
│  │ PUT    /api/settings                                                │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  Service layer (ported from C#):                                         │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────────┐        │
│  │ ProfileService │  │ ProxyService   │  │ FacebookGraphService  │        │
│  │ ← ProfileMgr   │  │ ← ProxyMgr     │  │ ← CommentService      │        │
│  │ NextProfile()  │  │ TryAcquire()   │  │ Edit/Delete/Create()  │        │
│  │ Import/Merge   │  │ MonitorAsync() │  │ ExtractCommentId()    │        │
│  │ FindByUid      │  │ CompleteLease()│  │ DetectTokenIssue()    │        │
│  └────────────────┘  └────────────────┘  └──────────────────────┘        │
│                                                                           │
│  Also port:                                                               │
│  ├── KiotProxyClient → kiotproxy_client.py  (HTTP calls to KiotProxy)    │
│  ├── GraphCommentAuthorResolver → graph_resolver.py                      │
│  └── Regex utilities → regex_utils.py (all patterns from Section 6)       │
│                                                                           │
│  Persistence:                                                             │
│  ├── PostgreSQL: profiles, proxy_keys, user_settings, task_runs, logs    │
│  └── Redis: proxy hot state, blocked profiles TTL, SSE pub/sub           │
└───────────────────────────────────────────────────────────────────────────┘
         │                                    ▲
         │ HTTP/SSE                           │ REST + SSE
         ▼                                    │
┌───────────────────────────────────────────────────────────────────────────┐
│  NEXT.JS FRONTEND (new UI)                                               │
│                                                                           │
│  Pages:  /profiles  /interaction  /proxy  /tasks                         │
│  Components: ProfileGrid, LogGrid, ProxyGrid (TanStack Table)            │
│              ActionTabs, StatsBar, SSE hooks                             │
│                                                                           │
│  Holds:                                                                   │
│  ├── All form inputs (React Hook Form)                                   │
│  ├── Tab navigation (shadcn/ui Tabs)                                     │
│  ├── Real-time log streaming (useLogStream hook → SSE consumer)          │
│  └── Stats bar updating (useStatsStream hook)                            │
└───────────────────────────────────────────────────────────────────────────┘
```

### 9.1 Exact C# lines → API boundary

```
ProcessSingleTaskAsync (CommentTaskManager.cs lines 240-336):
│
│  Lines 240-261:  LOOKUP + PRE-CHECK
│  These become:  implicit in POST /api/tasks/start validation
│  → Runner checks profile exists + not blocked before processing
│
│  Lines 263-283:  PROXY ACQUISITION
│  → Port as proxy_service.try_acquire() / acquire_async()
│    Called by runner internally; no API endpoint for this
│
│  Lines 285-297:  BUILD REQUEST
│  → Port as: Pick text variant + Pick image (pure functions)
│    Build CommentRequest DTO → call graph_service.execute()
│
│  Line 298-300:   GRAPH API CALL
│  → Port as: graph_service.execute(request) → CommentResult
│    THIS is the network I/O — the only thing that needs proxy/timeout
│
│  Line 300:       lease.MarkUsed()
│  → ROUTER: after success → proxy_svc.mark_used(lease.state_id)
│
│  Lines 302-311:  POST-EXECUTION
│  → profile_svc.update_stats(uid, result)
│  → If TokenIssue: proxy_svc... NO → profile_svc.block_profile(uid, issue)
│  → Emit SSE: runner.publish("log", {...})
│
│  Lines 313-335:  EXCEPTION HANDLING
│  → try/except around execute() in runner loop
│  → On cancel: sse.publish("log", {status:"Dung"}), then return
│  → On exception: profile_svc.update_error(uid, message), lease.mark_used()
```

### 9.2 Files NOT to port (explicit list)

| File | Action | Reason |
|---|---|---|
| `Form1.cs` UI construction methods | **Bỏ** | Replaced by Next.js + shadcn/ui |
| `Form1.Designer.cs` | **Bỏ** | Auto-generated, no web equivalent |
| `LicenseManager.cs` | **Bỏ** | Out of scope |
| `LicenseDialog.cs` | **Bỏ** | Out of scope |
| `LicenseGuard.cs` | **Bỏ** | Out of scope |
| `FlowMetaLicenseAdmin/*` | **Bỏ** | Out of scope |
| `SecureSettingsStore.cs` | **Thay thế** | PostgreSQL + Fernet encryption |
| `GitHubUpdateChecker.cs` | **Tùy chọn** | Desktop-specific self-update |
| `UpdateDialog.cs` / `UpdateInstaller.cs` | **Bỏ** | Desktop update mechanism |
| `NetworkGuard.cs` | **Tùy chọn** | Replace by `/api/health` endpoint |
| `RoundedButton.cs` | **Bỏ** | Tailwind + shadcn Button |
| `FlatTabControl.cs` | **Bỏ** | shadcn/ui Tabs |
| `CheckBoxHeaderCell.cs` | **Bỏ** | TanStack Table |
| `ProfileImportDialog.cs` | **Bỏ** | React textarea |
| `ToolEditDeleteCmt.csproj` | **Thay thế** | `requirements.txt` + `pyproject.toml` |

### 9.3 Backend migration stages

```
STAGE 1: Service Layer Port (có thể test ngay)
  ├── backend/app/models/          ← Models.cs → Pydantic schemas
  ├── backend/app/services/
  │   ├── facebook_graph.py        ← CommentService.cs
  │   ├── kiotproxy_client.py      ← KiotProxyClient.cs
  │   ├── graph_resolver.py        ← GraphCommentAuthorResolver.cs
  │   ├── regex_utils.py           ← Section 6 regex patterns
  │   └── __init__.py
  ├── backend/tests/               ← pytest (no test framework hiện tại, add mới)
  └── backend/main.py              ← FastAPI app + lifespan

STAGE 2: State Management Port
  ├── backend/app/services/profile_service.py ← ProfileManager
  ├── backend/app/services/proxy_service.py   ← ProxyManager
  ├── backend/app/infra/database.py           ← SQLAlchemy async
  ├── backend/app/infra/redis_client.py       ← aioredis
  ├── backend/app/infra/sse_manager.py        ← SSE event bus
  ├── backend/app/models/                    ← extend with SQLAlchemy ORM
  └── alembic/                               ← migrations

STAGE 3: Task Execution Engine
  ├── backend/app/services/task_runner.py     ← CommentTaskManager ( hardest)
  ├── backend/app/api/tasks.py                ← task start/stop/stream endpoints
  └── backend/app/api/proxy.py                ← proxy endpoints

STAGE 4: Frontend (Next.js — already scaffolded)
  ├── frontend/src/app/profiles/page.tsx
  ├── frontend/src/app/interaction/page.tsx
  ├── frontend/src/app/proxy/page.tsx
  ├── frontend/src/components/features/
  │   ├── profiles/          ← ProfileGrid, ProfileImport
  │   ├── interaction/       ← TaskConfigForm, LogGrid, StatsBar
  │   └── proxy/             ← ProxyConfigForm, ProxyGrid
  └── frontend/src/lib/api.ts  ← fetch + SSE client
```

### 9.4 Database schema (PostgreSQL)

```sql
-- Table: profiles
CREATE TABLE profiles (
    uid TEXT PRIMARY KEY,                    -- case-insensitive (COLLATE "C")
    token TEXT NOT NULL,                     -- plaintext in DB, encrypt at rest if needed
    token_status TEXT DEFAULT 'Chua kiem tra',
    task_count INT DEFAULT 0,
    last_error TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_profiles_status ON profiles(token_status);

-- Table: proxy_keys
CREATE TABLE proxy_keys (
    id SERIAL PRIMARY KEY,
    api_key TEXT NOT NULL,                   -- plaintext (not highly sensitive, like API key)
    current_proxy TEXT DEFAULT '',
    remaining_uses INT DEFAULT 0,
    reserved_uses INT DEFAULT 0,
    status TEXT DEFAULT '',
    last_error TEXT DEFAULT '',
    host TEXT DEFAULT '',
    http_port INT DEFAULT 0,
    proxy_username TEXT DEFAULT '',
    proxy_password TEXT DEFAULT '',          -- sensitive, consider encrypting
    display TEXT DEFAULT '',
    ip_expires_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ,
    last_get_ip_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Table: user_settings (singleton row)
-- (schema in Section 8.3)

-- Table: task_runs
CREATE TABLE task_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action TEXT NOT NULL,                    -- 'edit', 'delete', 'new_comment'
    total_tasks INT DEFAULT 0,
    status TEXT DEFAULT 'running',           -- 'running', 'completed', 'stopped'
    started_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    profiles_snapshot JSONB                  -- snapshot of profiles at run start
);

-- Table: task_logs
CREATE TABLE task_logs (
    id SERIAL PRIMARY KEY,
    run_id UUID REFERENCES task_runs(id),
    idx INT,
    uid TEXT,
    comment_link TEXT,
    action TEXT,
    proxy TEXT,
    status TEXT,
    error TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_task_logs_run ON task_logs(run_id, idx);
```

### 9.5 Backend project structure (final)

```
backend/
├── main.py                   # FastAPI app + lifespan + route registration
├── requirements.txt
├── pyproject.toml
├── .env.example              # DATABASE_URL, REDIS_URL, FERNET_KEY
│
├── app/
│   ├── __init__.py
│   ├── main.py               # re-export for uvicorn
│   │
│   ├── models/               # Pydantic schemas + SQLAlchemy ORM
│   │   ├── __init__.py
│   │   ├── common.py         # TokenIssueInfo, DelaySettings, TaskStats
│   │   ├── profile.py        # ProfileAccount, SavedProfileState, ParseResult
│   │   ├── proxy.py          # ProxyKeyState, ProxyEndpoint, ProxyLease, DirectLease
│   │   ├── task.py           # CommentTaskInput, ResolvedCommentTask, TaskLogEntry
│   │   └── settings.py       # AppSettings request/response DTOs
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── facebook_graph.py   # ← CommentService.cs
│   │   ├── kiotproxy_client.py # ← KiotProxyClient.cs
│   │   ├── graph_resolver.py   # ← GraphCommentAuthorResolver.cs
│   │   ├── profile_service.py  # ← ProfileManager.cs
│   │   ├── proxy_service.py    # ← ProxyManager.cs + KiotProxyClient
│   │   ├── task_runner.py      # ← CommentTaskManager.cs (hardest)
│   │   └── regex_utils.py      # ExtractCommentId, ExtractPostId, etc.
│   │
│   ├── infra/
│   │   ├── __init__.py
│   │   ├── database.py         # SQLAlchemy async engine, session
│   │   ├── redis_client.py     # aioredis pool
│   │   └── sse_manager.py      # Event pub/sub for SSE streaming
│   │
│   └── api/
│       ├── __init__.py
│       ├── profiles.py        # Profile CRUD endpoints
│       ├── tasks.py           # Task start/stop/stream
│       ├── proxy.py           # Proxy config/start/stop/status
│       ├── settings.py        # Settings load/save
│       └── graph.py           # Graph API helper endpoints (resolve-author)
│
└── migrations/
    └── 001_initial_schema.sql

frontend/
├── package.json              # Already has Next.js 16 + shadcn + TanStack
├── src/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx          # Dashboard shell (redirect or default view)
│   │   ├── profiles/page.tsx   # Profile management
│   │   ├── interaction/page.tsx  # AutoComment config + runner
│   │   ├── proxy/page.tsx    # Proxy management
│   │   └── history/page.tsx  # Task run history + logs
│   │
│   ├── components/
│   │   ├── layout/
│   │   │   ├── DashboardLayout.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   └── TopNav.tsx
│   │   └── features/
│   │       ├── profiles/
│   │       │   ├── ProfileGrid.tsx
│   │       │   ├── ProfileImport.tsx
│   │       │   └── ProfileToolbar.tsx
│   │       ├── interaction/
│   │       │   ├── TaskConfigForm.tsx     (React Hook Form)
│   │       │   ├── RunnerPanel.tsx        (stats bar + action buttons)
│   │       │   ├── LiveLogGrid.tsx        (TanStack Table + SSE row updates)
│   │       │   └── StatsBar.tsx           (dark bar, Frost theme)
│   │       └── proxy/
│   │           ├── ProxyConfigForm.tsx
│   │           ├── ProxyGrid.tsx
│   │           └── ProxyToolbar.tsx
│   │
│   └── lib/
│       ├── api.ts            # fetch() wrapper + SSE fetch
│       ├── types.ts          # TypeScript types (from Pydantic models)
│       └── utils.ts
│
└── tailwind.config.ts        # Frost theme colors from FRONTEND_DESIGN.md
```

---

## Appendix A: Frost Theme → Tailwind Config Mapping

```js
// From FRONTEND_DESIGN.md "Frost" palette → tailwind.config.ts
colors: {
  // Surfaces
  'app-back': 'hsl(215, 40%, 97%)',      // #F8FAFC slate-50
  'panel': 'hsl(0, 0%, 100%)',           // #FFFFFF
  'surface-row': 'hsl(210, 20%, 95%)',   // #F1F5F9 slate-100
  'surface-dark': 'hsl(215, 28%, 17%)',  // #1E293B slate-800

  // Brand
  'accent': 'hsl(221, 83%, 53%)',        // #2563EB blue-600
  'accent-hover': 'hsl(224, 76%, 48%)',  // #1D4ED8 blue-700
  'accent-soft': 'hsl(211, 97%, 90%)',   // #DBEAFE blue-100

  // Text
  'text-primary': 'hsl(222, 47%, 11%)',  // #0F172A slate-900
  'text-sub': 'hsl(215, 16%, 47%)',      // #64748B slate-500

  // Status
  'success': 'hsl(158, 64%, 36%)',       // #059669 emerald-600
  'success-soft': 'hsl(151, 81%, 93%)',  // #D1FAE5 emerald-100
  'warning': 'hsl(26, 84%, 50%)',        // #D97706 amber-600  ← only warm color
  'warning-soft': 'hsl(45, 93%, 94%)',   // #FEF3C7 amber-100
  'danger': 'hsl(0, 72%, 51%)',          // #DC2626 red-600
  'danger-soft': 'hsl(0, 94%, 95%)',     // #FEE2E2 red-100
  'info': 'hsl(187, 85%, 33%)',          // #0891B2 cyan-600
  'info-soft': 'hsl(186, 100%, 95%)',    // #CFFAFE cyan-100

  // Borders
  'border': 'hsl(215, 20%, 86%)',        // #E2E8F0 slate-200
}
```

## Appendix B: Key Constants Table

```yaml
# Defaults extracted from C# source
KiotProxy:
  base_url_new: "https://api.kiotproxy.com/api/v1/proxies/new?key={apiKey}"
  base_url_current: "https://api.kiotproxy.com/api/v1/proxies/current?key={apiKey}"
  timeout: 20 seconds
  acquire_timeout: 15 seconds
  uses_per_proxy: 4
  ip_lifetime: 30 minutes
  monitor_check_interval: 5 seconds
  acquire_retry_ms: 1000              # poll every 1s when no proxy

Facebook Graph API:
  version: "v19.0"
  base_url: "https://graph.facebook.com"
  timeout_edit_delete: 45 seconds
  timeout_resolve_uid: 35 seconds
  supported_image_extensions:
    - .jpg .jpeg .jfif .pjpeg .pjp  (image/jpeg)
    - .png                          (image/png)
    - .gif                          (image/gif)
    - .webp                         (image/webp)
    - .bmp .dib                     (image/bmp)
    - .tif .tiff                    (image/tiff)
    - .heic .heif                   (image/heic)  -- HISIC support
    - .avif                         (image/avif)
    - .ico                          (image/x-icon)
    - .svg                          (image/svg+xml)

UIs (desktop, for reference only):
  min_size: 1180 x 720
  default_size: 1280 x 820
```

## Appendix C: Next.js 16 Breaking Change Notes

From `frontend/AGENTS.md`:
> "This is NOT the Next.js you know. This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices."

Key: Next.js 16 has breaking changes from 15/14. Review next/dist/docs/ before coding frontend.

---

*End of document. Total C# source files reviewed: 20 classes across 14 .cs files. Target: FastAPI (Python) + Next.js 15 + PostgreSQL + Redis.*
