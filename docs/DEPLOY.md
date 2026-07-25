# FlowMeta - Hướng dẫn deploy

## Yêu cầu trước khi bắt đầu

- [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/) (phiên bản mới nhất)
- [Docker Compose](https://docs.docker.com/compose/install/) (đã tích hợp trong Docker Desktop)
- Windows 10/11 (x64)

---

## Bước 1 – Sao chép mã nguồn

Mở PowerShell, chạy:

```powershell
git clone https://github.com/<your-org>/flowmeta.git
cd flowmeta
```

---

## Bước 2 – Tạo file môi trường

Sao chép file mẫu và điền các biến bắt buộc:

```powershell
Copy-Item .env.example .env
```

Mở `.env` bằng trình soạn thảo và cập nhật:

| Biến | Mô tả | Mặc định |
|---|---|---|
| `POSTGRES_PASSWORD` | Mật khẩu PostgreSQL | `change-me` |
| `FERNET_KEY` | Khóa mã hóa — **bắt buộc phải đổi** | — |
| `FLOWMETA_TOKEN_SECRET` | Secret token — **bắt buộc phải đổi** | — |
| `KASM_VNC_PASSWORD` | Mật khẩu phiên browser nhìn thấy — **bắt buộc phải đổi** | — |
| `CORS_ORIGINS` | Origin frontend được phép gọi API | `http://localhost:3000` |
| `NEXT_PUBLIC_API_URL` | URL API mà trình duyệt truy cập | `http://localhost:8000` |

---

## Bước 3 – Tạo secret

Mở PowerShell (cần đã cài Python 3.x), chạy:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy output dán vào giá trị `FERNET_KEY` trong file `.env`.

Tạo thêm `FLOWMETA_TOKEN_SECRET` bằng chuỗi ngẫu nhiên dài:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Không dùng các giá trị `change-me` ở môi trường public. `docker compose` sẽ từ chối khởi động nếu thiếu các secret bắt buộc.

---

## Bước 4 – Khởi động toàn bộ stack

```powershell
docker compose up -d
```

Lần đầu Docker sẽ pull image và build, mất vài phút tùy tốc độ mạng.
Service `migrate` chạy `alembic upgrade head` trước khi backend/worker khởi động. Không sửa schema thủ công.

---

## Bước 5 – Kiểm tra trạng thái

```powershell
docker compose ps
```

Các service dài hạn `postgres`, `redis`, `backend`, `worker`, `browser-worker`, `browserless` và `frontend` phải ở trạng thái chạy. `migrate` phải kết thúc với mã `0`.

Kiểm tra health status chi tiết:

```powershell
docker compose ps --format "table {{.Name}}\t{{.Status}}"
docker compose logs migrate
```

---

## Bước 6 – Mở ứng dụng

- **Frontend:** [http://localhost:3000](http://localhost:3000)
- **API docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **API health:** [http://localhost:8000/api/health](http://localhost:8000/api/health)

Sau khi đăng nhập, vào **Chiến dịch Sheets** để xem health của publication jobs. `stale_jobs` phải bằng `0` trước khi chạy chiến dịch lớn.

## Bước 7 – Smoke test trước khi dùng thật

1. Tạo một kết nối Google Sheets thử nghiệm và bấm **Kiểm tra**.
2. Tạo campaign với một dòng và một target thử nghiệm.
3. Bấm **Đồng bộ ngay**, kiểm tra source item và publication job.
4. Với đăng trọ, chạy **Đồng bộ ngay**, mở lịch sử job của một phòng rồi mới gán group.
5. Kiểm tra bài trên Facebook và URL kết quả; không chỉ dựa vào trạng thái giao diện.
6. Kiểm tra log không có vòng lỗi lặp:

```powershell
docker compose logs --since 10m backend worker browser-worker
```

Chỉ tăng số target sau khi smoke test một target thành công.

---

## Các lệnh hữu ích

```powershell
# Xem logs của backend
docker compose logs -f backend

# Xem logs của frontend
docker compose logs -f frontend

# Xem scheduler Google Sheets / phòng trọ
docker compose logs -f backend

# Xem queue và automation trình duyệt
docker compose logs -f worker browser-worker

# Kiểm tra file compose sau khi nội suy biến môi trường
docker compose config --quiet

# Chạy migration thủ công sau khi cập nhật source
docker compose run --rm migrate

# Dừng tất cả services
docker compose down

# Dừng xóa cả data volumes
docker compose down -v

# Khởi động lại sau khi thay đổi code
docker compose up -d --build
```

## Scheduler và chạy nhiều backend

Scheduler Google Sheets, đăng trọ và publication jobs chạy trong service `backend`.

- Với cấu hình mặc định, chỉ chạy **một** replica backend có `SCHEDULER_ENABLED=true`.
- Nếu scale backend, chỉ một instance được bật scheduler; đặt `SCHEDULER_ENABLED=false` cho các instance còn lại.
- `SCHEDULER_INTERVAL_SECONDS` mặc định là `60`, không nên đặt dưới `5`.

---

## Khắc phục sự cố thường gặp

### Port đã được sử dụng

Nếu port 3000 hoặc 8000 bị chiếm, đổi trong file `.env`:

```powershell
# .env
FRONTEND_PORT=3001
BACKEND_PORT=8001
```

Rồi chạy lại `docker compose up -d`.

### Backend khởi động nhưng healthcheck fail

xem log chi tiết:

```powershell
docker compose logs backend
```

Thường gặp khi `FERNET_KEY` hoặc `FLOWMETA_TOKEN_SECRET` chưa được cấu hình đúng trong `.env`.

### Frontend báo lỗi build

Xóa cache và build lại:

```powershell
docker compose down
docker compose build --no-cache frontend
docker compose up -d
```

### Windows: lỗi quyền file sharing

Mở Docker Desktop → Settings → Resources → File Sharing → Thêm thư mục chứa project.

---

## Cấu trúc volume

| Volume | Mục đích |
|---|---|
| `postgres-data` | Dữ liệu PostgreSQL |
| `redis-data` | Dữ liệu Redis persistence |
| `backend-logs` | Logs của backend |
| `backend-uploads` | Media upload, ảnh comment và media đã tải |
| `browser-profiles` | Session/profile browser dùng cho Facebook |

Volume được lưu trong `\\wsl$\docker-desktop-data\data\docker\volumes\` trên Windows.
