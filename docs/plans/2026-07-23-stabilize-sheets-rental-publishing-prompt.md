# Prompt triển khai: ổn định luồng đăng từ Google Sheets và NhatroVN

Sao chép toàn bộ phần từ **“BẮT ĐẦU PROMPT”** đến **“KẾT THÚC PROMPT”** để giao cho coding agent.

---

## BẮT ĐẦU PROMPT

Bạn là senior engineer chịu trách nhiệm hoàn thiện và ổn định production cho hai luồng:

1. Đăng nội dung tự động từ Google Sheets lên Facebook.
2. Đồng bộ phòng từ `quanly.nhatrovn.vn`, ghép nhóm và đăng phòng lên Facebook.

Làm việc trực tiếp trong repository hiện tại. Không chỉ viết kế hoạch hoặc mô tả: hãy khảo sát code, triển khai migration/backend/frontend, bổ sung test, chạy kiểm tra và sửa đến khi các tiêu chí nghiệm thu bên dưới đạt. Không được báo hoàn thành chỉ vì unit test dùng mock đã pass.

### 1. Quy tắc làm việc bắt buộc

- Đọc và tuân thủ `AGENTS.md` ở root và mọi `AGENTS.md` trong thư mục con trước khi sửa file thuộc phạm vi đó.
- Kiểm tra `git status` trước khi làm. Worktree hiện có thể đang bẩn; bảo toàn mọi thay đổi của người dùng và không reset/checkout/xóa chúng.
- Không commit, push, deploy hoặc gọi dịch vụ thật nếu người dùng chưa yêu cầu rõ.
- Sau mỗi phase, báo:
  - Đã hoàn thành gì.
  - File/module nào thay đổi.
  - Test/check nào đã chạy và kết quả.
  - Còn gì hoặc đang bị chặn.
- Dùng migration Alembic; không sửa database production thủ công.
- API mới hoặc API sửa đổi phải dùng schema Pydantic rõ ràng, không dùng `body: dict` cho payload nghiệp vụ.
- Không log service-account JSON, private key, access token, mật khẩu NhatroVN, cookie đăng nhập hoặc nội dung bí mật.
- Mọi dữ liệu, target, connection và tác vụ phải được cách ly theo `user_id`.
- Nếu cần thay đổi kiến trúc so với đề bài, phải giải thích bằng bằng chứng từ code hiện tại và giữ các invariants ở mục 3.

### 2. Hiện trạng đã xác minh

Các test hiện tại đều xanh nhưng chưa chứng minh luồng end-to-end đúng:

- Backend: 93 passed, 1 skipped.
- Test riêng Google Sheets + rental: 34 passed.
- Frontend production build: pass.

Các lỗi đã được phát hiện:

1. Google Sheets hiện chỉ có CRUD/test/preview connection và hàm ghi; chưa có worker đọc dòng `READY`, campaign, source item, publication job, scheduler hoặc write-back kết quả.
2. `RentalPostService` đánh dấu group đã đăng và có thể chuyển phòng sang `posted` ngay sau khi gọi `_run_page_post_task`.
3. `_run_page_post_task` với group chỉ enqueue browser/extension job; chưa có kết quả Facebook cuối cùng và còn bắt exception rồi không propagate. Do đó có false-success.
4. Ảnh phòng được lưu trong `images_json` nhưng lúc đăng truyền `media_paths=[]`.
5. Phòng đã tồn tại không được cập nhật khi nguồn đổi sang “Đã thuê”; phòng cũ vẫn có thể nằm trong hàng đợi đăng.
6. `POST /api/rental/configs/{config_id}/post-now` kiểm tra config được chọn nhưng gọi `post_due()` cho mọi config.
7. Mirror rental → Google Sheet chạy sau DB commit, lỗi chỉ log. Lần sau phòng bị dedup nên dòng Sheet có thể mất vĩnh viễn.
8. `google_sheet_connection_id` chỉ được kiểm tra định dạng UUID, chưa kiểm tra connection thuộc cùng user.
9. Sync NhatroVN lỗi vẫn trả payload thành công với các bộ đếm bằng 0, khiến UI báo “Đồng bộ xong”.
10. `post_delay_seconds` có trong model nhưng chưa được áp dụng.
11. Retry hiện dựa vào exception lúc dispatch, không dựa vào kết quả đăng cuối cùng.
12. `post_urls_json` đang lưu `run_id`, không phải Facebook URL như tên trường/UI kỳ vọng.
13. Scheduler chạy tuần tự trong một vòng 60 giây và chưa có cơ chế chống hai process/instance cùng nhận một việc.
14. Validation config rental còn lỏng: ép `int` có thể gây 500, số âm/quá lớn không bị chặn, `bool("false")` thành `True`, timezone và độ dài chuỗi chưa được kiểm soát đầy đủ.
15. Matching group theo phép `substring` có thể match nhầm; target không còn khả dụng chưa được phản ánh ổn định.

