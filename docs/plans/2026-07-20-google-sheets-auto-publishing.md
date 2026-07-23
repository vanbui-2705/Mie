# Kế hoạch Google Sheets Auto Publishing

**Ngày lập:** 2026-07-20  
**Dự án:** FlowMeta Web Tool  
**Nhánh mục tiêu:** `dev-web-tool`  
**Trạng thái:** Sẵn sàng để phân rã thành task triển khai

## 1. Mục tiêu

Xây dựng chức năng cho phép người dùng nhập hoặc quản lý nội dung trong Google Sheets, sau đó FlowMeta tự động:

1. Đồng bộ các dòng đã sẵn sàng.
2. Kiểm tra và chuẩn hóa nội dung/media.
3. Chống nhận hoặc đăng trùng.
4. Xác định thời gian đăng theo từng dòng hoặc lịch cấu hình sẵn.
5. Phân phối bài tới Page, Group và trang cá nhân Facebook đã kết nối.
6. Ghi trạng thái, lỗi và link bài Facebook ngược về Google Sheets.

Google Sheets chỉ đóng vai trò nguồn nhập liệu và bảng theo dõi. PostgreSQL là nguồn trạng thái chính của hàng đợi để bảo đảm không mất hoặc đăng lặp bài khi backend khởi động lại.

## 2. Phạm vi MVP

### Bao gồm

- Kết nối một hoặc nhiều Google Sheets bằng service account.
- Đọc nội dung, link và nhiều ảnh/video từ Sheet.
- Chọn Page, Group và trang cá nhân làm đích mặc định cho từng chiến dịch.
- Hỗ trợ ba chế độ thời gian: `EXACT`, `AUTO`, `NOW`.
- Lịch theo múi giờ `Asia/Ho_Chi_Minh`.
- Chống trùng bằng `external_id` và content hash.
- Một bài có thể tạo nhiều job, mỗi job tương ứng một đích Facebook.
- Lưu kết quả độc lập theo từng đích.
- Ghi trạng thái và link kết quả ngược về Sheet.
- Retry có giới hạn và có log lỗi.
- Giao diện quản lý kết nối, chiến dịch và hàng đợi.

### Chưa bao gồm

- AI viết lại nội dung.
- Tự động đọc website phòng trọ.
- Nguồn Telegram hoặc Zalo.
- Đồng bộ sửa nội dung Facebook sau khi bài đã đăng.
- Tự động xóa bài Facebook đã hết hạn.
- Phân tích hiệu suất hoặc tương tác bài đăng.

## 3. Luồng tổng thể

```text
Người dùng thêm bài vào Google Sheets
                    ↓
Backend quét Sheet mỗi 30–60 giây
                    ↓
Kiểm tra status=READY và validate dữ liệu
                    ↓
Tải media + chuẩn hóa + chống trùng
                    ↓
Xác định thời gian đăng
    ┌───────────────┴────────────────┐
    ↓                                ↓
publish_at trong từng dòng    Khung giờ cấu hình sẵn
    └───────────────┬────────────────┘
                    ↓
Tạo publication job cho từng đích
                    ↓
Đến giờ → gọi publisher Facebook hiện có
                    ↓
Ghi kết quả và link Facebook về Sheet
```

## 4. Cấu trúc Google Sheets

Tên Sheet mặc định: `Posts`.

| Cột | Tên | Bắt buộc | Ý nghĩa |
|---|---|---:|---|
| A | `external_id` | Có | Mã duy nhất do người dùng cung cấp, ví dụ `PT-0001` |
| B | `content` | Tùy media | Nội dung bài đăng |
| C | `media_urls` | Không | Link ảnh/video, mỗi link một dòng |
| D | `link` | Không | Link đính kèm |
| E | `targets` | Không | Danh sách đích riêng; để trống sẽ dùng đích chiến dịch |
| F | `schedule_mode` | Không | `EXACT`, `AUTO` hoặc `NOW`; để trống dùng mặc định chiến dịch |
| G | `publish_at` | Với `EXACT` | Thời gian đăng cụ thể |
| H | `priority` | Không | Độ ưu tiên, mặc định `0` |
| I | `status` | Có | Trạng thái điều khiển và kết quả |
| J | `facebook_urls` | Hệ thống ghi | Danh sách link bài đăng thành công |
| K | `result` | Hệ thống ghi | Tóm tắt số đích thành công/thất bại |
| L | `error` | Hệ thống ghi | Lỗi đồng bộ hoặc đăng bài |
| M | `queued_at` | Hệ thống ghi | Thời điểm backend nhận bài |
| N | `posted_at` | Hệ thống ghi | Thời điểm hoàn thành |

