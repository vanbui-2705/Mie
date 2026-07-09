# Hướng dẫn chuyển từ FlowMeta WinForms sang FlowMeta Web

> Phiên bản: 1.0 — Ngày: 2026-07-06

---

## 1. Những gì đã thay đổi

| Mặt | Trước (WinForms) | Bây giờ (Web) |
|-----|-------------------|----------------|
| Cài đặt | `.exe` ClickOnce / MSI | `docker compose up` |
| Dữ liệu | File `settings.dpapi` (encrypted, user-specific) | PostgreSQL + Redis (container-local hoặc volume) |
| License | RSA + DPAPI, kích hoạt máy | Không cần — open usage, single-user |
| Mật khẩu/token | Lưu trong file DPAPI trên máy | Lưu trong PostgreSQL, mã hóa Fernet |
| Proxy | KiotProxy vẫn giữ nguyên | KiotProxy vẫn giết nguyên logic round-robin |
| Graph API | v19.0 | v19.0 (giữ nguyên) |
| UI | WinForms GDI+ | Next.js 16 + Frost theme |
| Trình duyệt | Không cần | Chrome / Edge / Firefox, min-width 1180px |

---

## 2. Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|------------|---------|
| Docker + Docker Compose | phiên bản mới nhất (v26+) |
| RAM | tối thiểu 4 GB (khuyến nghị 8 GB) |
| Disk | 2 GB trống |
| Trình duyệt | Chrome / Edge / Firefox, màn hình độ phân giải từ 1280px trở lên |
| Mạng | Cần kết nối internet để gọi Facebook Graph API + KiotProxy |

---

## 3. Cách chạy (3 bước)

### Bước 1 — Clone hoặc giải nén

```bash
# Giải nén file nén hoặc clone repo
cd FlowMeta
```

### Bước 2 — Tạo file `.env`

```bash
cp .env.example .env
```

Mở `.env` và điền các biến bắt buộc:

| Biến | Mô tả | Bắt buộc |
|------|-------|----------|
| `FERNET_KEY` | Chuỗi mã hóa Fernet (sinh bằng Python: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) | Có |
| `FLOWMETA_TOKEN_SECRET` | Secret cho HMAC bearer token (ví dụ: `dev-secret` cho local) | Có |
| `POSTGRES_PASSWORD` | Mật khẩu PostgreSQL | Có |
| `CORS_ORIGINS` | Origin cho CORS (ví dụ: `http://localhost:3000`) | Có nếu khác mặc định |

### Bước 3 — Khởi động

```bash
docker compose up --build
```

Sau khi khởi động xong (mất ~30-60 giây cho lần đầu):

- **Frontend**: mở <http://localhost:3000>
- **Backend API**: <http://localhost:8000>
- **API Docs**: <http://localhost:8000/docs>

Để chạy background:

```bash
docker compose up --build -d
docker compose logs -f  # xem log
```

---

## 4. Cách di dữ liệu từ WinForms sang Web

### 4.1 Xuất từ WinForms

1. Mở FlowMeta WinForms
2. Tab **Hồ sơ** → click nút **Xuất** (hoặc nút Export trong menu)
3. Lưu file `.txt` — mỗi dòng có dạng:

```
1000123456|EAAGm0PX9y...
1000654321|EAABw2zL7k...
```

### 4.2 Nhập vào Web

