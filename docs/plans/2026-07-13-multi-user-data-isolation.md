# FlowMeta Multi-User Data Isolation Execution Plan

## 1. Mục tiêu

Chuyển FlowMeta từ chế độ migration tạm thời dùng chung default admin sang mô hình multi-user thực sự:

- User A chỉ nhìn thấy và thao tác dữ liệu thuộc User A.
- User B không thể đọc, sửa, xóa, chạy task hoặc nhận event của User A và ngược lại.
- `user_id` luôn được backend lấy từ access token đã xác thực, không tin `user_id` do frontend gửi lên.
- Mọi API truy cập tài nguyên theo ID phải kiểm tra ownership.
- Worker, scheduler, Redis queue, SSE và browser session phải giữ đúng tenant context xuyên suốt.
- Hành vi truy cập chéo user phải có test tự động và làm CI thất bại nếu tái xuất hiện.

## 2. Trạng thái hiện tại và rủi ro

### Đã có

- Bảng `users` và phần lớn bảng nghiệp vụ đã có `user_id`.
- Đăng nhập thường, đăng ký, reset password và OAuth Google/Facebook đã tạo local user/token.
- Facebook accounts/pages, scheduled posts, browser sessions và một số page/share API đã lọc theo user.
- Alembic đang ở revision `20260713_0002`.

### Chưa an toàn

- `backend/app/auth.py::current_user` đang luôn trả default admin, bỏ qua Bearer token.
- Một số task/log endpoint lấy dữ liệu chỉ theo `run_id`, chưa kiểm tra `user_id`.
- SSE đang phát event dùng chung, chưa tách channel/user.
- Proxy/settings có khả năng đang dùng singleton hoặc dữ liệu dùng chung toàn hệ thống.
- Worker nhận job ID nhưng cần audit để bảo đảm không làm mất `user_id`.
- Frontend từng có request dùng `fetch()` trực tiếp; cần audit lại để bảo đảm request protected đều gửi token.
- Token đang lưu trong `localStorage`; cần đánh giá chuyển sang HttpOnly cookie ở phase hardening riêng.

## 3. Nguyên tắc bắt buộc

1. Không nhận `user_id` từ body/query để quyết định ownership.
2. Endpoint collection luôn lọc `Model.user_id == current_user.id`.
3. Endpoint resource-by-ID phải query đồng thời `id` và `user_id`.
4. Với tài nguyên của user khác, ưu tiên trả `404` để không làm lộ sự tồn tại của record.
5. Child record phải được kiểm tra qua ownership trực tiếp hoặc ownership
6. Queue payload phải chứa `user_id`, nhưng worker vẫn phải đối chiếu `run.user_id` trong DB.
7. SSE event phải có `user_id`; subscription chỉ nhận event đúng user.
8. Không dùng global singleton chứa state của nhiều user nếu key không bao gồm `user_id`.
9. RBAC được triển khai trong plan này. Quyền truy cập chéo tenant chỉ dành cho permission được khai báo rõ như `tenant:read:any`; role `admin` không tự động được bỏ qua ownership nếu thiếu permission tương ứng.
10. Không được hoàn tất phase nếu chưa có test User A/User B tương ứng.

## 4. Kiến trúc đích

```text
Browser
  -> Authorization: Bearer <token>
  -> FastAPI current_user
       -> verify signature + expiry
       -> load active User from PostgreSQL
       -> load roles + effective permissions
       -> inject User into router
  -> require_permission("facebook_account:read")
  -> router/service query WHERE user_id = current_user.id
       hoặc cross-tenant khi có permission `resource:action:any`
  -> create TaskRun(user_id=current_user.id)
  -> Redis job {run_id, user_id}
  -> worker reloads TaskRun WHERE id=run_id AND user_id=user_id
  -> logs/items/events giữ user_id
  -> SSE subscription lọc theo authenticated user_id
```

## 5. Phase 0 — Baseline và inventory

### Công việc