Ví dụ:

| external_id | content | media_urls | schedule_mode | publish_at | status |
|---|---|---|---|---|---|
| PT-0001 | Phòng trọ Quận 7... | URL ảnh | EXACT | 2026-07-21 09:30 | READY |
| PT-0002 | Phòng mới gần đại học... | URL ảnh | AUTO | | READY |
| PT-0003 | Nội dung cần đăng ngay | | NOW | | READY |

Chỉ những dòng có `status=READY` mới được backend tiếp nhận.

## 5. Chế độ thời gian

### 5.1. `EXACT` — thời gian riêng từng dòng

```text
schedule_mode = EXACT
publish_at = 2026-07-21 19:30
```

Quy tắc:

- Thời gian được diễn giải theo múi giờ chiến dịch, mặc định `Asia/Ho_Chi_Minh`.
- Nếu thời gian đã qua, chiến dịch có thể chọn `đăng bù ngay` hoặc `đánh dấu MISSED`.
- Dòng chỉ được xếp lịch một lần cho cùng phiên bản nội dung.
- Người dùng có thể sửa thời gian khi dòng còn `READY`.
- Khi dòng đã `QUEUED`, muốn thay đổi phải hủy job hoặc đưa dòng về quy trình chỉnh sửa được hỗ trợ trên giao diện.

### 5.2. `AUTO` — dùng khung giờ cấu hình sẵn

Ví dụ cấu hình:

```text
Ngày chạy: Thứ 2–Chủ nhật
Khung giờ: 08:00, 11:30, 17:30, 20:30
Tối đa: 4 bài/ngày
Khoảng cách tối thiểu: 90 phút
Random: ±10 phút
Múi giờ: Asia/Ho_Chi_Minh
```

Backend sẽ gán bài vào slot trống gần nhất theo `priority`, sau đó theo thời điểm nhận bài.

### 5.3. `NOW` — đăng sớm nhất có thể

- Job được đưa vào hàng đợi ngay sau khi validate thành công.
- Vẫn áp dụng giới hạn tốc độ, delay giữa các đích và trạng thái sẵn sàng của tài khoản Facebook.
- `NOW` không có nghĩa là bỏ qua hàng đợi hoặc chạy song song không giới hạn.

## 6. Đích đăng

Mỗi chiến dịch có danh sách đích mặc định được chọn bằng checkbox trên giao diện:

- Trang cá nhân.
- Fanpage.
- Group.

Cột `targets` có thể ghi đè danh sách mặc định của riêng một dòng.

Định dạng nội bộ:

```text
page:<page_id>,group:<group_id>,personal:<account_id>
```

Một bài và bốn đích sẽ tạo bốn `publication_jobs`. Kết quả được lưu độc lập để hỗ trợ trạng thái thành công một phần.

## 7. Vòng đời trạng thái

```text
DRAFT
  ↓ người dùng đổi status trong Sheet
READY
  ↓ backend nhận và validate
QUEUED
  ↓ đến thời gian
POSTING
  ├── POSTED
  ├── PARTIAL
  ├── FAILED
  └── CANCELED
```

Các trạng thái bổ sung:

- `INVALID`: dữ liệu không hợp lệ hoặc thiếu nội dung bắt buộc.
- `DUPLICATE`: trùng `external_id` hoặc vi phạm quy tắc chống trùng.
- `MISSED`: thời gian đã qua và chiến dịch không cho đăng bù.
- `RETRYING`: một hoặc nhiều job đang chờ thử lại.

Quy tắc tổng hợp:

- Tất cả đích thành công → `POSTED`.
- Một phần thành công, một phần lỗi/chờ duyệt → `PARTIAL`.
- Tất cả đích thất bại sau khi hết retry → `FAILED`.
- Group trả về trạng thái chờ quản trị viên duyệt phải được lưu riêng, không coi là đăng thất bại kỹ thuật.

## 8. Kiến trúc dữ liệu

### 8.1. `google_sheet_connections`

- `id`
- `user_id`
- `name`
- `spreadsheet_id`
- `sheet_name`
- `credentials_enc`
- `poll_interval_seconds`
- `timezone`
- `status`
- `last_synced_at`
- `last_error`
- `created_at`
- `updated_at`

