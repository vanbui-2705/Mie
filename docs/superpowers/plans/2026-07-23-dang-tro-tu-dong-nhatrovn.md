# Đăng trọ tự động từ nhatrovn — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lấy tin phòng trọ của công ty từ cổng `quanly.nhatrovn.vn` theo khu vực đã chọn, lưu vào DB (đồng bộ ra Google Sheet), tự động đăng vào các nhóm Facebook có tên khớp Quận/Huyện với nhịp giãn cách an toàn, qua một trang quản trị riêng.

**Architecture:** Adapter đăng nhập cổng + `POST /main/room-sale/search` → parse HTML → `Room`. Sync service dedup/lưu `RentalRoom`, khớp nhóm theo tên quận, đồng bộ ra Sheet. Post service đăng giãn cách bằng cách tái dùng pipeline `_run_page_post_task` sẵn có. Hai worker móc vào `_scheduler_tick()` trong `main.py`. Frontend Next.js thêm trang cấu hình + theo dõi.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async + Postgres, Alembic, httpx, BeautifulSoup4, pytest/pytest-asyncio; Next.js/React + TypeScript; Google Sheets REST (service-account, có sẵn).

## Global Constraints

- Backend nằm trong `backend/`, chạy test bằng `pytest` (từ thư mục `backend/`). Async dùng `pytest.mark.asyncio` như các test hiện có.
- Bí mật (mật khẩu cổng, service-account) **mã hoá bằng `app.crypto.encrypt`/`decrypt`** (Fernet). Không log giá trị bí mật.
- Mọi model kế thừa `Base` trong `app/models/sqlmodels.py`; UUID PK dùng `server_default=func.gen_random_uuid()`.
- Router mới bảo vệ bằng `app.rbac.require_permission(...)` như `app/routers/google_sheets.py`.
- Đăng bài **tái dùng** `app.routers.page_tasks._run_page_post_task` — KHÔNG viết lại logic gọi Facebook.
- Nhịp đăng: giãn cách áp cho **từng lượt (1 phòng × 1 nhóm)**.
- Khớp nhóm cấp **Quận/Huyện**; không khớp → trạng thái `waiting_groups` (người dùng gán tay).
- Commit thường xuyên: mỗi Task kết thúc bằng một commit.
- Thêm dependency `beautifulsoup4` vào `backend/requirements.txt` (Task 1).

---

## File Structure

**Tạo mới (backend):**
- `backend/app/services/nhatrovn_adapter.py` — login + fetch + parse HTML → `Room`.
- `backend/app/services/rental_group_match.py` — chuẩn hoá tên + khớp `FacebookGroup`.
- `backend/app/services/rental_sync.py` — sync/dedup/caption/match/persist + mirror Sheet.
- `backend/app/services/rental_post.py` — throttle + đăng + retry + ghi ngược.
- `backend/app/routers/rental.py` — API CRUD config, rooms, sync-now, post-now, assign-groups, skip, retry.
- `backend/alembic/versions/20260723_0005_rental_configs_rooms.py` — migration.
- `backend/tests/fixtures/nhatrovn_room_sale.html` — HTML thật (Task 1).
- `backend/tests/test_nhatrovn_adapter.py`, `test_rental_group_match.py`, `test_rental_sync.py`, `test_rental_post.py`, `tests/integration/test_rental_api.py`.

**Sửa (backend):**
- `backend/app/models/sqlmodels.py` — thêm `RentalConfig`, `RentalRoom`.
- `backend/app/services/google_sheets.py` — thêm `append_rows`, `update_cells`.
- `backend/app/main.py` — đăng ký router + móc worker vào `_scheduler_tick`.
- `backend/app/rbac_catalog.py` — thêm quyền `rental:*`.
- `backend/requirements.txt` — `beautifulsoup4`.

**Tạo mới / sửa (frontend):**
- `frontend/src/app/tro/page.tsx` (hoặc theo cấu trúc route hiện có) — trang "Đăng trọ tự động".
- `frontend/src/lib/api-client.ts` — thêm hàm gọi API rental.
- `frontend/src/components/layout/SideNav.tsx` — thêm link.

---

## Task 1: Khảo sát nhatrovn & tạo fixture

**Mục tiêu:** Chốt các ẩn số của cổng: form params đăng nhập, form params `/search`, phân trang, và selector từng trường. Lưu HTML thật làm fixture cho parser.

**Files:**
- Create: `backend/tests/fixtures/nhatrovn_room_sale.html`
- Create: `backend/tests/fixtures/nhatrovn_notes.md` (ghi params + selector)
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: file fixture HTML + tài liệu `nhatrovn_notes.md` mô tả: endpoint login (URL, field tên/mật khẩu, có OTP/captcha không), endpoint `/search` (URL, các form field: `page`, mã tỉnh/quận/phường, các filter khác), cách phân trang, và selector cho: mã phòng (`external_room_id`), tiêu đề, giá, diện tích, địa chỉ, quận, phường, mô tả, ảnh, trạng thái.

- [ ] **Step 1: Lấy HTML thật của trang danh sách.** Trong phiên trình duyệt đã đăng nhập (`quanly.nhatrovn.vn/main/room-sale/init`), chạy tìm kiếm rồi lưu `document.querySelector('div.row').outerHTML` của khối chứa các thẻ phòng vào `backend/tests/fixtures/nhatrovn_room_sale.html`. Nếu output bị bộ lọc chặn (token/URL), thay các `href`/`src` chứa token bằng chuỗi giả trước khi lưu (giữ nguyên cấu trúc tag/class).

- [ ] **Step 2: Ghi lại form params `/search` và luồng login.** Dùng DevTools/Network (hoặc `read_network_requests`) bắt request `POST /main/room-sale/search`: liệt kê tên các form field và ý nghĩa (đặc biệt mã tỉnh/quận/phường và `page`). Kiểm tra trang login: field tên đăng nhập/mật khẩu, và **có OTP/captcha không**. Ghi hết vào `backend/tests/fixtures/nhatrovn_notes.md`.

- [ ] **Step 3: Chốt selector từng trường.** Dựa trên fixture, xác định selector cụ thể cho mỗi trường (đã biết: card = `div.card.card-body`; cặp `span` nhãn → `span.fw-800` giá trị trong `div.col-4.small`; cọc/HĐ = `span.fw-700.contract-time`; trạng thái = phần tử `.text-color-room-live`). Bổ sung selector cho tiêu đề/mã phòng, địa chỉ, ảnh. Ghi bảng `label → selector` vào `nhatrovn_notes.md`.