Hãy tự kiểm tra lại từng nhận định trong code trước khi sửa và tìm thêm lỗi liên quan. Không giới hạn việc sửa chỉ ở danh sách này.

### 3. Invariants kiến trúc bắt buộc

#### 3.1. Trạng thái thành công

- `queued` hoặc `dispatched` không phải là `posted`.
- Chỉ ghi `posted` cho một target khi `TaskItem`/publisher trả kết quả cuối cùng thành công.
- Chỉ ghi `facebook_url` khi nhận được URL thật. `run_id` và `task_item_id` phải lưu ở trường riêng.
- Một source item/phòng chỉ thành `posted` khi tất cả target bắt buộc thành công.
- Thành công một phần phải là `partial`; thất bại hết retry phải là `failed`.
- Trạng thái chờ duyệt Facebook nếu phát hiện được phải được lưu riêng, không coi là thành công kỹ thuật.

#### 3.2. Idempotency và concurrency

- Một source item + một target chỉ có tối đa một publication job logic.
- Worker restart, API retry, scheduler chạy lại hoặc hai backend instance chạy đồng thời không được tạo bài Facebook trùng.
- Claim job bằng transaction/row lock phù hợp với PostgreSQL, ưu tiên `SELECT ... FOR UPDATE SKIP LOCKED` hoặc cơ chế tương đương.
- Thêm unique constraint ở DB cho khóa idempotency; không chỉ kiểm tra bằng Python.
- Không giữ database transaction mở trong lúc gọi Google, NhatroVN hoặc Facebook lâu.
- Trạng thái `dispatching` bị treo phải có timeout/recovery an toàn.

#### 3.3. Phân quyền

- Mọi query theo UUID nhận từ client phải kiểm tra ownership.
- Rental config chỉ được liên kết Google Sheet connection cùng `user_id`.
- Campaign chỉ được tham chiếu Facebook target cùng `user_id`.
- Worker khi resolve target phải lọc lại `user_id`, kể cả dữ liệu trong DB từng bị ghi sai.
- Manual sync/post/retry chỉ tác động resource nằm trong scope endpoint.

#### 3.4. Xử lý lỗi và retry

- Lỗi tích hợp phải có mã/trạng thái rõ, lưu `last_error`, log có context nhưng không có secret.
- Retry chỉ áp dụng lỗi tạm thời; lỗi validation, ownership hoặc credential sai không được retry vô hạn.
- Dùng exponential backoff có giới hạn và `next_retry_at`.
- Sau khi hết số lần thử, chuyển trạng thái cuối `failed/error`.
- API thủ công phải trả lỗi HTTP phù hợp; không trả “thành công 0 dòng” khi thực tế đăng nhập/fetch/ghi thất bại.

### 4. Kiến trúc đích: publication pipeline bền vững