- Chạy baseline trước khi sửa:
  - `python -m pytest -q`
  - `npm run lint`
  - `npm run build`
  - `docker compose config --quiet`
- Lập bảng inventory cho mọi model và endpoint:
  - Model có/không có `user_id`.
  - Collection endpoint có filter user hay chưa.
  - Detail/update/delete endpoint có ownership check hay chưa.
  - Background job có mang user context hay chưa.
- Tìm toàn repo:
  - `session.get(`
  - `select(` không có `user_id`
  - route có `{id}`, `{run_id}`, `{task_id}`, `{session_id}`
  - raw `fetch(` trong frontend
  - event publish/subscribe

### File output

- Tạo `docs/plans/multi-user-endpoint-inventory.md`.

### Tiêu chí hoàn tất

- Inventory bao phủ 100% router trong `backend/app/routers/`.
- Ghi rõ endpoint nào là global system endpoint hợp lệ, ví dụ `/api/health`.
- Không sửa business logic trong phase này.

## 6. Phase 1 — Bật lại authentication thật

### Backend

Sửa `backend/app/auth.py`:

- `current_user` yêu cầu header `Authorization: Bearer <token>`.
- Gọi `parse_token` và từ chối token:
  - sai chữ ký;
  - hết hạn;
  - user không tồn tại;
  - user bị disabled.
- Không fallback default admin khi request protected thiếu token.
- Tách dependency nếu cần:
  - `optional_current_user` cho endpoint public đặc biệt;
  - `current_user` bắt buộc cho endpoint protected.
- Giữ public:
  - login;
  - register;
  - forgot/reset password;
  - OAuth start/callback;
  - health/root.

### Frontend

Audit `frontend/src/lib/api-client.ts`:

- Mọi JSON request protected dùng `apiFetch`.
- Thêm helper `apiFormData` cho upload có Bearer token nhưng không tự set `Content-Type`.
- Raw `fetch()` chỉ được giữ cho:
  - health public;
  - OAuth navigation;
  - trường hợp có giải thích rõ và header auth đầy đủ.
- Dashboard shell phải kiểm tra `/api/auth/me` và redirect `/login` khi token không hợp lệ.
- Logout phải xóa token/user rồi full reload hoặc redirect an toàn.

### Test bắt buộc

- Thiếu token vào protected endpoint -> `401`.
- Token sai chữ ký -> `401`.
- Token hết hạn -> `401`.
- Token của disabled user -> `401`.
- Login/register/OAuth start vẫn public.

### Tiêu chí hoàn tất

- Không protected endpoint nào hoạt động khi thiếu token.
- User đăng nhập hợp lệ vẫn dùng được dashboard.

## 7. Phase 2 — Chuẩn hóa schema ownership bằng Alembic

### Audit model

Kiểm tra các bảng sau có `user_id NOT NULL`, foreign key và index:

- `facebook_accounts`
- `facebook_pages`
- `facebook_groups`
- `external_pages`
- `browser_sessions`
- `source_posts`
- `share_campaigns`
- `scheduled_posts`
- `share_targets`
- `task_runs`
- `task_items`
- `task_logs`
- `proxy_keys`
- `app_settings`

### Quyết định ownership

- Nếu `task_items`/`task_logs` chưa có `user_id`, có hai lựa chọn:
  - thêm `user_id` trực tiếp để filter nhanh và audit dễ;
  - hoặc bắt buộc join qua `task_runs.user_id`.
- Khuyến nghị thêm `user_id` trực tiếp và foreign key để giảm nguy cơ query quên join.
- `proxy_keys` và `app_settings` phải per-user nếu mỗi user có cấu hình riêng.

### Migration

Tạo Alembic revision mới sau `20260713_0002`, ví dụ:

```text
20260713_0003_multi_user_ownership
```

Migration phải:

- Thêm column nullable trước nếu bảng đã có dữ liệu.
- Backfill dữ liệu cũ về default admin một lần.
- Tạo foreign key/index/unique constraint theo user.
- Chuyển column sang `NOT NULL` sau backfill.
- Dùng unique constraint dạng tenant-scoped, ví dụ `(user_id, uid)`.
- Không import mutable `Base.metadata.create_all()` trong migration mới.
- Có downgrade rõ ràng hoặc ghi lý do nếu downgrade phá dữ liệu không được hỗ trợ.

### Test migration

- Upgrade database mới từ zero tới head.
- Upgrade database hiện tại từ `0002` tới head.
- Kiểm tra không mất record cũ.
- `alembic heads` chỉ có một head.

## 8. Phase 2B — RBAC roles và permissions

### Mục tiêu

Thêm lớp authorization theo quyền bên cạnh tenant ownership. Một request chỉ được thực thi khi đồng thời thỏa mãn:

1. User đã xác thực và đang active.
2. User có permission cho hành động.
3. Record thuộc tenant của user, trừ khi user có permission cross-tenant `:any` tương ứng.

RBAC không được thay thế ownership. Có permission `facebook_account:read` chỉ cho phép đọc account của chính user; muốn đọc tenant khác phải có thêm `facebook_account:read:any`.

### Schema database

Tạo hoặc chuẩn hóa các bảng:

- `roles`
  - `id`
  - `name` unique, ví dụ `super_admin`, `admin`, `manager`, `staff`, `user`
  - `display_name`
  - `description`
  - `is_system`
  - timestamps
- `permissions`
  - `id`
  - `code` unique theo dạng `resource:action` hoặc `resource:action:any`
  - `resource`
  - `action`
  - `description`
  - `is_system`
- `role_permissions`
  - composite unique `(role_id, permission_id)`
- `user_roles`
  - composite unique `(user_id, role_id)`
  - `assigned_by_user_id` nullable cho bootstrap/system
  - `assigned_at`

Nếu giữ column legacy `users.role`, migration phải:

- tạo role tương ứng;
- backfill `user_roles` từ `users.role`;
- chuyển code sang đọc `user_roles`;
- chỉ xóa `users.role` ở revision sau khi toàn bộ code/test không còn phụ thuộc.

Tạo Alembic revision riêng, ví dụ:

```text
20260713_0004_rbac_roles_permissions
```

Không gộp migration ownership và RBAC thành một revision quá lớn nếu có thể rollback độc lập.

### Permission catalog ban đầu

Tối thiểu phải seed các permission sau:

```text
user:read
user:create
user:update
user:disable
user:delete
role:read
role:create
role:update
role:delete
permission:read
permission:assign

facebook_account:read
facebook_account:create
facebook_account:update
facebook_account:delete
facebook_account:check
facebook_account:sync
facebook_account:read:any
facebook_account:update:any
facebook_account:delete:any

facebook_page:read
facebook_page:post
facebook_group:read
facebook_group:share

task:read
task:create
task:cancel
task:delete
task:read:any
task:cancel:any

scheduled_post:read
scheduled_post:create
scheduled_post:update
scheduled_post:delete

proxy:read
proxy:manage
settings:read
settings:update
browser_session:read
browser_session:manage
audit_log:read
tenant:read:any
tenant:manage:any
```

Catalog phải nằm ở một module version-controlled, ví dụ `backend/app/rbac_catalog.py`, không rải string tùy ý khắp router.

### Role mặc định

- `super_admin`
  - toàn bộ permission, bao gồm `:any`;
  - chỉ seed cho default owner/bootstrap user;
  - không cho user thường tự gán.
- `admin`
  - quản lý user/role trong tenant hoặc scope được thiết kế;
  - quản lý toàn bộ resource của chính mình;
  - không mặc định có `:any`.
- `manager`
  - đọc/tạo/chạy task, quản lý Facebook resources và lịch đăng;
  - không quản lý role/permission.
- `staff`
  - đọc resource được giao, tạo/chạy task theo chính sách;
  - không xóa user hoặc thay settings nhạy cảm.
- `user`
  - CRUD dữ liệu cá nhân cơ bản;
  - không quản trị user/role.