- [ ] **Step 4: Thêm dependency.** Thêm dòng `beautifulsoup4>=4.12` vào `backend/requirements.txt` và cài: `pip install beautifulsoup4`.

- [ ] **Step 5: Commit.**

```bash
git add backend/tests/fixtures/nhatrovn_room_sale.html backend/tests/fixtures/nhatrovn_notes.md backend/requirements.txt
git commit -m "chore(rental): fixture HTML nhatrovn + ghi chú params/selector"
```

---

## Task 2: Model DB `RentalConfig` + `RentalRoom` + migration

**Files:**
- Modify: `backend/app/models/sqlmodels.py` (thêm cuối file, cạnh `GoogleSheetConnection`)
- Create: `backend/alembic/versions/20260723_0005_rental_configs_rooms.py`
- Test: `backend/tests/test_rental_models.py`

**Interfaces:**
- Produces: `RentalConfig` và `RentalRoom` (SQLAlchemy models). Cột chính của `RentalConfig`: `id, user_id, name, source_type, source_credentials_enc, province_code, province_name, district_code, district_name, ward_code, ward_name, extra_filters_json, auto_post, post_spacing_seconds, post_delay_seconds, caption_template, contact_phone, group_match_level, poll_interval_seconds, timezone, google_sheet_connection_id, status, last_synced_at, last_post_at, last_error, created_at, updated_at`. Cột chính của `RentalRoom`: `id, config_id, user_id, external_room_id, title, price, area_text, address, district, ward, description, images_json, caption, matched_group_ids_json, status, post_urls_json, posted_at, retry_count, error, created_at, updated_at` với `UniqueConstraint(config_id, external_room_id)`.

- [ ] **Step 1: Viết test kiểm tra tạo bản ghi.**

```python
# backend/tests/test_rental_models.py
import pytest
from app.models.sqlmodels import RentalConfig, RentalRoom

@pytest.mark.asyncio
async def test_create_rental_config_and_room(db_session):
    cfg = RentalConfig(
        user_id=await _a_user_id(db_session),
        name="Trọ Gò Vấp", source_type="nhatrovn",
        source_credentials_enc="enc", province_code="79", province_name="TP HCM",
        district_code="764", district_name="Gò Vấp",
        caption_template="{title}", contact_phone="0900",
        poll_interval_seconds=300, post_spacing_seconds=480,
    )
    db_session.add(cfg); await db_session.flush()
    room = RentalRoom(
        config_id=cfg.id, user_id=cfg.user_id,
        external_room_id="P.004", title="P.004", price="3,000,000",
        area_text="30m2", address="496 Đào Sư Tích", district="Gò Vấp",
        description="mô tả", images_json="[]", caption="cap", status="new",
    )
    db_session.add(room); await db_session.flush()
    assert room.id is not None and room.status == "new"
```

Dùng helper `_a_user_id` tạo user tối thiểu theo pattern trong `backend/tests/conftest.py` (xem fixture user hiện có; nếu conftest đã có helper tạo user, dùng lại).

- [ ] **Step 2: Chạy test → FAIL** (`ImportError: RentalConfig`).

Run: `cd backend && pytest tests/test_rental_models.py -v`
Expected: FAIL (import error).

- [ ] **Step 3: Thêm 2 model.** Trong `app/models/sqlmodels.py`, thêm (theo mẫu `GoogleSheetConnection`):

```python
class RentalConfig(Base):
    __tablename__ = "rental_configs"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="nhatrovn")
    source_credentials_enc: Mapped[str] = mapped_column(Text, nullable=False)
    province_code: Mapped[str] = mapped_column(String(32), nullable=False)
    province_name: Mapped[str] = mapped_column(String(128), nullable=False)
    district_code: Mapped[str] = mapped_column(String(32), nullable=False)
    district_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ward_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default=None)
    ward_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    extra_filters_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    auto_post: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    post_spacing_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=480)
    post_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    caption_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    group_match_level: Mapped[str] = mapped_column(String(16), nullable=False, default="district")
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Ho_Chi_Minh")
    google_sheet_connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("google_sheet_connections.id", ondelete="SET NULL"), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    last_post_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class RentalRoom(Base):
    __tablename__ = "rental_rooms"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    config_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("rental_configs.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    external_room_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    area_text: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    district: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    ward: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, default=None)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    images_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    matched_group_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new")
    post_urls_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint("config_id", "external_room_id", name="uq_rental_rooms_config_room"),)
```

Kiểm tra đầu file đã import `Boolean` từ `sqlalchemy`; nếu chưa, thêm vào import.

- [ ] **Step 4: Viết migration Alembic.** Tạo `backend/alembic/versions/20260723_0005_rental_configs_rooms.py` với `down_revision` = revision mới nhất hiện có (xem file `20260720_0004_google_sheet_connections.py` để lấy `revision` của nó làm `down_revision`). `upgrade()` tạo 2 bảng đúng cột trên + unique constraint + index `(user_id)`; `downgrade()` drop 2 bảng.

- [ ] **Step 5: Chạy test → PASS** (conftest tạo schema từ metadata nên bảng mới xuất hiện tự động).

Run: `cd backend && pytest tests/test_rental_models.py -v`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/models/sqlmodels.py backend/alembic/versions/20260723_0005_rental_configs_rooms.py backend/tests/test_rental_models.py
git commit -m "feat(rental): model RentalConfig + RentalRoom + migration"
```

---

## Task 3: `NhatrovnAdapter.parse_rooms` — parse HTML → Room

**Files:**
- Create: `backend/app/services/nhatrovn_adapter.py`
- Test: `backend/tests/test_nhatrovn_adapter.py`

**Interfaces:**
- Produces: `@dataclass Room{external_room_id:str, title:str, price:str, area_text:str, address:str, district:str|None, ward:str|None, description:str, images:list[str]}` và `class NhatrovnAdapter` với `@staticmethod parse_rooms(html: str) -> list[Room]`.
- Consumes: fixture `backend/tests/fixtures/nhatrovn_room_sale.html` + selector trong `nhatrovn_notes.md` (Task 1).

- [ ] **Step 1: Viết test parse fixture.**

```python
# backend/tests/test_nhatrovn_adapter.py
from pathlib import Path
from app.services.nhatrovn_adapter import NhatrovnAdapter, Room

FIXTURE = Path(__file__).parent / "fixtures" / "nhatrovn_room_sale.html"

def test_parse_rooms_extracts_all_cards():
    rooms = NhatrovnAdapter.parse_rooms(FIXTURE.read_text(encoding="utf-8"))
    assert len(rooms) >= 1
    r = rooms[0]
    assert isinstance(r, Room)
    assert r.external_room_id            # không rỗng
    assert r.title
    assert r.price
    assert r.area_text
    assert r.address