Tạo hoặc hoàn thiện một pipeline dùng chung theo từng target. Có thể dùng model `PublicationJob` dùng chung cho cả Sheet và rental, hoặc tách model nếu codebase buộc phải tách; dù chọn cách nào vẫn phải đáp ứng các invariants.

Một publication job tối thiểu cần có:

- `id`, `user_id`.
- Một liên kết nguồn duy nhất: `sheet_source_item_id` hoặc `rental_room_id`.
- `target_type`: `page`, `group`, `personal`.
- `target_id` là UUID nội bộ; nếu cần lưu Facebook ID ngoài thì dùng trường riêng.
- `scheduled_at`.
- `status`: `pending`, `dispatching`, `queued`, `running`, `pending_review`, `succeeded`, `failed`, `canceled`.
- `attempt_count`, `max_attempts`, `next_retry_at`.
- `task_run_id`, `task_item_id`.
- `facebook_post_id`, `facebook_url`, `result_message`, `error`.
- `claimed_at`, `started_at`, `finished_at`, timestamps chuẩn.
- Unique constraint bảo đảm một nguồn không tạo trùng cùng target.

Luồng chuẩn:

```text
Source sync
  -> validate + persist source trong DB
  -> tạo publication jobs trong cùng transaction
  -> commit
  -> worker claim job đến hạn
  -> dispatch sang publisher hiện có
  -> lưu task_run_id/task_item_id, trạng thái queued/running
  -> browser/extension/Graph hoàn thành
  -> reconcile kết quả TaskItem
  -> cập nhật publication job
  -> aggregate trạng thái source
  -> ghi kết quả ngược về Google Sheet hoặc RentalRoom
```

Refactor publisher hiện tại để có contract rõ:

- Dispatch phải trả structured result, tối thiểu gồm `accepted`, `task_run_id`, `task_item_ids`, lỗi dispatch nếu có.
- Không nuốt exception rồi trả về như thành công.
- Với browser/extension job, kết quả dispatch chỉ là `queued`.
- Kết quả cuối phải được cập nhật từ callback/event hiện có hoặc reconciliation worker đọc `TaskItem`.
- Giữ tương thích với các tính năng đang dùng `_run_page_post_task`; bổ sung regression test cho auto-post/scheduled-post hiện tại.

### 5. Hoàn thiện luồng Google Sheets làm nguồn đăng

Tham khảo thiết kế hiện có tại:

- `docs/plans/2026-07-20-google-sheets-auto-publishing.md`
- `backend/app/services/google_sheets.py`
- `backend/app/routers/google_sheets.py`
- `frontend/src/app/google-sheets/page.tsx`

#### 5.1. Model và migration

Tạo tối thiểu:

1. `SheetCampaign`
   - Owner, connection.
   - Tên campaign.
   - Default targets.
   - Default schedule mode.
   - Slot AUTO, active weekdays, timezone.
   - Max post/day, min gap.
   - Target delay, retry policy, late policy.
   - Enabled/status, last sync/error.

2. `SheetSourceItem`
   - Connection/campaign, `external_id`, `sheet_row_number`.
   - Content/link/media URLs/targets.
   - Schedule mode/requested time/scheduled time.
   - `content_hash`, `source_version`.
   - Validation và aggregate status.
   - Timestamps nhận/queue/hoàn tất.
   - Unique constraint phù hợp, tối thiểu connection + sheet + external ID.

3. `PublicationJob` theo mục 4.

4. Cơ chế write-back bền vững:
   - Có thể dùng `SheetWritebackJob`/outbox hoặc các cột retry riêng.
   - Phải lưu row number, payload/version, attempts, next retry và lỗi.
   - Write-back thất bại không được tạo lại publication job.

Migration phải có upgrade/downgrade hợp lệ và test model/migration.

#### 5.2. Google API service

Bổ sung:

- Đọc range theo batch, không chỉ preview.
- Xác thực header và trả danh sách header thiếu/sai.
- Parse row kèm số dòng thật.
- Batch update/write-back để giảm quota.
- Timeout rõ, retry/backoff cho 429 và lỗi 5xx phù hợp.
- Phân loại 401/403/404/quota/network.
- Validate `sheet_name` và escape A1 notation an toàn.
- Không tải toàn bộ sheet không giới hạn; có pagination/range cap.

Header MVP:

```text
external_id
content
media_urls
link
targets
schedule_mode
publish_at
priority
status
facebook_urls
result
error
queued_at
posted_at
```

Chỉ nhận dòng `status=READY` không phân biệt hoa thường sau normalize. Dòng thiếu `external_id`, không có content lẫn media, target sai, thời gian sai hoặc media không hợp lệ phải được ghi `INVALID` cùng lỗi cụ thể.

#### 5.3. Scheduling

Hỗ trợ:

- `NOW`: tạo job đến hạn ngay nhưng vẫn qua queue/throttle.
- `EXACT`: parse theo timezone campaign; áp dụng `late_policy`.
- `AUTO`: chọn slot trống theo weekday, quota ngày, min gap và priority.

Dùng `zoneinfo.ZoneInfo`, lưu UTC trong DB và chỉ chuyển timezone ở biên API/UI.

#### 5.4. Idempotency và thay đổi nội dung

- Cùng `external_id` + cùng content hash: sync lại không tạo job mới.
- Khi dòng còn `READY` và chưa dispatch, cho phép cập nhật version/nội dung theo rule rõ.
- Khi đã queued/running/succeeded, không âm thầm sửa payload của job cũ.
- Nếu hỗ trợ đăng lại nội dung sửa đổi, phải tăng `source_version` và khóa idempotency gồm version.

#### 5.5. Write-back

Sau DB commit:

- `READY -> QUEUED` kèm `queued_at` và lịch dự kiến.
- Aggregate cuối: `POSTED`, `PARTIAL`, `FAILED`, `CANCELED`, `INVALID`.
- Ghi URL Facebook thật, số target thành công/thất bại và lỗi rút gọn.
- Nếu Google API lỗi, outbox retry đến khi thành công hoặc hết policy; không đăng lại Facebook.
- Dùng source version để tránh write-back cũ ghi đè trạng thái mới.

#### 5.6. API và UI

Bổ sung API CRUD/test/sync/pause/resume cho campaign; API list/detail/filter/retry/cancel/publish-now cho source item và publication job.

UI tối thiểu:

- Trang connections giữ chức năng hiện tại và hiển thị quyền đọc/ghi.
- Trang/cụm campaign cho phép chọn connection, target, schedule và bật/tắt.
- Queue hiển thị source row, lịch, target status, retry, lỗi và URL Facebook.
- Nút “Đồng bộ ngay” phải phản ánh lỗi thật.
- Không hiển thị lại credentials đã lưu.

### 6. Ổn định luồng NhatroVN/rental

#### 6.1. Validation và ownership

- Thay `body: dict` bằng schema create/update/assign rõ ràng.
- Validate:
  - Chuỗi bắt buộc sau khi trim.
  - Độ dài theo DB.
  - `post_spacing_seconds`, `post_delay_seconds`, `poll_interval_seconds` trong khoảng an toàn.
  - `auto_post` là strict boolean.
  - Timezone tồn tại.
  - UUID đúng kiểu.
- Khi gắn Sheet connection, query connection với cả `id` và `user_id`; trả 404/400 nếu không thuộc user hoặc không có quyền ghi.
- Khi assign groups, kiểm tra mọi group UUID/FBID đều thuộc user và còn khả dụng.

#### 6.2. Adapter và sync