Không hard-code `if user.role == "admin"` trong router sau phase này.

### Backend authorization layer

Tạo module, ví dụ:

- `backend/app/rbac.py`
- `backend/app/services/permission_service.py`
- `backend/app/routers/roles.py`

Các primitive bắt buộc:

```python
require_permission("task:create")
require_any_permission("task:read", "task:read:any")
has_permission(user, "facebook_account:delete:any")
```

`current_user` hoặc dependency kế tiếp phải trả auth context có:

```python
AuthenticatedUser(
    user=user,
    role_codes={...},
    permission_codes={...},
)
```

Có thể cache permission trong Redis với key:

```text
flowmeta:rbac:user:{user_id}:permissions:{version}
```

Nhưng phase đầu ưu tiên correctness; chỉ cache sau khi có invalidation khi assign/unassign role hoặc permission.

### Ownership + permission helper

Chuẩn hóa helper để router không tự viết logic khác nhau:

```python
async def get_owned_or_any(
    session,
    model,
    resource_id,
    actor,
    own_permission,
    any_permission,
):
    ...
```

Hành vi:

- thiếu permission own và any -> `403`;
- có own permission, record thuộc actor -> trả record;
- có own permission nhưng record thuộc user khác -> `404`;
- có any permission -> cho phép query cross-tenant và ghi audit log;
- record không tồn tại -> `404`.

### API quản trị RBAC

Tối thiểu:

- `GET /api/roles`
- `POST /api/roles`
- `PATCH /api/roles/{role_id}`
- `DELETE /api/roles/{role_id}`
- `GET /api/permissions`
- `PUT /api/roles/{role_id}/permissions`
- `GET /api/users/{user_id}/roles`
- `PUT /api/users/{user_id}/roles`
- `GET /api/auth/me/permissions`

Quy tắc:

- System role/permission không được xóa.
- Không cho user tự nâng quyền.
- Không cho xóa/gỡ role của super admin cuối cùng.
- Assignment thay đổi phải ghi audit log.
- API response không trả cấu trúc DB thừa hoặc secret.

### Frontend RBAC

Thêm type và hook:

- `AuthUser.roles: string[]`
- `AuthUser.permissions: string[]`
- `usePermission(code)`
- `<Can permission="task:create">...</Can>` nếu thực sự giúp giảm lặp.

Frontend dùng permission để:

- ẩn navigation không được phép;
- disable action với thông báo rõ;
- không render nút quản lý role/user nếu thiếu quyền;
- hiển thị trang 403 phù hợp.

Frontend chỉ cải thiện UX; backend vẫn phải enforce toàn bộ permission.

### RBAC test matrix

Tạo fixture role/user rõ ràng:

- User A role `user`.
- User B role `user`.
- Manager M.
- Admin N không có `:any`.
- Super Admin S có `:any`.

Test tối thiểu:

- User thiếu permission -> `403` dù record thuộc chính mình.
- User có permission own -> thao tác record của mình thành công.
- User có permission own -> record user khác trả `404`.
- Admin không có `:any` -> không đọc record user khác.
- Super Admin có `resource:action:any` -> đọc được và có audit log.
- User không thể tự gán role admin/super admin.
- Không thể xóa system role/permission.
- Không thể gỡ super admin cuối cùng.
- Thay role làm effective permissions thay đổi ngay, không dùng cache cũ.
- Hai user cùng role vẫn không thấy dữ liệu nhau.

### Tiêu chí hoàn tất

- Không còn authorization logic dựa vào string `users.role` trong router.
- Mọi protected action quan trọng có permission code từ catalog.
- Ownership và RBAC cùng được test, không chỉ test riêng lẻ.
- Role/permission seed idempotent trên DB mới và DB hiện tại.
- Migration upgrade pass và chỉ có một Alembic head.

## 9. Phase 3 — Cô lập Facebook resources

### Modules