```

- [ ] **Step 2: Chạy test → FAIL** (`ModuleNotFoundError`).

Run: `cd backend && pytest tests/test_nhatrovn_adapter.py::test_parse_rooms_extracts_all_cards -v`
Expected: FAIL.

- [ ] **Step 3: Viết parser.** Tạo `app/services/nhatrovn_adapter.py`. Dùng BeautifulSoup, selector từ Task 1. Khung cụ thể (điền selector chính xác theo `nhatrovn_notes.md`):

```python
from __future__ import annotations
from dataclasses import dataclass, field
from bs4 import BeautifulSoup

@dataclass
class Room:
    external_room_id: str
    title: str
    price: str = ""
    area_text: str = ""
    address: str = ""
    district: str | None = None
    ward: str | None = None
    description: str = ""
    images: list[str] = field(default_factory=list)

def _label_value(card, label: str) -> str:
    """Tìm <span>label:</span> rồi lấy <span class=fw-800/fw-700> kế tiếp."""
    for span in card.select("span"):
        if span.get_text(strip=True).rstrip(":") == label.rstrip(":"):
            val = span.find_next("span")
            return val.get_text(strip=True) if val else ""
    return ""

class NhatrovnAdapter:
    @staticmethod
    def parse_rooms(html: str) -> list[Room]:
        soup = BeautifulSoup(html, "html.parser")
        rooms: list[Room] = []
        for card in soup.select("div.card.card-body"):
            title_el = card.select_one("h4, h5, b, strong, .card-title")  # chỉnh theo Task 1
            title = title_el.get_text(strip=True) if title_el else ""
            ext_id = title.split("–")[0].split("-")[0].strip() or title  # mã phòng đầu tiêu đề; chỉnh theo Task 1
            address_el = card.select_one(".room-address, .address")        # chỉnh theo Task 1
            images = [img.get("src", "") for img in card.select("img") if img.get("src")]
            rooms.append(Room(
                external_room_id=ext_id,
                title=title,
                price=_label_value(card, "Giá cho thuê"),
                area_text=_label_value(card, "Diện tích"),
                address=address_el.get_text(strip=True) if address_el else "",
                description=card.get_text(" ", strip=True)[:1000],
                images=[i for i in images if not i.startswith("data:")],
            ))
        return rooms
```

> Ghi chú thực thi: selector `title_el`, `ext_id`, `address_el`, và cách lấy quận/phường phải khớp `nhatrovn_notes.md`. Nếu tiêu đề chứa mã phòng như `P.004 – 496 ĐÀO SƯ TÍCH` thì `external_room_id="P.004"`. Nếu có `data-id` trên card thì ưu tiên dùng nó.

- [ ] **Step 4: Chạy test → PASS.**

Run: `cd backend && pytest tests/test_nhatrovn_adapter.py -v`
Expected: PASS. Nếu FAIL vì selector, tinh chỉnh selector theo fixture rồi chạy lại.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/nhatrovn_adapter.py backend/tests/test_nhatrovn_adapter.py
git commit -m "feat(rental): parse HTML phòng nhatrovn -> Room"
```

---

## Task 4: `NhatrovnAdapter.login` + `fetch_rooms`

**Files:**
- Modify: `backend/app/services/nhatrovn_adapter.py`
- Test: `backend/tests/test_nhatrovn_adapter.py`

**Interfaces:**
- Produces: `async login(self, username, password) -> httpx.AsyncClient` (client có cookie phiên; raise `NhatrovnError` nếu sai mật khẩu hoặc gặp OTP/captcha), `async fetch_rooms(self, client, *, province_code, district_code, ward_code=None, max_pages=10) -> list[Room]`, và `class NhatrovnError(Exception)`.
- Consumes: `parse_rooms` (Task 3), form params từ `nhatrovn_notes.md` (Task 1).

- [ ] **Step 1: Viết test dùng transport giả (mock httpx).**

```python
import httpx, pytest
from app.services.nhatrovn_adapter import NhatrovnAdapter, NhatrovnError

@pytest.mark.asyncio
async def test_fetch_rooms_paginates_until_empty(monkeypatch):
    pages = {1: (FIXTURE.read_text(encoding="utf-8")), 2: "<div class='row'></div>"}
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, headers={"set-cookie": "sess=abc"})
        page = int(dict(request.url.params).get("page", "1")) if request.url.params else 1
        # form body 'page=' cũng có thể ở body; fixture đơn giản dùng query
        return httpx.Response(200, text=pages.get(page, "<div class='row'></div>"))
    transport = httpx.MockTransport(handler)
    adapter = NhatrovnAdapter(transport=transport)
    client = await adapter.login("user", "pass")
    rooms = await adapter.fetch_rooms(client, province_code="79", district_code="764", max_pages=3)
    assert len(rooms) >= 1
```

- [ ] **Step 2: Chạy test → FAIL** (`login` chưa có).

Run: `cd backend && pytest tests/test_nhatrovn_adapter.py::test_fetch_rooms_paginates_until_empty -v`
Expected: FAIL.

- [ ] **Step 3: Viết login + fetch_rooms.** Thêm vào `nhatrovn_adapter.py`:

```python
import httpx

BASE = "https://quanly.nhatrovn.vn"
LOGIN_URL = f"{BASE}/main/login"        # chỉnh theo Task 1
SEARCH_URL = f"{BASE}/main/room-sale/search"

class NhatrovnError(Exception): ...

class NhatrovnAdapter:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, base_url=BASE, timeout=30, follow_redirects=True)

    async def login(self, username: str, password: str) -> httpx.AsyncClient:
        client = self._client()
        resp = await client.post(LOGIN_URL, data={"username": username, "password": password})  # field theo Task 1
        text = resp.text.lower()
        if "captcha" in text or "otp" in text:
            await client.aclose()
            raise NhatrovnError("Cổng yêu cầu OTP/captcha — cần đăng nhập thủ công.")
        if resp.status_code >= 400 or "đăng nhập" in text and "sai" in text:
            await client.aclose()
            raise NhatrovnError("Đăng nhập nhatrovn thất bại — kiểm tra tài khoản/mật khẩu.")
        return client

    async def fetch_rooms(self, client, *, province_code, district_code, ward_code=None, max_pages=10) -> list["Room"]:
        rooms: list[Room] = []
        for page in range(1, max_pages + 1):
            data = {"page": str(page), "province": province_code, "district": district_code}  # field theo Task 1
            if ward_code:
                data["ward"] = ward_code
            resp = await client.post(SEARCH_URL, data=data, headers={"X-Requested-With": "XMLHttpRequest"})
            if resp.status_code >= 400:
                raise NhatrovnError(f"Search lỗi HTTP {resp.status_code}")
            page_rooms = self.parse_rooms(resp.text)
            if not page_rooms:
                break
            rooms.extend(page_rooms)
        return rooms
```