1. Mở FlowMeta Web (<http://localhost:3000>)
2. Vào trang **Hồ sư**
3. Click **Nhập Profile**
4. Dán nội dung file `.txt` vào hộp thoại
5. Click **Nhập dữ liệu**

Dữ liệu đã được mã hóa Fernet trước khi lưu vào PostgreSQL. Trên màn hình, token hiển thị dạng `EAAG******abcd` (4 ký tự đầu + 4 ký tự cuối).

### 4.3 Cấu hình Proxy

1. Vào trang **Proxy**
2. Dán danh sách API keys KiotProxy vào ô **API Keys** (mỗi dòng 1 key)
3. Nhập **Token xác thực Kiot** (nếu KiotProxy yêu cầu)
4. Click **Lưu cấu hình proxy**
5. Click **Bắt đầu proxy** để monitor bắt đầu đổi IP tự động

Logic round-robin, auto-refresh khi IP hết hạn (30 phút) và auto-fetch IP mới khi hết lượt sử dụng (mặc định: 4 lượt/IP) được giữ nguyên y chang WinForms.

### 4.4 Cấu hình Delay / Luồng

Vào **Cài đặt** để đặt:

- **Delay mặc định**: tối thiểu — tối đa (giây) sau mỗi vòng
- **Sau mỗi N vòng**: số vòng để áp dụng delay
- **Luồng song song tối đa**: số tác vụ chạy song song trong cùng 1 vòng (mặc định: 5)

---

## 5. Hạn chế đã biết

| # | Hạn chế | Mức độ | Giải pháp / Kế hoạch |
|---|---------|--------|----------------------|
| 1 | Không có license activation — mở mật | Low | Single-user, auto-update qua Docker pull |
| 2 | Không có multi-user / chia sẻ profile | Low | v2 sẽ thêm auth + per-user data |
| 3 | Min-width 1180px — chưa responsive mobile | Low | v1 là desktop-only |
| 4 | Hình ảnh upload lưu tạm trên filesystem container | Low | v1 — S3 sẽ là lựa chọn cho production |
| 5 | Trang Auto Post và Auto Share chỉ có mock UI | Low | Chưa tích hợp backend |
| 6 | Redis chỉ dùng cho proxy state in-memory, chưa pub/sub | Low | Scale-out worker cần Redis pub/sub |
| 7 | Auth chỉ là stub — token HMAC đơn giản | Medium | Production cần OAuth2 / JWT |

---

## 6. FAQ

**Q: Dữ liệu cũ (file `.dpapi` trên WinForms) có chuyển được sang web không?**  
A: Có. Xuất **Profile** từ WinForms (dạng `uid|token` mỗi dòng), rồi nhập vào trang **Hồ sơ** trên web. File `.dpapi` không thể đọc trực tiếp vì nó được mã hóa theo user Windows hiện tại — cần chạy WinForms để xuất.

**Q: Token Facebook của tôi có an toàn không trên web?**  
A: Có. Token được mã hóa Fernet trước khi lưu vào PostgreSQL. Key Fernet được set qua biến môi trường `FERNET_KEY` — không lưu trong git.

**Q: Tôi có thể dùng chung một profile với nhiều người không?**  
A: Không trong v1 — single-user app. Mỗi deployment phục vụ 1 người dùng. Phần backend đã có schema `users` + `facebook_accounts` + `facebook_pages` có FK đến `user_id` — ready cho multi-user ở v2.

**Q: Nếu KiotProxy API thay đổi trả về format JSON?**  
A: Code KiotProxyClient đã xử lý nhiều format khác nhau: `data.data`, `data` root-level, `success=false`, `host`/`httpPort` cũ hoặc `httpStaticProxy` text, expiry ẩn trong các field `expire/ttl/lifetime/...`. Hầu hết cases thực tế đều được cover.

**Q: Cách tôi tự cập nhật FlowMeta Web?**  
A:
```bash
docker compose pull      # kéo image mới
docker compose up -d     # khởi động lại
docker compose logs -f   # xem log
```

**Q: Port đang bị chiếm, tôi đổi được không?**  
A: Có. Sửa `docker-compose.yml`:
```yaml
services:
  frontend:
    ports:
      - "3001:3000"     # đổi port ngoài
  backend:
    ports:
      - "8001:8000"     # đổi port ngoài
```
Hoặc set biến môi trường:
```bash
FRONTEND_PORT=3001 BACKEND_PORT=8001 docker compose up
```

**Q: Dữ liệu tôi có mất khi xóa container không?**  
A: Nếu xóa theo `docker compose down -v` thì mất data volume. Bình thường `docker compose down` giữ nguyên volume. Backup:
```bash
docker compose exec postgres pg_dump -U flowmeta flowmeta > backup.sql
```

**Q: Tôi cần mở thêm port 80/443 cho NGINX?**  
A: Docker Compose hiện tại expose 3000 (frontend) và 8000 (backend). Để reverse-proxy qua nginx/Caddy, thêm service vào `docker-compose.yml` theo hướng dẫn deploy riêng.

---

## 7. Liên hệ / Hỗ trợ

Nếu gặp lỗi deployment hoặc muốn đóng góp:

- **Repo**: kiểm tra file `fb_automator_design_spec.md` trong project
- **Deployment**: xem `docs/DEPLOY.md`
- **Backend**: đọc docstrings trong `backend/app/services/`
- **Frontend**: đọc `frontend/src/components/`