- `backend/app/routers/facebook_accounts.py`
- `backend/app/routers/facebook_oauth.py`
- `backend/app/routers/page_tasks.py`
- Các service Facebook liên quan.

### Quy tắc

- List/import/check/sync/delete account phải scope user.
- Page/group/external page phải scope user.
- Khi nhận `account_id`, query:

```python
select(FacebookAccount).where(
    FacebookAccount.id == account_id,
    FacebookAccount.user_id == user.id,
)
```

- Không dùng `session.get(FacebookAccount, account_id)` trong request user-scoped nếu không kiểm tra ownership ngay sau đó.
- OAuth Facebook quản lý page phải gắn kết quả về user bắt đầu flow, không default admin.
- Browser profile path phải bao gồm user ID và account ID.

### Cross-user test matrix

Với User A và User B:

- A import account A -> A thấy.
- B list -> không thấy account A.
- B check/sync/delete account A -> `404`.
- B không thấy pages/groups/external pages của A.
- Unique UID chỉ unique trong từng user; A và B có thể lưu cùng UID nếu business cho phép.

## 10. Phase 4 — Cô lập task, item và log

### Modules

- `backend/app/routers/comment_tasks.py`
- `backend/app/routers/tasks.py`
- `backend/app/routers/page_tasks.py`
- `backend/app/services/task_runner.py`
- `backend/app/services/task_queue.py`
- `backend/app/worker.py`
- Models task.

### Công việc

- Khi tạo run: luôn `user_id=current_user.id`.
- List/detail/cancel/log/items query theo cả ID và user ID.
- Không cho User B đoán `run_id` của A để:
  - xem summary;
  - xem item;
  - xem log;
  - cancel;
  - restart.
- Queue payload chứa:

```json
{
  "run_id": "...",
  "user_id": "..."
}
```

- Worker reload run bằng cả `run_id` và `user_id`.
- Token/account lookup trong runner phải scope theo `run.user_id`.
- Log/item được tạo phải mang cùng user ID với run.
- Khi job payload và DB ownership lệch nhau: fail job, ghi security log, không chạy Graph action.

### Test bắt buộc

- B không đọc/cancel task A.
- Worker từ chối payload user mismatch.
- Task A không dùng Facebook token của B dù UID giống nhau.
- Logs/items luôn có cùng owner với run.

## 11. Phase 5 — Scheduler, share và browser session

### Scheduler

- `scheduled_posts` list/create/update/pause/resume/delete/fire-now scope user.
- Scheduler background scan có thể lấy nhiều user, nhưng mỗi run tạo ra phải copy đúng `scheduled_post.user_id`.
- Target của scheduled post phải thuộc cùng user.
- Không cho lịch A tham chiếu target B.

### Share

- Campaign/source/target phải cùng owner.
- Khi tạo campaign, validate toàn bộ selected target thuộc current user.
- Khi start campaign, reload campaign theo `(id, user_id)`.

### Browser sessions/extension

- Session list/detail/stop scope user.
- Extension connection/job phải liên kết user rõ ràng.
- Không để extension của A nhận job B.
- Redis key/session key phải prefix user ID.

### Test bắt buộc

- Cross-user scheduled post access -> `404`.
- A không schedule lên page/group B.
- Extension A không poll được job B.
- Browser session B không mở/stop session A.

## 12. Phase 6 — Proxy và settings per-user

### Modules

- `backend/app/routers/proxy.py`
- `backend/app/routers/settings.py`
- `backend/app/services/proxy_manager.py`
- `backend/app/services/kiotproxy_client.py`
- Frontend proxy/settings pages.

### Công việc

- `proxy_keys` gắn `user_id` và unique theo user.
- `app_settings` chuyển từ singleton global sang một record/user hoặc key-value có composite unique `(user_id, key)`.
- ProxyManager không giữ một pool dùng chung. Dùng registry:

```text
user_id -> UserProxyManager
```

- Redis keys:

```text
flowmeta:{user_id}:proxy:...
```

- Task A chỉ acquire proxy A.
- Khi user logout không nhất thiết stop worker, nhưng manager phải không trộn state.

