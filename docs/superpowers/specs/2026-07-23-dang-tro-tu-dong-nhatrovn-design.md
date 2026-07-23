# Thiết kế: Đăng trọ tự động từ nhatrovn → Facebook

- **Ngày:** 2026-07-23
- **Nhánh:** dev-web-tool
- **Trạng thái:** Đã duyệt thiết kế, chuẩn bị lập kế hoạch triển khai

## 1. Mục tiêu

Tự động lấy tin phòng trọ của công ty từ cổng quản lý nhatrovn theo **khu vực đã chọn**, đưa vào hệ thống, rồi **tự động đăng lên các nhóm Facebook có tên khớp địa điểm** (theo Quận/Huyện), với nhịp giãn cách an toàn. Có **trang quản trị riêng** cho tính năng này; dữ liệu lưu trong DB và **đồng bộ ra Google Sheet** để tiện xem/sửa.

Hai yêu cầu gốc của người dùng được gộp thành **một luồng duy nhất**:
1. Hoàn thiện chức năng đọc Google Sheet để đăng bài.
2. Lấy thông tin trọ từ website công ty để đăng.

## 2. Hiện trạng (đã có sẵn, tái dùng)

- **Pipeline đăng bài hoàn chỉnh:** `ScheduledPost` + `ScheduledPostService` + `enqueue_due_posts` (`backend/app/services/scheduled_post_service.py`) đăng lên page/group/personal qua `_run_page_post_task`, hỗ trợ xoay vòng nhiều nội dung. → Tái dùng để đăng.
- **Bảng nhóm FB:** `FacebookGroup` (`group_id`, `group_name`, `group_url` theo user) + API liệt kê nhóm (`page_tasks.py`). → Dùng để khớp nhóm theo tên.
- **Google Sheets service:** `backend/app/services/google_sheets.py` — service-account, đọc header/preview, có scope **ghi** (`spreadsheets`). Model `GoogleSheetConnection` có sẵn `poll_interval_seconds`, `last_synced_at`, `timezone`. → Tái dùng để đồng bộ ra Sheet (hiện mới đọc, chưa ghi).
- **Bộ mã hoá bí mật:** `app/crypto.py` (`encrypt`/`decrypt`, Fernet). → Dùng cho credential nhatrovn.
- **Vòng lặp scheduler:** `_scheduler_tick()` trong `app/main.py` chạy mỗi 60s gọi `enqueue_due_posts()`. → Chỗ móc các worker mới.

**Khoảng trống cần lấp:** chưa có nguồn nội dung nào đổ vào pipeline; `poll_interval_seconds`/`last_synced_at` chưa được dùng; chưa ghi ngược ra Sheet.

## 3. Kết quả khảo sát nhatrovn (đã xác minh qua trình duyệt)

- Cổng `quanly.nhatrovn.vn/main/room-sale/init` là app **jQuery + render HTML phía server** (KendoUI, jquery.tmpl…), **không có API JSON sạch**.
- **Đăng nhập:** form login → **session cookie** (cần xác minh có OTP/captcha không khi triển khai).
- **Lấy dữ liệu:** `POST /main/room-sale/search` với form params (`page`, bộ lọc Tỉnh/Quận/Phường/giá…) → **trả về HTML** (~44KB), không phải JSON.
- **Cấu trúc thẻ phòng:** container `div.row` → mỗi phòng là `div.col-md-6.col-lg-6.col-xlg-4 > div.card.card-body.p-2` (≈20 thẻ/trang). Trong thẻ có: mã phòng/tiêu đề, địa chỉ, giá cho thuê, cọc, điện/nước, diện tích, tiện ích, khu vực xung quanh, trạng thái (Trống).
- **Bộ lọc khu vực** có sẵn trên UI: Tỉnh/Thành phố → Quận/Huyện → Phường/Xã.

**Hệ quả:** adapter phải **đăng nhập + POST search + parse HTML** (không phải gọi JSON). Ổn định hơn trang marketing công khai nhưng vẫn phụ thuộc cấu trúc HTML → **cô lập phần parse** vào một chỗ, có test so mẫu.

## 4. Quyết định thiết kế (đã chốt với người dùng)