### 8.2. `sheet_campaigns`

- `id`
- `user_id`
- `connection_id`
- `name`
- `default_targets_json`
- `default_schedule_mode`
- `schedule_slots_json`
- `active_weekdays_json`
- `timezone`
- `max_posts_per_day`
- `min_post_gap_seconds`
- `target_delay_min_seconds`
- `target_delay_max_seconds`
- `late_policy`
- `max_retries`
- `enabled`
- `created_at`
- `updated_at`

### 8.3. `sheet_source_items`

- `id`
- `user_id`
- `connection_id`
- `campaign_id`
- `external_id`
- `sheet_row_number`
- `content`
- `link`
- `media_urls_json`
- `targets_json`
- `schedule_mode`
- `requested_publish_at`
- `content_hash`
- `source_version`
- `status`
- `validation_error`
- `queued_at`
- `completed_at`
- `created_at`
- `updated_at`

Khóa duy nhất:

```text
connection_id + sheet_name + external_id
```

### 8.4. `publication_jobs`

- `id`
- `user_id`
- `source_item_id`
- `target_type`
- `target_id`
- `scheduled_at`
- `status`
- `attempt_count`
- `max_attempts`
- `next_retry_at`
- `facebook_url`
- `facebook_post_id`
- `result_message`
- `error`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

Khóa chống đăng trùng:

```text
source_item_id + target_type + target_id
```

## 9. Đồng bộ Google Sheets

Worker chạy theo `poll_interval_seconds`, mặc định 60 giây.

Quy trình an toàn:

1. Khóa connection để một thời điểm chỉ có một tiến trình đồng bộ.
2. Đọc header và các dòng có `READY`.
3. Chuẩn hóa `external_id`, nội dung, thời gian và danh sách đích.
4. Validate dữ liệu và media.
5. Kiểm tra idempotency trong PostgreSQL.
6. Tạo hoặc cập nhật `sheet_source_item` hợp lệ.
7. Tính slot và tạo `publication_jobs`.
8. Commit transaction PostgreSQL.
9. Ghi `QUEUED`, `queued_at` và thời gian dự kiến về Sheet.
10. Lưu lỗi đồng bộ nếu thao tác ghi Sheet thất bại để worker thử lại mà không tạo job trùng.

Không được ghi `QUEUED` vào Sheet trước khi transaction database hoàn tất.

## 10. Media

MVP hỗ trợ:

- URL ảnh/video công khai.
- Google Drive file ID hoặc link được chia sẻ cho service account.
- Nhiều media, phân cách bằng xuống dòng.

Quy trình:

1. Chuẩn hóa URL hoặc Drive file ID.
2. Kiểm tra quyền truy cập.
3. Kiểm tra MIME type, phần mở rộng và dung lượng.
4. Tải media về vùng lưu trữ của backend.
5. Tính hash để tránh tải hoặc lưu trùng.
6. Lưu theo `user_id/source_item_id` để bảo đảm cách ly người dùng.
7. Chỉ tạo publication job sau khi media bắt buộc đã sẵn sàng.

Nếu chiến dịch yêu cầu ảnh nhưng media tải thất bại, dòng chuyển `INVALID` thay vì đăng bài thiếu ảnh.

## 11. Xác thực và bảo mật Google

MVP sử dụng service account:

1. Tạo Google Cloud project.
2. Bật Google Sheets API và Google Drive API.
3. Tạo service account.
4. Chia sẻ spreadsheet và thư mục media cho email service account.
5. Upload credentials vào FlowMeta.
6. Backend validate rồi mã hóa credentials trước khi lưu.

Yêu cầu bảo mật:

- Không ghi credentials hoặc access token vào log.
- Không trả credentials về frontend sau khi đã lưu.
- Phân quyền connection theo `user_id`.
- Chỉ yêu cầu scope tối thiểu cần thiết.
- Có chức năng thu hồi/xóa connection.
- Không lưu file credentials dạng rõ trong repository hoặc thư mục public.

OAuth Google có thể được bổ sung sau MVP để người dùng chọn Sheet trực tiếp.

## 12. Tái sử dụng hệ thống hiện có

Phần mới không xây lại Facebook publisher. Khi đến giờ, `publication_jobs` phải gọi lại tầng thực thi hiện có:

- Page dùng Graph publisher hiện có.
- Group và trang cá nhân dùng browser/extension worker hiện có.
- Target availability tiếp tục dùng API target hiện có.
- Log và TaskRun tiếp tục được tái sử dụng hoặc liên kết từ publication job.

`scheduled_posts` tiếp tục phục vụ lịch nội dung cố định do người dùng tạo thủ công. Nội dung động từ Sheet dùng `sheet_source_items` và `publication_jobs` để tránh trộn hai vòng đời khác nhau.

## 13. API dự kiến

### Connections

- `GET /api/google-sheets/connections`
- `POST /api/google-sheets/connections`
- `POST /api/google-sheets/connections/{id}/test`
- `POST /api/google-sheets/connections/{id}/sync`
- `DELETE /api/google-sheets/connections/{id}`

### Campaigns

- `GET /api/sheet-campaigns`
- `POST /api/sheet-campaigns`
- `GET /api/sheet-campaigns/{id}`
- `PUT /api/sheet-campaigns/{id}`
- `POST /api/sheet-campaigns/{id}/pause`
- `POST /api/sheet-campaigns/{id}/resume`
- `DELETE /api/sheet-campaigns/{id}`

### Source items và jobs

- `GET /api/sheet-source-items`
- `GET /api/sheet-source-items/{id}`
- `POST /api/sheet-source-items/{id}/publish-now`
- `POST /api/sheet-source-items/{id}/reschedule`
- `POST /api/sheet-source-items/{id}/cancel`
- `POST /api/sheet-source-items/{id}/retry`
- `GET /api/publication-jobs`

## 14. Giao diện

### 14.1. Trang “Nguồn Google Sheets”

- Thêm connection.
- Nhập spreadsheet URL và sheet name.
- Upload credentials.
- Kiểm tra kết nối.
- Xem trước header và 5 dòng.
- Đồng bộ ngay.
- Bật/tắt tự đồng bộ.
- Hiển thị lần đồng bộ và lỗi gần nhất.

### 14.2. Trang “Chiến dịch từ Sheet”

- Chọn connection.
- Chọn Page, Group và trang cá nhân.
- Chọn chế độ thời gian mặc định.
- Cấu hình khung giờ và ngày trong tuần.
- Giới hạn bài/ngày.
- Cấu hình delay giữa các đích.
- Cấu hình retry và chính sách đăng bù.
- Bật/tắt chiến dịch.

### 14.3. Trang “Hàng đợi”

- Preview nội dung và media.
- Hiển thị source row/external ID.
- Thời gian đăng.
- Danh sách đích và trạng thái từng đích.
- Đăng ngay.
- Đổi lịch.
- Hủy.
- Thử lại.
- Mở link Facebook sau khi thành công.

## 15. Kế hoạch triển khai

### Giai đoạn 1 — Google Sheets connection

**Công việc:**

- Thêm dependency Google API cần thiết.
- Thêm model và migration cho connection.
- Mã hóa/lưu credentials.
- Service đọc spreadsheet metadata, header và preview.
- API CRUD/test connection.
- Giao diện quản lý nguồn.
- Tạo file Google Sheets template mẫu.

**Kiểm thử:**

- Credentials hợp lệ và không hợp lệ.
- Sheet không tồn tại.
- Thiếu quyền đọc hoặc ghi.
- Header sai hoặc thiếu.
- Nội dung tiếng Việt và ký tự đặc biệt.
- Cách ly dữ liệu nhiều người dùng.

### Giai đoạn 2 — Đồng bộ và chống trùng

**Công việc:**

- Model/migration cho campaign và source item.
- Polling worker.
- Header mapping và row parser.
- Validation.
- Idempotency theo `external_id`.
- Content hash.
- Ghi trạng thái về Sheet.
- Đồng bộ thủ công và tự động.

**Kiểm thử:**

- Đồng bộ một dòng nhiều lần không tạo bản ghi trùng.
- Hai worker cùng chạy không tạo job trùng.
- Sheet thay đổi trong lúc đồng bộ.
- Google API timeout/quota/error.
- Backend restart giữa quá trình đồng bộ.

### Giai đoạn 3 — Scheduler và publication jobs

**Công việc:**

- Model/migration cho `publication_jobs`.
- Bộ tính lịch `EXACT`, `AUTO`, `NOW`.
- Slot theo ngày trong tuần.
- Giới hạn bài/ngày.
- Random delay và delay giữa các đích.
- Late policy.
- Worker lấy job đến hạn.