### Test bắt buộc

- A/B có settings khác nhau.
- A không thấy/xóa/start/stop proxy B.
- Task A không lấy IP từ pool B.

## 13. Phase 7 — SSE/event isolation

### Modules

- `backend/app/event_bus.py`
- `backend/app/main.py`
- Mọi nơi gọi `event_bus.publish`.
- `frontend/src/lib/sse-client.ts`.

### Backend

- SSE endpoint bắt buộc `current_user`.
- Mọi event schema có `user_id`.
- Có thể chọn một trong hai mô hình:

```text
channel = user:{user_id}:log
```

hoặc channel chung nhưng filter server-side trước khi yield.

- Khuyến nghị channel theo user để tránh subscriber nhận rồi mới loại.
- Event task nên có thêm `run_id` để frontend lọc đúng task.
- Không chấp nhận `user_id` query param từ frontend để thay ownership.

### Frontend

EventSource native không gửi Authorization header. Chọn một giải pháp:

1. Chuyển auth sang HttpOnly cookie và dùng EventSource với cookie; hoặc
2. Dùng fetch streaming hỗ trợ Bearer header; hoặc
3. Cấp SSE ticket ngắn hạn, one-time, scope user.

Khuyến nghị dài hạn: HttpOnly secure session cookie. Nếu chưa chuyển cookie, dùng SSE ticket thay vì token dài hạn trên query string.

### Test bắt buộc

- A publish log -> A nhận.
- B không nhận log A.
- Ticket/token của A không subscribe channel B.
- Disconnect/reconnect không đổi tenant.

## 14. Phase 8 — Frontend tenant-safe behavior

### Công việc

- Sau login, mọi cache/state phải được reset khi user thay đổi.
- Logout dùng full page reload để xóa state route được Next.js Activity giữ lại.
- Không lưu dữ liệu user A trong global store rồi hiển thị cho B.
- Nếu dùng localStorage cho form draft, key phải gồm user ID.
- Polling task phải dừng khi logout hoặc user thay đổi.
- Upload FormData gửi auth đúng.
- Error handling:
  - login 401 -> sai thông tin đăng nhập;
  - protected API 401 -> hết phiên;
  - ownership 404 -> không tìm thấy dữ liệu.

### E2E flow

1. Login User A.
2. Import Facebook account A.
3. Tạo task A.
4. Logout.
5. Login User B.
6. Không thấy account/task/log A.
7. Gọi trực tiếp URL/API bằng ID của A -> bị từ chối.
8. Tạo account/task B.
9. Login lại A -> chỉ thấy A.

## 15. Phase 9 — Security hardening

Thực hiện sau khi isolation cơ bản pass:

- Chuyển access token khỏi localStorage sang HttpOnly, Secure, SameSite cookie.
- Thêm refresh token rotation và revoke session nếu cần.
- CSRF protection cho cookie-auth mutation.
- Rate limit login/register/reset/OAuth callback.
- Audit log cho:
  - login success/failure;
  - ownership violation;
  - user disabled;
  - task cancel/delete;
  - proxy/settings change.
- Không log access token, Facebook token, OAuth code, client secret hoặc reset token.
- Cấu hình secure headers/CSP ở Caddy/Nginx.

## 16. Phase 10 — CI, integration và rollout

### CI gates

- Backend unit test.
- Cross-user isolation test suite.
- Alembic upgrade test trên PostgreSQL service container.
- Frontend lint/build.
- Playwright E2E hai user.
- Docker Compose validation.

### Rollout

1. Backup PostgreSQL.
2. Deploy migration.
3. Verify record cũ được gắn default admin.
4. Deploy backend/worker/frontend cùng version.
5. Smoke test A/B trên staging.
6. Theo dõi 401/403/404 và queue failure.
7. Chỉ bật production khi cross-user checklist đạt toàn bộ.

### Rollback

