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

---

## Bước 3 – T Fernet key

Mở PowerShell (cần đã cài Python 3.x), chạy:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy output dán vào giá trị `FERNET_KEY` trong file `.env`.

---

## Bước 4 – Khởi động toàn bộ stack

```powershell
docker compose up -d
```

Lần đầu Docker sẽ pull image và build, mất vài phút tùy tốc độ mạng.

---

## Bước 5 – Kiểm tra trạng thái

```powershell
docker compose ps
```

Tất cả 4 services (`postgres`, `redis`, `backend`, `frontend`) phải hiển thị `State: running`.

Kiểm tra health status chi tiết:

```powershell
docker compose ps --format "table {{.Name}}\t{{.Status}}"
```

---

## Bước 6 – Mở ứng dụng

- **Frontend:** [http://localhost:3000](http://localhost:3000)
- **API docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **API health:** [http://localhost:8000/api/health](http://localhost:8000/api/health)

---

## Các lệnh hữu ích

```powershell
# Xem logs của backend
docker compose logs -f backend

# Xem logs của frontend
docker compose logs -f frontend

# Dừng tất cả services
docker compose down

# Dừng xóa cả data volumes
docker compose down -v

# Khởi động lại sau khi thay đổi code
docker compose up -d --build
```

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

Volume được lưu trong `\\wsl$\docker-desktop-data\data\docker\volumes\` trên Windows.