> Ghi chú: tên field (`username`/`password`/`province`/`district`/`ward`) phải khớp `nhatrovn_notes.md`. Điều kiện phát hiện đăng nhập lỗi tinh chỉnh theo HTML thật.

- [ ] **Step 4: Chạy test → PASS.**

Run: `cd backend && pytest tests/test_nhatrovn_adapter.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/nhatrovn_adapter.py backend/tests/test_nhatrovn_adapter.py
git commit -m "feat(rental): login + fetch_rooms nhatrovn (phân trang)"
```

---

## Task 5: `GroupMatcher` — khớp nhóm theo tên quận

**Files:**
- Create: `backend/app/services/rental_group_match.py`
- Test: `backend/tests/test_rental_group_match.py`

**Interfaces:**
- Produces: `normalize_vn(text: str) -> str` (bỏ dấu, lowercase, gộp khoảng trắng) và `match_group_ids(district_name: str, groups: list) -> list[str]` (mỗi `group` có `.group_id`, `.group_name`; trả về danh sách `group_id` mà tên nhóm chứa tên quận đã chuẩn hoá, bỏ tiền tố "quan"/"huyen").

- [ ] **Step 1: Viết test.**

```python
# backend/tests/test_rental_group_match.py
from types import SimpleNamespace
from app.services.rental_group_match import normalize_vn, match_group_ids

def test_normalize_strips_accents():
    assert normalize_vn("Gò Vấp") == "go vap"

def test_match_by_district_contains():
    groups = [
        SimpleNamespace(group_id="1", group_name="Thuê trọ Gò Vấp giá rẻ"),
        SimpleNamespace(group_id="2", group_name="Nhà trọ Bình Thạnh"),
        SimpleNamespace(group_id="3", group_name="Phòng trọ GÒ VẤP - HCM"),
    ]
    ids = match_group_ids("Gò Vấp", groups)
    assert set(ids) == {"1", "3"}

def test_no_match_returns_empty():
    groups = [SimpleNamespace(group_id="2", group_name="Nhà trọ Bình Thạnh")]
    assert match_group_ids("Gò Vấp", groups) == []
```

- [ ] **Step 2: Chạy test → FAIL.**

Run: `cd backend && pytest tests/test_rental_group_match.py -v`
Expected: FAIL (import error).

- [ ] **Step 3: Viết implementation.**

```python
# backend/app/services/rental_group_match.py
from __future__ import annotations
import re, unicodedata

def normalize_vn(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text or ""))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"\s+", " ", text).strip()

def match_group_ids(district_name: str, groups) -> list[str]:
    key = normalize_vn(district_name)
    for prefix in ("quan ", "huyen ", "thi xa ", "tp "):
        if key.startswith(prefix):
            key = key[len(prefix):]
    key = key.strip()
    if not key:
        return []
    out: list[str] = []
    for g in groups:
        name = normalize_vn(getattr(g, "group_name", "") or "")
        if key and key in name:
            out.append(str(getattr(g, "group_id", "") or ""))
    return [gid for gid in out if gid]
```

- [ ] **Step 4: Chạy test → PASS.**

Run: `cd backend && pytest tests/test_rental_group_match.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/rental_group_match.py backend/tests/test_rental_group_match.py
git commit -m "feat(rental): khớp nhóm FB theo tên quận (bỏ dấu, contains)"
```

---

## Task 6: `RentalSyncService` + caption

**Files:**
- Create: `backend/app/services/rental_sync.py`
- Test: `backend/tests/test_rental_sync.py`

**Interfaces:**
- Produces: `render_caption(template: str, room: Room, contact_phone: str) -> str` và `class RentalSyncService` với `async sync_config(self, config_id: uuid.UUID) -> dict` trả `{"added": int, "matched": int, "waiting": int}`. Constructor: `RentalSyncService(get_session, adapter=None)` — `adapter` inject được để test (mặc định tạo `NhatrovnAdapter`).
- Consumes: `NhatrovnAdapter` (Task 3–4), `match_group_ids` (Task 5), models (Task 2), `app.crypto.decrypt`.

- [ ] **Step 1: Viết test với adapter giả + DB.**

```python
# backend/tests/test_rental_sync.py
import json, pytest
from types import SimpleNamespace
from app.models.sqlmodels import RentalConfig, RentalRoom, FacebookGroup
from app.services.nhatrovn_adapter import Room
from app.services.rental_sync import RentalSyncService, render_caption

class FakeAdapter:
    def __init__(self, rooms): self._rooms = rooms
    async def login(self, u, p): return object()
    async def fetch_rooms(self, client, **kw): return self._rooms

def test_render_caption_has_hashtag():
    room = Room(external_room_id="P1", title="P1", price="3tr", area_text="30m2",
                address="Gò Vấp", district="Gò Vấp", description="đẹp", images=[])
    cap = render_caption("🏠 {title}\n💰 {price} 📐 {area_text}\n📍 {address}\n{description}\n📞 {contact_phone}\n#thuetro #{district_slug}", room, "0900")
    assert "#GoVap" in cap and "0900" in cap

@pytest.mark.asyncio
async def test_sync_dedups_and_matches(db_session, session_factory, a_user):
    cfg = RentalConfig(user_id=a_user.id, name="c", source_type="nhatrovn",
        source_credentials_enc=_enc('{"u":"x","p":"y"}'), province_code="79", province_name="HCM",
        district_code="764", district_name="Gò Vấp", caption_template="{title}", contact_phone="0900",
        poll_interval_seconds=300, post_spacing_seconds=1)
    db_session.add(cfg)
    db_session.add(FacebookGroup(user_id=a_user.id, group_id="10", group_name="Thuê trọ Gò Vấp", group_url="u"))
    await db_session.commit()
    rooms = [Room("P.004","P.004",district="Gò Vấp",address="Gò Vấp"),
             Room("P.005","P.005",district="Quận 1",address="Quận 1")]
    svc = RentalSyncService(session_factory, adapter=FakeAdapter(rooms))
    r1 = await svc.sync_config(cfg.id)
    assert r1["added"] == 2 and r1["matched"] == 1 and r1["waiting"] == 1
    r2 = await svc.sync_config(cfg.id)          # chạy lại: không thêm trùng
    assert r2["added"] == 0
```