- Giữ backup trước migration.
- Không downgrade migration nếu sẽ làm mất ownership data; rollback application image và restore DB nếu cần.
- Không tái bật fallback default admin để chữa nhanh lỗi production.

## 17. Danh sách endpoint cần audit tối thiểu

### Auth/users

- `/api/auth/me`
- `/api/auth/users*`
- `/api/roles*`
- `/api/permissions*`
- `/api/users/{user_id}/roles`

### Facebook

- `/api/facebook-accounts*`
- `/api/facebook-pages`
- `/api/facebook-groups*`
- `/api/external-pages*`
- `/api/post-targets`
- `/api/share-targets`

### Tasks

- `/api/comment-tasks`
- `/api/tasks*`
- `/api/page-post-tasks*`
- `/api/share-campaigns*`

### Scheduler/browser/extension

- `/api/scheduled-posts*`
- `/api/browser-sessions*`
- `/api/extension*`

### Config/runtime

- `/api/proxy*`
- `/api/settings`
- `/api/events/stream`

## 18. Definition of Done

Chỉ đánh dấu hoàn tất khi:

- `current_user` xác thực token thật, không fallback.
- Roles/permissions đã được migrate và seed idempotent.
- Mọi protected action quan trọng được backend kiểm tra permission.
- Không còn `if user.role == ...` rải rác trong router.
- Permission own không được phép bỏ qua tenant ownership.
- Cross-tenant chỉ hoạt động với permission `:any` và có audit log.
- 100% endpoint protected có ownership policy rõ ràng.
- User A/B isolation pass cho list/detail/update/delete/action.
- Queue/worker/scheduler không trộn user.
- SSE không rò log/event chéo user.
- Proxy/settings per-user hoặc được ghi rõ là global admin-only và enforced.
- Migration chạy được trên DB mới và DB hiện tại.
- Backend tests, integration tests, frontend lint/build, E2E và compose đều pass.
- Tài liệu deployment và env được cập nhật.
- Không có secret/token trong log hoặc URL không an toàn.

## 19. Quy tắc thực thi cho agent

- Làm tuần tự theo phase; không sửa đồng thời nhiều lớp khi chưa có test baseline.
- Sau mỗi phase phải báo cáo:
  - Đã hoàn thành gì.
  - File/module nào thay đổi.
  - Test/check nào đã chạy và kết quả.
  - Còn gì chưa xong hoặc đang bị block.
- Không ghi đè thay đổi không liên quan trong worktree.
- Mọi thay đổi schema phải qua Alembic version mới.
- Không dùng `Base.metadata.create_all()` thay migration.
- Không thêm TODO/TBD vào code hoàn tất.
- Không coi frontend ẩn nút là authorization; backend luôn là lớp cưỡng chế cuối cùng.
- Mỗi endpoint sửa ownership phải đi kèm ít nhất một negative cross-user test.
- Mỗi action thêm RBAC phải có test thiếu quyền, có quyền own và quyền `:any` nếu áp dụng.

## 20. Mẫu báo cáo phase

```text
Phase X — <Tên phase>

Completed:
- ...

Changed files/modules:
- ...

Checks/tests:
- command: result

Remaining/blocked:
- ...

Security notes:
- User A/B behavior verified: ...
- RBAC behavior verified: ...
```

## 21. Thứ tự commit khuyến nghị

1. `test: add multi-user isolation fixtures and baseline matrix`
2. `fix: enforce authenticated current_user`
3. `feat: add tenant ownership migration`
4. `feat: add RBAC schema catalog and permission dependencies`
5. `feat: add role permission management APIs and UI`
6. `fix: isolate facebook resources by user and permission`
7. `fix: isolate task queue logs and worker execution`
8. `fix: isolate scheduler browser and extension jobs`
9. `feat: make proxy and settings user-scoped`
10. `fix: isolate SSE events by authenticated user`
11. `fix: reset frontend state across user sessions`
12. `test: add RBAC and two-user Playwright E2E gates`
13. `docs: document tenant RBAC deployment and rollback`