- Kiểm tra HTTP status cho cả GET/POST login và search.
- Phát hiện session hết hạn/login page trả lại trong lúc fetch.
- Có giới hạn trang cấu hình được, đồng thời báo rõ nếu chạm `max_pages` thay vì im lặng coi là đã lấy hết.
- Không nhận `external_room_id` rỗng.
- Normalize trạng thái Unicode đúng; test bằng text tiếng Việt thật, không dựa vào chuỗi mojibake.
- Upsert phòng đã tồn tại:
  - Cập nhật title, giá, diện tích, địa chỉ, mô tả, ảnh và source status.
  - Nếu chuyển sang “Đã thuê”/không còn khả dụng: hủy publication job chưa chạy và không đăng tiếp.
  - Nếu quay lại trạng thái trống: áp dụng policy rõ, không tự đăng trùng những target đã thành công trước đây.
- Chống race khi manual sync và scheduler sync đồng thời.
- Lỗi credential/fetch phải cập nhật config `error` và endpoint manual trả HTTP lỗi phù hợp.
- Scheduler retry lỗi theo backoff, không hammer NhatroVN mỗi 60 giây.

#### 6.3. Matching group

- Normalize dấu, `đ`, punctuation và token địa danh.
- Không dùng substring tự do gây match kiểu `1` với `10`, hoặc tên địa danh nằm trong từ khác.
- Ưu tiên match token/word boundary và alias hành chính (`Quận`, `Huyện`, `TP`, `Thành phố`).
- Dedup group ID.
- Group không còn available phải đưa phòng/job về trạng thái cần can thiệp, không coi là đăng thành công.
- Giữ khả năng gán nhóm thủ công.

#### 6.4. Caption và media

- Render caption bằng placeholder whitelist; báo warning/validation cho placeholder lạ thay vì âm thầm che mọi lỗi.
- Bảo toàn tiếng Việt và newline.
- Ảnh nguồn phải được đưa thật vào publisher:
  - Normalize absolute URL.
  - Chỉ cho phép `http/https`.
  - Chặn SSRF tới loopback/private/link-local/metadata endpoint nếu downloader nhận URL tùy ý.
  - Kiểm tra MIME, size, số lượng; timeout và cleanup file tạm.
  - Lưu file theo vùng user/source riêng hoặc dùng media storage sẵn có.
  - Truyền `media_paths` thật cho publisher.
- Nếu policy yêu cầu ảnh nhưng tải ảnh thất bại, không đăng bài text-only; chuyển lỗi có thể retry.

#### 6.5. Đăng và kết quả

- Tạo publication job cho từng `phòng × group`.
- Áp dụng `post_delay_seconds` trước lượt đầu và `post_spacing_seconds` giữa các lượt của cùng config.
- Scheduler mỗi tick chỉ claim số job an toàn; không đăng đồng thời trùng config.
- `post-now(config_id)`:
  - Chỉ tác động đúng config thuộc user.
  - Có contract rõ việc bypass lịch/spacing; mặc định chỉ bỏ qua thời điểm chờ nhưng vẫn giữ safety lock và idempotency.
  - Trả các job được queue, không nói “đã đăng” nếu chưa có kết quả.
- Retry dựa trên kết quả cuối từ publisher.
- `RentalRoom.post_urls_json` chỉ chứa URL thật hoặc thay bằng bảng result chuẩn hóa. Run/task ID lưu riêng.
- Aggregate room:
  - Chưa có target: `waiting_groups`.
  - Có job chờ: `queued/posting`.
  - Thành công một phần: `partial`.
  - Tất cả thành công: `posted`.
  - Hết retry: `error/failed`.
  - Nguồn đã thuê: `rented/inactive`.

#### 6.6. Mirror rental → Google Sheet

- Xác định schema riêng rõ ràng; không ghi sáu cột rental vào sheet `Posts` theo schema auto-publishing rồi gây hiểu sai.
- Có thể yêu cầu sheet/tab riêng, ví dụ `RentalRooms`, và validate header.
- Mirror bằng outbox/writeback bền vững:
  - DB commit phòng trước.
  - Tạo mirror job trong cùng transaction.
  - Worker ghi Sheet rồi đánh dấu thành công.
  - Retry lỗi Google mà không cần tạo lại phòng.