Dùng fixture `session_factory`, `a_user`, và helper `_enc` (mã hoá credential) theo pattern conftest hiện có; nếu chưa có, thêm vào `conftest.py` một fixture `session_factory` trả context manager tạo `AsyncSession` (giống `session_context`).

- [ ] **Step 2: Chạy test → FAIL.**

Run: `cd backend && pytest tests/test_rental_sync.py -v`
Expected: FAIL.

- [ ] **Step 3: Viết service.**

```python
# backend/app/services/rental_sync.py
from __future__ import annotations
import json, logging, uuid
from datetime import datetime, timezone
from sqlalchemy import select
from app.crypto import decrypt
from app.models.sqlmodels import RentalConfig, RentalRoom, FacebookGroup
from app.services.nhatrovn_adapter import NhatrovnAdapter, Room
from app.services.rental_group_match import match_group_ids, normalize_vn

logger = logging.getLogger("flowmeta.rental_sync")

def render_caption(template: str, room: Room, contact_phone: str) -> str:
    slug = "".join(w.capitalize() for w in normalize_vn(room.district or "").split())
    return template.format(title=room.title, price=room.price, area_text=room.area_text,
        address=room.address, description=room.description, contact_phone=contact_phone,
        district=room.district or "", district_slug=slug or "khuvuc")

class RentalSyncService:
    def __init__(self, get_session, adapter=None):
        self._get_session = get_session
        self._adapter = adapter or NhatrovnAdapter()

    async def sync_config(self, config_id: uuid.UUID) -> dict:
        async with self._get_session() as session:
            cfg = await session.get(RentalConfig, config_id)
            if cfg is None:
                return {"added": 0, "matched": 0, "waiting": 0}
            creds = json.loads(decrypt(cfg.source_credentials_enc) or "{}")
            groups = list((await session.execute(select(FacebookGroup).where(FacebookGroup.user_id == cfg.user_id))).scalars())
            existing = set((await session.execute(select(RentalRoom.external_room_id).where(RentalRoom.config_id == cfg.id))).scalars())
        try:
            client = await self._adapter.login(creds.get("u", ""), creds.get("p", ""))
            rooms = await self._adapter.fetch_rooms(client, province_code=cfg.province_code,
                district_code=cfg.district_code, ward_code=cfg.ward_code)
        except Exception as exc:
            async with self._get_session() as session:
                c = await session.get(RentalConfig, config_id)
                c.status = "error"; c.last_error = str(exc); await session.commit()
            logger.warning("sync %s failed: %s", config_id, exc)
            return {"added": 0, "matched": 0, "waiting": 0}
        added = matched = waiting = 0
        async with self._get_session() as session:
            cfg = await session.get(RentalConfig, config_id)
            for room in rooms:
                if room.external_room_id in existing:
                    continue
                gids = match_group_ids(room.district or "", groups)
                status = "new" if gids else "waiting_groups"
                session.add(RentalRoom(config_id=cfg.id, user_id=cfg.user_id,
                    external_room_id=room.external_room_id, title=room.title, price=room.price,
                    area_text=room.area_text, address=room.address, district=room.district, ward=room.ward,
                    description=room.description, images_json=json.dumps(room.images),
                    caption=render_caption(cfg.caption_template, room, cfg.contact_phone),
                    matched_group_ids_json=json.dumps(gids) if gids else None, status=status))
                added += 1
                if gids: matched += 1
                else: waiting += 1
            cfg.last_synced_at = datetime.now(timezone.utc); cfg.status = "active"; cfg.last_error = None
            await session.commit()
        return {"added": added, "matched": matched, "waiting": waiting}
```

- [ ] **Step 4: Chạy test → PASS.**

Run: `cd backend && pytest tests/test_rental_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/rental_sync.py backend/tests/test_rental_sync.py backend/tests/conftest.py
git commit -m "feat(rental): sync dedup + caption + khớp nhóm"
```

---

## Task 7: `RentalPostService` — đăng giãn cách + retry

**Files:**
- Create: `backend/app/services/rental_post.py`
- Test: `backend/tests/test_rental_post.py`

**Interfaces:**
- Produces: `class RentalPostService(get_session, run_post=None)` với `async post_due(self, now=None) -> list[dict]`. `run_post` inject được (mặc định `app.routers.page_tasks._run_page_post_task`); test truyền hàm giả để không gọi Facebook.
- Consumes: models (Task 2), `TaskRun`/`TaskRunStatus`.

- [ ] **Step 1: Viết test throttle + trạng thái.**

```python
# backend/tests/test_rental_post.py
import json, pytest
from datetime import datetime, timezone, timedelta
from app.models.sqlmodels import RentalConfig, RentalRoom
from app.services.rental_post import RentalPostService

@pytest.mark.asyncio
async def test_post_due_respects_spacing(db_session, session_factory, a_user):
    cfg = RentalConfig(user_id=a_user.id, name="c", source_type="nhatrovn", source_credentials_enc="e",
        province_code="79", province_name="HCM", district_code="764", district_name="Gò Vấp",
        caption_template="{title}", contact_phone="0", poll_interval_seconds=300,
        post_spacing_seconds=600, auto_post=True, last_post_at=datetime.now(timezone.utc))
    db_session.add(cfg); await db_session.flush()
    db_session.add(RentalRoom(config_id=cfg.id, user_id=a_user.id, external_room_id="P1", title="P1",
        caption="cap", status="new", matched_group_ids_json=json.dumps(["10","11"])))
    await db_session.commit()
    calls = []
    async def fake_run(**kw): calls.append(kw)
    svc = RentalPostService(session_factory, run_post=fake_run)
    # chưa đủ spacing -> không đăng
    assert await svc.post_due(now=datetime.now(timezone.utc)) == []
    # đủ spacing -> đăng đúng 1 lượt (1 nhóm)
    later = datetime.now(timezone.utc) + timedelta(seconds=601)
    fired = await svc.post_due(now=later)
    assert len(fired) == 1 and len(calls) == 1
```

- [ ] **Step 2: Chạy test → FAIL.**

Run: `cd backend && pytest tests/test_rental_post.py -v`
Expected: FAIL.

- [ ] **Step 3: Viết service.**