| Chủ đề | Quyết định |
|--------|-----------|
| Luồng tổng thể | nhatrovn → DB (nguồn sự thật) → tự đăng; đồng bộ song song ra Google Sheet |
| Duyệt trước khi đăng | **Tự động đăng**, không bắt duyệt tay; có van an toàn (độ trễ + trạng thái `bỏ qua`) |
| Nhịp đăng | **Giãn cách đều** N phút / mỗi lượt (1 phòng × 1 nhóm = 1 lượt) |
| Nơi đăng | **Nhóm khớp theo Quận/Huyện** (không dùng danh sách nhóm cố định) |
| Không khớp nhóm | **Để người dùng gán tay** trên trang trọ (trạng thái `chờ gán nhóm`) |
| Phạm vi khu vực | **Mỗi khu vực = một cấu hình riêng** |
| Lấy dữ liệu | Đăng nhập cổng + parse HTML `POST /main/room-sale/search` |
| Lưu credential cổng | **User/mật khẩu, mã hoá** (Fernet) — worker tự đăng nhập |
| Caption | Mẫu có sẵn + emoji + **hashtag khu vực tự sinh**; sửa được |
| UI | **Trang riêng** "Đăng trọ tự động" trong frontend |
| Google Sheet | **Giữ cả hai** — DB là chính, mirror ra Sheet để xem/sửa |

## 5. Kiến trúc

```
┌────────────────────┐  (1) login + POST search + parse HTML
│  quanly.nhatrovn   │ ─────────────────────────────────────┐
└────────────────────┘                                       ▼
                                              ┌───────────────────────────┐
                                              │  NhatrovnAdapter          │
                                              │  → Room{...}              │
                                              └───────────┬───────────────┘
                                                          │ (2) dedup + lưu
                                                          ▼
┌────────────────────┐  (mirror 2 chiều xem/sửa)  ┌───────────────────────┐
│  Google Sheet      │ ◄─────────────────────────►│  DB: RentalRoom       │  ◄── nguồn sự thật
└────────────────────┘                            │  (per RentalConfig)   │
                                                  └───────┬───────────────┘
                                (3) khớp nhóm theo Quận/Huyện │
                                     (FacebookGroup.group_name)│
                                                          ▼
                                              ┌───────────────────────────┐
                    (4) tự đăng giãn cách N/lượt│  PostWorker → tái dùng    │
   Facebook groups ◄───────────────────────────│  _run_page_post_task      │
                                              └───────────────────────────┘

           Trang "Đăng trọ tự động" (frontend): cấu hình khu vực, xem phòng,
           gán nhóm tay, theo dõi trạng thái. DB ↔ page ↔ Sheet.
```

**Ranh giới các thành phần (mỗi cái một việc, test độc lập):**
- `NhatrovnAdapter` chỉ biết nhatrovn (login/search/parse), không biết DB/Sheet/FB.
- `GroupMatcher` chỉ khớp tên quận ↔ `FacebookGroup`, không biết nhatrovn/FB.
- `SyncWorker`/`PostWorker` điều phối, không chứa logic đăng bài (đẩy vào pipeline sẵn có).
- Frontend chỉ gọi API, không chứa logic nghiệp vụ.

## 6. Mô hình dữ liệu (Alembic migration mới)

### `rental_configs` — mỗi khu vực một cấu hình
| Cột | Kiểu | Ghi chú |
|-----|------|---------|
| id | UUID PK | |
| user_id | UUID FK users | cascade |
| name | str | nhãn (vd "Trọ Gò Vấp") |
| source_type | str | `"nhatrovn"` |
| source_credentials_enc | text | user/mật khẩu cổng, mã hoá Fernet |
| province_code / province_name | str | khu vực chọn |
| district_code / district_name | str | dùng cho search **và** khớp nhóm |
| ward_code / ward_name | str, nullable | tuỳ chọn |
| extra_filters_json | text, nullable | giá, loại phòng… (form params search) |
| auto_post | bool = true | công tắc tự đăng / chờ duyệt |
| post_spacing_seconds | int | giãn cách mỗi lượt (mặc định vd 480s) |
| post_delay_seconds | int = 0 | chờ sau khi sync mới cho đăng |
| caption_template | text | mẫu caption |
| contact_phone | str | cho caption |
| group_match_level | str = `"district"` | cấp khớp nhóm |
| poll_interval_seconds | int | tần suất sync (tái dùng ràng buộc 30–3600) |
| timezone | str = `Asia/Ho_Chi_Minh` | |
| google_sheet_connection_id | UUID FK, nullable | mirror ra Sheet (tuỳ chọn) |
| status | str | `active` / `paused` / `error` |
| last_synced_at / last_post_at | datetime, nullable | bookkeeping throttle |
| last_error | text, nullable | |
| created_at / updated_at | datetime | |