- Upsert theo `external_room_id`, không append trùng.
- Ghi cả source status, aggregate post status, Facebook URLs thật, error và timestamps.
- Hiển thị trạng thái mirror/lỗi trong UI.

### 7. Scheduler và vận hành

- Không để một tích hợp chậm chặn toàn bộ scheduler.
- Tách tick cho scheduled posts, Sheet sync, rental sync, publication dispatch, result reconcile và Sheet write-back; có timeout/circuit breaker phù hợp.
- Exception ở một service không được bỏ qua service còn lại.
- Chống overlapping tick trong một process và nhiều instance.
- Có graceful cancellation khi shutdown.
- Có structured log với `user_id`, source ID, job ID, target ID nhưng không có secret.
- Thêm health/metrics tối thiểu:
  - Số job pending/running/retrying/failed.
  - Job bị treo quá timeout.
  - Lần sync cuối và lỗi cuối theo source.
- Không yêu cầu hạ tầng mới nếu có thể dùng PostgreSQL hiện tại; nếu dùng Redis/queue hiện có, phải có fallback/recovery rõ.

### 8. API compatibility và migration dữ liệu

- Không phá các endpoint/frontend hiện có nếu không cần thiết.
- Nếu đổi response, cập nhật đồng thời TypeScript types, API client và UI.
- Viết migration/backfill cho:
  - Rental room hiện có với `post_urls_json` đang chứa run ID.
  - Room status cũ.
  - Config liên kết Sheet sai ownership: không được tự động đọc credentials của user khác; detach và ghi lỗi an toàn.
- Dữ liệu không xác định không được gán `posted`; ưu tiên trạng thái `needs_review`.
- Migration phải chạy được trên database có dữ liệu và downgrade không làm lỗi schema.

### 9. Test bắt buộc

Không được chỉ sửa test để khớp implementation. Bổ sung test bắt đúng hành vi production.

#### 9.1. Google Sheets

- Parse URL/ID, credentials, quyền read-only/read-write.
- Header đúng/sai/thiếu/trùng.
- Chỉ nhận `READY`.
- Idempotency cùng external ID/hash/version.
- NOW/EXACT/AUTO và timezone/DST.
- Hai sync worker đồng thời không tạo job trùng.
- Google timeout/429/403/404 và retry classification.
- DB commit thành công nhưng write-back lỗi; retry không đăng trùng.
- Write-back version cũ không ghi đè version mới.
- User A không dùng được connection/target của user B.

#### 9.2. Rental

- Login/fetch/session expiry/HTTP error/max pages.
- Parse text tiếng Việt thật và loại phòng đã thuê.
- Phòng trống chuyển thành đã thuê sẽ hủy job pending.
- Phòng đã tồn tại được cập nhật dữ liệu.
- Sync concurrent không tạo trùng.
- Matching không false-positive với số quận/tên gần giống.
- Ảnh được download/validate và truyền vào publisher.
- Download lỗi không biến thành bài text-only nếu ảnh bắt buộc.
- `post_delay` và `post_spacing`.
- `post-now` chỉ chạy đúng config.
- Connection/group cross-user bị từ chối.
- Mirror lỗi rồi retry thành công, không append trùng.

#### 9.3. Publication pipeline

- Dispatch group chỉ tạo `queued`, chưa `succeeded`.
- Publisher exception không bị nuốt thành success.
- Browser/extension callback success cập nhật URL thật.
- Callback failed tăng attempt và lên lịch retry.
- Partial success aggregate đúng.
- Hết retry chuyển failed.
- Callback trùng/out-of-order là idempotent.
- Worker crash sau claim/dispatch được recovery không đăng trùng.
- Target unavailable không thành success.

#### 9.4. Regression và frontend

Chạy tối thiểu:

```powershell
cd backend
$env:PYTHONDONTWRITEBYTECODE='1'
pytest -q -p no:cacheprovider

cd ..\frontend
npm run lint
npm run build
```