```python
# backend/app/services/rental_post.py
from __future__ import annotations
import json, logging, uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.models.sqlmodels import RentalConfig, RentalRoom, TaskRun, TaskRunStatus

logger = logging.getLogger("flowmeta.rental_post")
MAX_RETRIES = 3

class RentalPostService:
    def __init__(self, get_session, run_post=None):
        self._get_session = get_session
        self._run_post = run_post

    def _runner(self):
        if self._run_post is not None:
            return self._run_post
        from app.routers.page_tasks import _run_page_post_task
        return _run_page_post_task

    async def post_due(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        fired: list[dict] = []
        async with self._get_session() as session:
            configs = list((await session.execute(select(RentalConfig).where(
                RentalConfig.auto_post == True, RentalConfig.status == "active"))).scalars())  # noqa: E712
            for cfg in configs:
                if cfg.last_post_at and (now - cfg.last_post_at) < timedelta(seconds=cfg.post_spacing_seconds):
                    continue
                room = (await session.execute(select(RentalRoom).where(
                    RentalRoom.config_id == cfg.id, RentalRoom.status == "new").order_by(
                    RentalRoom.created_at).limit(1))).scalar_one_or_none()
                if room is None:
                    continue
                group_ids = json.loads(room.matched_group_ids_json or "[]")
                posted = json.loads(room.post_urls_json or "{}")
                remaining = [g for g in group_ids if g not in posted]
                if not remaining:
                    room.status = "posted"; room.posted_at = now; await session.commit(); continue
                gid = remaining[0]
                room.status = "posting"; await session.commit()
                run = TaskRun(user_id=cfg.user_id, status=TaskRunStatus.RUNNING, action=cfg.source_type or "post",
                    max_threads=1, text_input_enc=room.caption, image_path=None)
                session.add(run); await session.flush()
                try:
                    await self._runner()(run_id=str(run.id), page_ids=[], group_ids=[gid],
                        personal_account_ids=[], message=room.caption,
                        link=None, media_paths=json.loads(room.images_json or "[]"))
                    posted[gid] = str(run.id)
                    room.post_urls_json = json.dumps(posted)
                    room.status = "posted" if len([g for g in group_ids if g in posted]) == len(group_ids) else "new"
                    if room.status == "posted": room.posted_at = now
                    room.error = None
                except Exception as exc:
                    room.retry_count += 1
                    room.status = "error" if room.retry_count >= MAX_RETRIES else "new"
                    room.error = str(exc)
                    logger.warning("post room %s failed: %s", room.id, exc)
                cfg.last_post_at = now
                await session.commit()
                fired.append({"config_id": str(cfg.id), "room_id": str(room.id), "group_id": gid, "status": room.status})
        return fired
```

- [ ] **Step 4: Chạy test → PASS.**

Run: `cd backend && pytest tests/test_rental_post.py -v`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add backend/app/services/rental_post.py backend/tests/test_rental_post.py
git commit -m "feat(rental): đăng giãn cách theo lượt + retry"
```

---

## Task 8: Ghi Google Sheet (append + update) — mirror

**Files:**
- Modify: `backend/app/services/google_sheets.py`
- Test: `backend/tests/test_google_sheets_write.py`

**Interfaces:**
- Produces: trên `GoogleSheetsClient`: `async append_rows(self, *, credentials, spreadsheet_id, sheet_name, rows: list[list[str]]) -> None` và `async update_cells(self, *, credentials, spreadsheet_id, sheet_name, a1_range: str, values: list[list[str]]) -> None`. Dùng lại `_access_token` + scope `spreadsheets` sẵn có.

- [ ] **Step 1: Viết test với httpx MockTransport.**

```python
# backend/tests/test_google_sheets_write.py
import httpx, pytest
from app.services.google_sheets import GoogleSheetsClient

@pytest.mark.asyncio
async def test_append_rows_posts_values(monkeypatch):
    seen = {}
    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok"})
        seen["url"] = str(request.url); seen["body"] = request.content.decode()
        return httpx.Response(200, json={"updates": {"updatedRows": 1}})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    creds = {"type":"service_account","client_email":"a@b.gserviceaccount.com","private_key": _TEST_PEM, "token_uri":"https://oauth2.googleapis.com/token"}
    gs = GoogleSheetsClient(http_client=client)
    await gs.append_rows(credentials=creds, spreadsheet_id="sid", sheet_name="Posts", rows=[["P1","3tr"]])
    assert "values:append" in seen["url"] and "P1" in seen["body"]
```

`_TEST_PEM` = một private key PEM hợp lệ dùng cho test (tạo bằng `cryptography` trong fixture, hoặc tái dùng helper có sẵn trong test google sheets hiện có nếu có).

- [ ] **Step 2: Chạy test → FAIL.**

Run: `cd backend && pytest tests/test_google_sheets_write.py -v`
Expected: FAIL (`append_rows` chưa có).

- [ ] **Step 3: Thêm 2 method.** Trong `GoogleSheetsClient`:

```python
    async def append_rows(self, *, credentials, spreadsheet_id, sheet_name, rows):
        normalized = normalize_service_account_credentials(credentials)
        sid = parse_spreadsheet_id(spreadsheet_id)
        async def _do(client):
            token = await self._access_token(client, normalized)
            rng = quote(f"'{sheet_name.replace(chr(39), chr(39)*2)}'!A1", safe="")
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{quote(sid, safe='')}/values/{rng}:append"
            resp = await client.post(url, headers={"Authorization": f"Bearer {token}"},
                params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                json={"values": rows})
            if resp.status_code >= 400:
                raise GoogleSheetsError(_google_error_message(resp, "Ghi Google Sheet thất bại"))
        if self._http_client is not None:
            return await _do(self._http_client)
        async with httpx.AsyncClient(timeout=20) as client:
            return await _do(client)

    async def update_cells(self, *, credentials, spreadsheet_id, sheet_name, a1_range, values):
        normalized = normalize_service_account_credentials(credentials)
        sid = parse_spreadsheet_id(spreadsheet_id)
        async def _do(client):
            token = await self._access_token(client, normalized)
            rng = quote(f"'{sheet_name.replace(chr(39), chr(39)*2)}'!{a1_range}", safe="")
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{quote(sid, safe='')}/values/{rng}"
            resp = await client.put(url, headers={"Authorization": f"Bearer {token}"},
                params={"valueInputOption": "USER_ENTERED"}, json={"values": values})
            if resp.status_code >= 400:
                raise GoogleSheetsError(_google_error_message(resp, "Cập nhật Google Sheet thất bại"))
        if self._http_client is not None:
            return await _do(self._http_client)
        async with httpx.AsyncClient(timeout=20) as client:
            return await _do(client)