### `rental_rooms` — mỗi phòng một dòng
| Cột | Kiểu | Ghi chú |
|-----|------|---------|
| id | UUID PK | |
| config_id | UUID FK rental_configs | cascade |
| user_id | UUID FK users | |
| external_room_id | str | **khoá dedup** (ID/link phòng từ nhatrovn) |
| title / price / area_text / address | str | dữ liệu bóc từ HTML |
| district / ward | str, nullable | dùng khớp nhóm |
| description | text | |
| images_json | text | danh sách URL ảnh |
| caption | text | sinh từ template, **sửa được** |
| matched_group_ids_json | text, nullable | nhóm đã khớp/gán |
| status | str | `new` · `waiting_groups` · `posting` · `posted` · `error` · `skipped` |
| post_urls_json | text, nullable | link bài đã đăng theo nhóm |
| posted_at | datetime, nullable | |
| retry_count | int = 0 | |
| error | text, nullable | |
| created_at / updated_at | datetime | |

`UniqueConstraint(config_id, external_room_id)` chống trùng.

> Ghi chú: có thể tái dùng/nới `GoogleSheetConnection` cho phần mirror thay vì FK riêng — quyết định lúc lập kế hoạch. Bản thiết kế ưu tiên bảng riêng cho rõ ràng.

## 7. Thành phần chi tiết

### 7.1 `NhatrovnAdapter` (`app/services/nhatrovn_adapter.py`)
- `login(credentials) -> session` — POST form login, giữ cookie (dùng `httpx.AsyncClient` có cookie jar). Xử lý lỗi sai mật khẩu; **phát hiện** nếu gặp OTP/captcha → báo lỗi rõ ràng để người dùng xử lý.
- `fetch_rooms(session, filters) -> list[Room]` — `POST /main/room-sale/search` theo `province/district/ward/page`, lặp phân trang tới hết.
- `parse_rooms(html) -> list[Room]` — **cô lập selector** ở đây: `div.col-xlg-4 .card.card-body` → bóc `external_room_id`, title, price, area, address, district, ward, description, images. Chuẩn hoá số (giá, diện tích).
- **Bước triển khai #1 (bắt buộc, làm trước):** dùng trình duyệt đăng nhập thật, bắt đúng **form params của `/search`** và **selector từng trường** từ HTML thật, ghi lại vào adapter + test cố định (fixture HTML).

### 7.2 `SyncWorker` (`app/services/rental_sync.py`)
- Với mỗi `rental_config` tới hạn (`now - last_synced_at >= poll_interval`): gọi adapter → so `external_room_id` với `rental_rooms` → **chỉ thêm phòng mới** (status `new`, sinh caption). Cập nhật `last_synced_at`. Không sửa dòng cũ.
- Nếu có `google_sheet_connection_id`: **append phòng mới ra Google Sheet** (dùng google_sheets service, thêm hàm ghi `values.append`).

### 7.3 `GroupMatcher` (`app/services/rental_group_match.py`)
- `match(district_name, user_groups) -> list[group_id]`: chuẩn hoá (bỏ dấu, lowercase, bỏ tiền tố "Quận"/"Huyện") rồi so **contains** với `FacebookGroup.group_name` đã chuẩn hoá.
- Gọi khi sync xong mỗi phòng: có nhóm → gán `matched_group_ids_json`, status giữ `new`; **không có nhóm → status `waiting_groups`** (chờ người dùng gán tay).

### 7.4 `PostWorker` (`app/services/rental_post.py`)
- Với mỗi config: nếu `auto_post` và đã đủ `post_spacing_seconds` kể từ `last_post_at`, và đã qua `post_delay_seconds` kể từ khi phòng được thêm:
  - Lấy **một lượt** (phòng `new` cũ nhất × một nhóm chưa đăng) → đánh dấu `posting` (chống đăng đôi khi restart) → tạo `TaskRun` + gọi `_run_page_post_task` (target `group:<id>`) → ghi `post_urls_json`, khi hết nhóm thì `posted` + `posted_at`. Cập nhật `last_post_at`.
  - Lỗi → `error` + `error`, `retry_count++`, thử lại tới `max_retries` rồi dừng chờ xem.
  - Ghi ngược trạng thái ra Google Sheet (nếu có mirror).
- **Giãn cách áp cho từng lượt (1 phòng × 1 nhóm)** để tránh đăng trùng nội dung nhiều nhóm dồn dập.

### 7.5 Nối dây scheduler (`app/main.py`)
Trong `_scheduler_tick()` thêm (bọc try/except riêng, không làm chết vòng lặp):
```
await run_rental_sync()     # sync + match, tôn trọng poll_interval
await run_rental_posting()  # đăng giãn cách, tôn trọng last_post_at
```