Nếu lint repo có lỗi tồn tại từ trước, phân biệt rõ lỗi baseline và lỗi do thay đổi; không che giấu.

Thêm integration test FastAPI + DB cho toàn bộ API mới/sửa. Mock biên Google/NhatroVN/Facebook, nhưng dùng database thật của test và publisher contract thật. Nếu môi trường có credentials test do người dùng cung cấp, chạy smoke test live không phá dữ liệu; nếu không có, ghi rõ live E2E chưa chạy thay vì tuyên bố production verified.

### 10. Trình tự triển khai đề xuất

#### Phase 0 — Baseline và thiết kế chi tiết

- Đọc code và tài liệu liên quan.
- Vẽ state machine thực tế.
- Chạy baseline test/build.
- Chốt model/contract publisher và kế hoạch migration.

#### Phase 1 — Sửa false-success và publisher contract

- Refactor dispatch/result lifecycle.
- Thêm publication job/reconciliation.
- Test queue không phải success, callback và retry.

#### Phase 2 — Ổn định rental core

- Schema validation, ownership, config scoping.
- Upsert/source-status/rented cancellation.
- Matching, media, spacing/delay.
- Mirror outbox.

#### Phase 3 — Google Sheets source pipeline

- Campaign/source item/job/writeback models.
- Polling, validation, scheduling, media, idempotency.
- API và UI quản lý.

#### Phase 4 — Scheduler/concurrency/observability

- Claim locks, recovery, backoff, independent workers.
- Health/metrics/logging.

#### Phase 5 — Migration dữ liệu, regression và bàn giao

- Backfill dữ liệu cũ an toàn.
- Full backend test, lint, frontend build.
- Tóm tắt thay đổi, giới hạn và checklist smoke test live.

Có thể chia nhỏ hơn, nhưng không được đảo thứ tự khiến Google/rental tiếp tục dựa trên false-success.

### 11. Definition of Done

Chỉ được coi là hoàn thành khi:

- Google Sheets thực sự đọc dòng `READY`, tạo job, đăng theo lịch và ghi kết quả ngược.
- Rental cập nhật trạng thái nguồn, không đăng phòng đã thuê và đăng được ảnh.
- Không luồng nào đánh dấu `posted` khi mới enqueue.
- `post-now` được scope đúng config/user.
- Mọi liên kết Sheet/target có ownership validation.
- Retry dựa trên kết quả cuối và không tạo đăng trùng khi restart/concurrent.
- Mirror/write-back lỗi có thể phục hồi mà không mất dữ liệu hoặc đăng lại.
- `facebook_url` là URL thật; run/task ID không giả làm URL.
- Full backend suite pass.
- Frontend lint/build pass hoặc có báo cáo baseline chính xác.
- Migration được test.
- Có test mới chứng minh từng lỗi đã phát hiện không tái diễn.
- Có hướng dẫn cấu hình Google Sheet mẫu, service account, NhatroVN và checklist smoke test.
- Báo cáo cuối liệt kê file thay đổi, migration, API mới/đổi, test đã chạy, kết quả và phần live integration chưa thể xác minh.

Không được dùng các workaround sau:

- `try/except Exception: pass`.
- Đánh dấu success ngay sau enqueue.
- Sleep dài trong request HTTP.
- Chỉ dựa vào in-memory lock cho môi trường nhiều instance.
- Retry vô hạn.
- Dùng mock result để ghi `posted` trong production.
- Bỏ ảnh âm thầm rồi đăng text.
- Nuốt lỗi sync và trả 200 như thành công.
- Truy cập resource chỉ bằng UUID mà không lọc owner.

Hãy bắt đầu bằng baseline audit ngắn, sau đó triển khai liên tục theo phase. Khi gặp giới hạn cần credentials/dịch vụ thật, tiếp tục hoàn thành toàn bộ phần có thể kiểm chứng cục bộ và chỉ ghi rõ phần smoke test live đang bị chặn.

## KẾT THÚC PROMPT