```

- [ ] **Step 4: Chạy test → PASS.**

Run: `cd backend && pytest tests/test_google_sheets_write.py -v`
Expected: PASS.

- [ ] **Step 5: Nối mirror vào sync (tùy chọn, an toàn).** Trong `rental_sync.py`, sau khi thêm phòng mới, nếu `cfg.google_sheet_connection_id` có giá trị: đọc `GoogleSheetConnection`, giải mã creds, gọi `append_rows` với các phòng vừa thêm. Bọc try/except riêng, lỗi Sheet **không** làm hỏng sync (chỉ log + ghi `last_error`). Thêm 1 test `test_sync_mirrors_to_sheet` dùng client giả.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/services/google_sheets.py backend/app/services/rental_sync.py backend/tests/test_google_sheets_write.py backend/tests/test_rental_sync.py
git commit -m "feat(rental): ghi Google Sheet (append/update) + mirror khi sync"
```

---

## Task 9: Nối worker vào scheduler

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_rental_scheduler.py`

**Interfaces:**
- Produces: `async run_rental_sync() -> None` và `async run_rental_posting() -> None` (module-level trong `main.py` hoặc `rental_sync`/`rental_post`), được gọi trong `_scheduler_tick()`.

- [ ] **Step 1: Viết test gọi được + không ném lỗi khi không có config.**

```python
# backend/tests/test_rental_scheduler.py
import pytest
from app.services.rental_sync import run_rental_sync
from app.services.rental_post import run_rental_posting

@pytest.mark.asyncio
async def test_runners_no_config_ok():
    await run_rental_sync()       # không có config -> không lỗi
    await run_rental_posting()
```

- [ ] **Step 2: Chạy test → FAIL** (`run_rental_sync` chưa có).

Run: `cd backend && pytest tests/test_rental_scheduler.py -v`
Expected: FAIL.

- [ ] **Step 3: Thêm hàm module-level.** Trong `rental_sync.py`:

```python
async def run_rental_sync() -> None:
    from datetime import datetime, timezone
    from app.db.postgres import session_context
    now = datetime.now(timezone.utc)
    async with session_context() as session:
        from sqlalchemy import select
        configs = list((await session.execute(select(RentalConfig).where(RentalConfig.status != "paused"))).scalars())
    svc = RentalSyncService(session_context)
    for cfg in configs:
        due = cfg.last_synced_at is None or (now - cfg.last_synced_at).total_seconds() >= cfg.poll_interval_seconds
        if due:
            try:
                await svc.sync_config(cfg.id)
            except Exception:
                logger.exception("rental sync failed for %s", cfg.id)
```

Trong `rental_post.py`:

```python
async def run_rental_posting() -> None:
    from app.db.postgres import session_context
    try:
        await RentalPostService(session_context).post_due()
    except Exception:
        logger.exception("rental posting failed")
```

- [ ] **Step 4: Móc vào `_scheduler_tick`.** Trong `app/main.py`, trong `_scheduler_tick()` sau `enqueue_due_posts()`:

```python
            from app.services.rental_sync import run_rental_sync
            from app.services.rental_post import run_rental_posting
            await run_rental_sync()
            await run_rental_posting()
```

(giữ trong cùng `try/except` đang có để lỗi không làm chết vòng lặp).

- [ ] **Step 5: Chạy test → PASS.**

Run: `cd backend && pytest tests/test_rental_scheduler.py -v`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add backend/app/main.py backend/app/services/rental_sync.py backend/app/services/rental_post.py backend/tests/test_rental_scheduler.py
git commit -m "feat(rental): móc sync/post worker vào scheduler tick"
```

---

## Task 10: Router `rental.py` + quyền RBAC

**Files:**
- Create: `backend/app/routers/rental.py`
- Modify: `backend/app/rbac_catalog.py` (thêm quyền `rental:read/create/update/delete`)
- Modify: `backend/app/main.py` (đăng ký router)
- Test: `backend/tests/integration/test_rental_api.py`

**Interfaces:**
- Produces: các endpoint dưới prefix `/api/rental`:
  - `GET /configs`, `POST /configs`, `PUT /configs/{id}`, `DELETE /configs/{id}`
  - `POST /configs/{id}/test-login` (thử đăng nhập nhatrovn)
  - `POST /configs/{id}/sync-now`, `POST /configs/{id}/post-now`
  - `GET /configs/{id}/rooms`
  - `POST /rooms/{room_id}/assign-groups` (body: `{group_ids: [...]}` → set `matched_group_ids_json`, status `new`)
  - `POST /rooms/{room_id}/skip`, `POST /rooms/{room_id}/retry`
- Consumes: services Task 4/6/7, models Task 2, `require_permission`.

- [ ] **Step 1: Thêm quyền vào catalog.** Trong `app/rbac_catalog.py`, thêm `rental:read`, `rental:create`, `rental:update`, `rental:delete` theo đúng cấu trúc các quyền `google_sheet:*` hiện có (cấp cho role admin mặc định như google_sheet).

- [ ] **Step 2: Viết integration test.**

```python
# backend/tests/integration/test_rental_api.py
import pytest

@pytest.mark.asyncio
async def test_create_list_config(async_client, auth_headers):
    body = {"name":"Trọ Gò Vấp","credentials":{"u":"user","p":"pass"},
        "province_code":"79","province_name":"HCM","district_code":"764","district_name":"Gò Vấp",
        "caption_template":"{title}","contact_phone":"0900","post_spacing_seconds":600,"poll_interval_seconds":300}
    r = await async_client.post("/api/rental/configs", json=body, headers=auth_headers)
    assert r.status_code == 201
    cid = r.json()["id"]
    r2 = await async_client.get("/api/rental/configs", headers=auth_headers)
    assert any(c["id"] == cid for c in r2.json())

@pytest.mark.asyncio
async def test_assign_groups_sets_new(async_client, auth_headers, seed_waiting_room):
    rid = seed_waiting_room
    r = await async_client.post(f"/api/rental/rooms/{rid}/assign-groups", json={"group_ids":["10"]}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "new"
```

Dùng fixture `async_client`, `auth_headers` theo pattern các test integration hiện có (`tests/integration/`). `seed_waiting_room` tạo config + room `waiting_groups`.

- [ ] **Step 3: Chạy test → FAIL.**

Run: `cd backend && pytest tests/integration/test_rental_api.py -v`
Expected: FAIL (404 / router chưa có).

- [ ] **Step 4: Viết router.** Tạo `app/routers/rental.py` theo mẫu `google_sheets.py`: mã hoá `credentials` bằng `encrypt(json.dumps({"u":...,"p":...}))`, CRUD `RentalConfig` (lọc theo `user.id`), `sync-now` gọi `RentalSyncService(session_context).sync_config`, `post-now` gọi `RentalPostService(session_context).post_due`, `assign-groups`/`skip`/`retry` cập nhật `RentalRoom` (kiểm tra quyền sở hữu qua `config.user_id == user.id`). `test-login` gọi `NhatrovnAdapter().login` và trả `{ok: true}` hoặc 400 với thông báo lỗi. Trả DTO không chứa `source_credentials_enc`.