### 7.6 API + Trang frontend "Đăng trọ tự động"
- **Router mới** `app/routers/rental.py` (RBAC như google_sheets): CRUD `rental_configs`, list `rental_rooms` theo config, `test-login`, `sync-now`, `post-now`, `assign-groups` (gán tay), `skip-room`, `retry-room`.
- **Trang mới** trong `frontend/src/app/...` + link ở `SideNav`. Gồm:
  - Danh sách/khởi tạo cấu hình: đăng nhập nhatrovn, **chọn khu vực** (Tỉnh→Quận→Phường), nhịp giãn cách, caption+hashtag, bật/tắt auto-post, chọn Google Sheet mirror (tuỳ chọn).
  - **Bảng phòng**: trạng thái từng phòng, nút **gán nhóm tay** cho phòng `waiting_groups`, nút bỏ qua / thử lại, link bài đã đăng.
- Danh sách Tỉnh/Quận/Phường: lấy từ nhatrovn hoặc dùng bảng đơn vị hành chính VN (quyết định lúc triển khai).

### 7.7 Caption mặc định
```
🏠 {title}
💰 Giá: {price}   📐 {area_text}
📍 {address}

{description}

📞 Liên hệ: {contact_phone}
#thuetro #phongtro #nhatro #chothuephongtro #{district_slug}
```
`#{district_slug}` sinh từ Quận/Huyện (bỏ dấu, vd `#GoVap`). Người dùng sửa được trong `caption`/`caption_template`.

## 8. Xử lý lỗi & an toàn

- Mỗi worker bọc try/except riêng theo config; lỗi 1 config không làm chết scheduler; ghi `last_error`, đặt `status="error"`, thử lại lần sau (backoff).
- Login cổng lỗi / gặp OTP/captcha → báo lỗi rõ, dừng config đó, không retry mù.
- HTML đổi cấu trúc → parse trả rỗng/thiếu → log cảnh báo + test mẫu bắt sớm.
- **Chống trùng:** `UniqueConstraint(config_id, external_room_id)`.
- **Chống đăng đôi:** chuyển `new → posting` trước khi gọi đăng; chỉ `posted` sau khi xong.
- **Phanh an toàn:** throttle giãn cách; `status="paused"` cho config = tắt khẩn cấp; `post_delay_seconds` để có cửa sổ can thiệp; trạng thái `skipped`.
- **Bí mật:** credential cổng + Google service-account mã hoá Fernet khi lưu; không log ra ngoài.
- **Tôn trọng tài khoản FB:** giãn cách mỗi lượt để giảm rủi ro bị gắn cờ spam.

## 9. Kiểm thử (pytest — backend đã có sẵn)

- **Adapter/parse:** fixture HTML thật (lưu từ bước #1) → test bóc đúng các trường, phân trang, chuẩn hoá số; test login (mock httpx) thành công/sai mật khẩu/gặp captcha.
- **GroupMatcher:** chuẩn hoá dấu + contains; khớp/không khớp; nhiều nhóm cùng quận.
- **SyncWorker:** dedup (chỉ thêm phòng mới), sinh caption, cập nhật `last_synced_at`.
- **PostWorker:** throttle giãn cách, chuyển trạng thái, chống đăng đôi, giới hạn thử lại, ghi ngược.
- **Sheet mirror:** ghi append + cập nhật trạng thái (mock google_sheets).
- **API:** CRUD config, gán nhóm tay, sync-now/post-now (integration với DB như test hiện có).

## 10. Rủi ro & giả định

- **Giả định:** cổng nhatrovn đăng nhập chỉ bằng user/mật khẩu (không OTP/captcha). *Cần xác minh ở bước #1.* Nếu có OTP/captcha → chuyển sang phương án "dán cookie/token định kỳ".
- **Rủi ro:** nhatrovn đổi giao diện thẻ phòng → parse hỏng. Giảm thiểu: cô lập selector + test fixture + cảnh báo khi parse rỗng.
- **Rủi ro:** đăng nhiều nhóm nhanh → FB gắn cờ. Giảm thiểu: giãn cách mỗi lượt, giới hạn.
- **Giả định:** nhóm FB đã được nạp vào `FacebookGroup` với `group_name` đúng để khớp. Nếu tên nhóm không chứa tên quận → rơi vào `waiting_groups` (gán tay).

## 11. Việc cần làm trước khi/khi triển khai (đưa vào plan)

1. **(Trước tiên)** Bắt form params `/search` + selector HTML thật qua trình duyệt; lưu fixture.
2. Xác minh luồng đăng nhập cổng (OTP/captcha?).
3. Quyết định nguồn danh sách Tỉnh/Quận/Phường cho UI.
4. Alembic migration cho `rental_configs` + `rental_rooms`.
5. Bổ sung hàm **ghi** vào google_sheets service (append + update ô).