**Kiểm thử:**

- Slot đầy và chuyển sang ngày kế tiếp.
- Thời gian đã qua.
- Múi giờ Việt Nam.
- Ngày bị vô hiệu hóa.
- Nhiều bài có cùng priority.
- Restart trước và sau thời điểm job đến hạn.

### Giai đoạn 4 — Facebook execution

**Công việc:**

- Adapter gọi publisher Page/Group/personal hiện có.
- Tạo TaskRun/log liên quan.
- Lưu kết quả từng target.
- Retry có giới hạn.
- Tổng hợp trạng thái source item.
- Ghi Facebook URL, result và error về Sheet.

**Kiểm thử:**

- Một bài nhiều đích.
- Thành công toàn bộ.
- Thành công một phần.
- Browser profile hết session.
- Group yêu cầu duyệt.
- Worker bị dừng sau khi Facebook đã đăng nhưng trước khi ghi kết quả.
- Job đã thành công không bị đăng lại.

### Giai đoạn 5 — Hàng đợi và vận hành

**Công việc:**

- Giao diện campaign.
- Giao diện hàng đợi.
- Hành động publish now/reschedule/cancel/retry.
- Cảnh báo lỗi Google và Facebook.
- Lịch sử đồng bộ.
- Thống kê tổng quan.
- Tài liệu cấu hình/deploy.

**Kiểm thử:**

- Phân quyền frontend/backend.
- Luồng thao tác đầy đủ từ Sheet đến Facebook.
- Trạng thái cập nhật theo thời gian thực hoặc polling.
- Khả năng phục hồi sau khi các service restart.

## 16. Tiêu chí nghiệm thu MVP

- Dòng `READY` được nhận trong tối đa 60 giây với cấu hình mặc định.
- Một `external_id` không bị đăng hai lần vào cùng một đích.
- Thời gian đăng chính xác theo múi giờ chiến dịch.
- Backend restart không làm mất hoặc lặp job.
- Kết quả từng Page, Group và profile được lưu độc lập.
- Sheet nhận được `POSTED`, `PARTIAL`, `FAILED` hoặc trạng thái phù hợp.
- Link bài Facebook thành công được ghi ngược về Sheet.
- Media lỗi không làm đăng bài thiếu dữ liệu bắt buộc.
- Mất kết nối Google không ảnh hưởng các job đã lưu trong PostgreSQL.
- Người dùng có thể tạm dừng toàn bộ campaign từ giao diện.
- Credentials Google không xuất hiện trong API response hoặc log.
- Test backend, integration và frontend liên quan đều đạt.

## 17. Rủi ro và phương án xử lý

| Rủi ro | Phương án |
|---|---|
| Google API quota hoặc timeout | Batch read/write, retry có backoff, tăng poll interval |
| Hai worker xử lý cùng dòng | DB unique constraint + transaction + distributed lock |
| Sheet báo `QUEUED` nhưng DB chưa có job | Chỉ ghi Sheet sau khi commit database |
| DB có job nhưng ghi Sheet thất bại | Retry việc đồng bộ kết quả, không tạo lại job |
| Link Drive không tải trực tiếp được | Dùng Drive API với service account |
| Facebook đăng thành công nhưng worker mất kết nối | Lưu idempotency, đối chiếu kết quả trước khi retry nếu có thể |
| Browser profile hết đăng nhập | Chuyển job sang lỗi cần thao tác và cảnh báo người dùng |
| Một đích lỗi làm sai trạng thái cả bài | Lưu kết quả từng publication job và tổng hợp `PARTIAL` |
| Người dùng sửa dòng sau khi đã queue | Khóa theo source version; yêu cầu reschedule/cancel qua UI |

## 18. Thứ tự ưu tiên

1. Connection và template Sheet.
2. Đồng bộ `READY` an toàn, chống trùng.
3. Lập lịch `EXACT` và `NOW`.
4. Kết nối publisher hiện có.
5. Ghi kết quả về Sheet.
6. Lịch `AUTO` nâng cao.
7. Giao diện vận hành đầy đủ.
8. Tối ưu quota, thống kê và cảnh báo.

Không triển khai AI, Telegram, Zalo hoặc website collector trước khi luồng Sheet → PostgreSQL → Facebook → Sheet đạt đủ tiêu chí nghiệm thu.