- [ ] **Step 5: Đăng ký router.** Trong `app/main.py`: `from app.routers import rental` và `app.include_router(rental.router)` cạnh các router khác.

- [ ] **Step 6: Chạy test → PASS.**

Run: `cd backend && pytest tests/integration/test_rental_api.py -v`
Expected: PASS.

- [ ] **Step 7: Chạy toàn bộ test backend.**

Run: `cd backend && pytest -q`
Expected: PASS toàn bộ (không hỏng test cũ).

- [ ] **Step 8: Commit.**

```bash
git add backend/app/routers/rental.py backend/app/rbac_catalog.py backend/app/main.py backend/tests/integration/test_rental_api.py
git commit -m "feat(rental): API config/rooms + quyền RBAC + đăng ký router"
```

---

## Task 11: Frontend — API client + kiểu dữ liệu

**Files:**
- Modify: `frontend/src/lib/api-client.ts`
- Modify: `frontend/src/types` (thêm kiểu `RentalConfig`, `RentalRoom` nếu dự án tách types)

**Interfaces:**
- Produces: các hàm `listRentalConfigs()`, `createRentalConfig(body)`, `updateRentalConfig(id, body)`, `deleteRentalConfig(id)`, `testRentalLogin(id)`, `syncRentalNow(id)`, `postRentalNow(id)`, `listRentalRooms(id)`, `assignRoomGroups(roomId, groupIds)`, `skipRoom(roomId)`, `retryRoom(roomId)` — theo đúng phong cách các hàm API hiện có trong `api-client.ts`.

- [ ] **Step 1: Đọc pattern hiện có.** Xem cách `api-client.ts` gọi các endpoint google-sheets/page-tasks (base URL, header auth, xử lý lỗi) để bắt chước.

- [ ] **Step 2: Thêm kiểu + hàm.** Thêm `RentalConfig`/`RentalRoom` type và các hàm gọi `/api/rental/...` khớp router Task 10, dùng cùng helper fetch/`request` có sẵn.

- [ ] **Step 3: Typecheck.**

Run: `cd frontend && npx tsc --noEmit`
Expected: không lỗi type ở `api-client.ts`.

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/lib/api-client.ts frontend/src/types
git commit -m "feat(rental): frontend api-client cho rental"
```

---

## Task 12: Frontend — Trang "Đăng trọ tự động"

**Files:**
- Create: `frontend/src/app/tro/page.tsx` (đặt đúng theo cấu trúc route hiện có; nếu dùng route group thì theo mẫu trang google-sheets/tasks hiện có)
- Modify: `frontend/src/components/layout/SideNav.tsx` (thêm mục "Đăng trọ tự động")

**Interfaces:**
- Consumes: hàm API Task 11.

- [ ] **Step 1: Thêm link SideNav.** Thêm một mục điều hướng tới `/tro` theo mẫu các mục hiện có trong `SideNav.tsx`.

- [ ] **Step 2: Dựng trang.** Trang gồm 2 khối:
  - **Danh sách + form cấu hình:** tạo/sửa config (tài khoản nhatrovn, chọn Tỉnh→Quận→Phường, nhịp giãn cách, caption + hashtag, contact_phone, bật/tắt auto_post, chọn Google Sheet mirror tùy chọn); nút "Test đăng nhập", "Đồng bộ ngay".
  - **Bảng phòng:** cột mã phòng, tiêu đề, quận, trạng thái (badge: mới/đã đăng/lỗi/chờ gán nhóm), link bài; nút "Gán nhóm" (mở chọn nhóm từ danh sách `FacebookGroup`) cho phòng `waiting_groups`, nút "Bỏ qua"/"Thử lại".

  Dùng component UI theo mẫu trang hiện có (bảng, form, badge). Danh sách Tỉnh/Quận/Phường: dùng nguồn đã chốt ở Task 1 (nếu nhatrovn cấp endpoint danh mục thì gọi; nếu không, nhúng danh sách đơn vị hành chính tĩnh — quyết định khi làm).

- [ ] **Step 3: Build kiểm tra.**

Run: `cd frontend && npm run build`
Expected: build thành công, trang `/tro` render được.

- [ ] **Step 4: Kiểm thử thủ công.** Chạy backend + frontend, tạo 1 config (khu vực thật), bấm "Test đăng nhập" (kỳ vọng ok), "Đồng bộ ngay" (kỳ vọng phòng xuất hiện trong bảng), gán nhóm cho 1 phòng `waiting_groups`, bấm "Đăng ngay" một lượt và kiểm tra bài lên đúng nhóm. Ghi lại kết quả.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/app/tro/page.tsx frontend/src/components/layout/SideNav.tsx
git commit -m "feat(rental): trang Đăng trọ tự động (cấu hình + bảng phòng)"
```

---

## Self-Review (đã thực hiện)

- **Spec coverage:** Adapter login+search+parse (T1,3,4) · DB model + migration (T2) · khớp nhóm theo quận (T5) · sync/dedup/caption/hashtag (T6) · đăng giãn cách + retry + chống đăng đôi (T7) · mirror Google Sheet (T8) · scheduler wiring (T9) · API + RBAC + gán nhóm tay (T10) · trang riêng + chọn khu vực (T11,12). Van an toàn `paused`/`skip`/`post_delay` có trong model + services. ✔
- **Placeholder scan:** Các chỗ "chỉnh theo Task 1" là phần reverse-engineer thật (selector/param) được chốt trong Task 1 và có fixture + test kiểm chứng — không phải placeholder logic. ✔
- **Type consistency:** `Room` dùng nhất quán (T3→T4→T6); `sync_config`, `post_due`, `append_rows/update_cells`, `match_group_ids`, `render_caption` khớp chữ ký giữa các task. ✔

## Rủi ro cần chú ý khi thực thi

1. **Task 1 là điểm chặn:** nếu cổng có OTP/captcha, `login` không tự động được → chuyển sang phương án dán cookie (đổi `source_credentials_enc` thành cookie + hàm `from_cookie`); các task sau hầu như không đổi.
2. **conftest fixtures:** một số test giả định fixture `session_factory`/`a_user`/`async_client`/`auth_headers`. Nếu conftest hiện chưa có, bổ sung ở Task 6 (backend) / Task 10 (integration) theo pattern có sẵn trước khi viết test.
3. **`_run_page_post_task` chữ ký:** xác nhận tham số thật (`run_id, page_ids, group_ids, personal_account_ids, message, link, media_paths`) trong `page_tasks.py` trước Task 7; điều chỉnh lời gọi nếu khác.
