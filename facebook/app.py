import json
import mimetypes
import queue
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from tkinter import BooleanVar, Canvas, END, filedialog, messagebox, StringVar, Text, Tk
from tkinter import ttk
from typing import List, Dict

try:
    from browser import PlaywrightManager
except ImportError:
    PlaywrightManager = None

APP_DIR = Path.home() / ".ucmas_facebook_poster"
CONFIG_PATH = APP_DIR / "config.json"
DB_PATH = APP_DIR / "poster.db"
GRAPH_VERSION = "v20.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"

UCMAS_PROMPT = """Viết một bài Facebook cho Fanpage trung tâm UCMAS/toán tư duy.

Đối tượng: phụ huynh có con từ 5 đến 10 tuổi.
Mục tiêu: thu hút phụ huynh inbox đăng ký học thử.
Chủ đề: vì sao trẻ nên rèn khả năng tập trung và tư duy logic thông qua toán tư duy.
Giọng điệu: ấm áp, chuyên nghiệp, gần gũi, không quá bán hàng.
Độ dài: 150 đến 250 từ.
Nội dung bắt buộc: UCMAS, toán tư duy, khả năng tập trung, tư duy logic, học thử.
Không được: cam kết điểm cao, nói trẻ sẽ giỏi ngay, nói quá về IQ, dùng quá 6 hashtag.
CTA: mời phụ huynh inbox để được tư vấn lộ trình và đăng ký buổi học thử cho con.

Trả về: caption hoàn chỉnh, phiên bản ngắn hơn, gợi ý hình ảnh/video, hashtag."""


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = Canvas(self, highlightthickness=0, borderwidth=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_inner_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)


@dataclass
class FacebookPage:
    """Page từ một Facebook Account"""
    id: str
    name: str
    access_token: str
    permissions: List[str] = field(default_factory=list)
    category: str = ""
    account_id: str = ""
    selected: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "access_token": self.access_token,
            "permissions": self.permissions,
            "category": self.category,
            "account_id": self.account_id,
            "selected": self.selected
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data["id"],
            name=data["name"],
            access_token=data["access_token"],
            permissions=data.get("permissions", []),
            category=data.get("category", ""),
            account_id=data.get("account_id", ""),
            selected=data.get("selected", False)
        )


@dataclass
class FacebookAccount:
    """User Facebook Account với nhiều pages"""
    id: str
    name: str
    user_token: str
    pages: List[FacebookPage] = field(default_factory=list)
    selected: bool = False
    post_to_personal: bool = False
    browser_profile_path: str = ""
    is_browser_logged_in: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "user_token": self.user_token,
            "pages": [p.to_dict() for p in self.pages],
            "selected": self.selected,
            "post_to_personal": self.post_to_personal,
            "browser_profile_path": self.browser_profile_path,
            "is_browser_logged_in": self.is_browser_logged_in
        }

    @classmethod
    def from_dict(cls, data):
        pages = [FacebookPage.from_dict(p) for p in data.get("pages", [])]
        return cls(
            id=data["id"],
            name=data["name"],
            user_token=data["user_token"],
            pages=pages,
            selected=data.get("selected", False),
            post_to_personal=data.get("post_to_personal", False),
            browser_profile_path=data.get("browser_profile_path", ""),
            is_browser_logged_in=data.get("is_browser_logged_in", False)
        )


def ensure_app_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    ensure_app_dirs()
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(config):
    ensure_app_dirs()
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")




def _page_to_dict(page):
    return page.to_dict()


def _dict_to_page(data):
    return FacebookPage.from_dict(data)

def migrate_old_config(config):
    """Convert old config formats to multi-account format"""
    # Nếu đã có accounts list, không cần migrate
    if "accounts" in config and isinstance(config["accounts"], list):
        return config

    # Tạo accounts list rỗng
    accounts = []

    # Migration từ old single page config
    if config.get("page_id") and config.get("access_token"):
        # Lấy user info không có → tạo account giả
        accounts.append({
            "id": "legacy_single_page",
            "name": config.get("page_name", "Legacy Account"),
            "user_token": "",
            "pages": [{
                "id": config["page_id"],
                "name": config.get("page_name", config["page_id"]),
                "access_token": config["access_token"],
                "permissions": [],
                "category": "",
                "account_id": "legacy_single_page",
                "selected": True
            }],
            "selected": True
        })

    # Migration từ old multiple pages (pages_text)
    if config.get("pages_text"):
        # Không thể lấy user token từ pages_text → tạo account giả
        pages = []
        lines = config["pages_text"].strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                page_id = parts[0]
                name = parts[2] if len(parts) >= 3 and parts[2] else page_id
                token = parts[1]
                pages.append({
                    "id": page_id,
                    "name": name,
                    "access_token": token,
                    "permissions": [],
                    "category": "",
                    "account_id": "legacy_multi_pages",
                    "selected": True
                })
        if pages:
            accounts.append({
                "id": "legacy_multi_pages",
                "name": "Legacy Multi-Pages",
                "user_token": "",
                "pages": pages,
                "selected": True
            })

    config["accounts"] = accounts

    # Remove legacy fields
    config.pop("page_id", None)
    config.pop("page_name", None)
    config.pop("access_token", None)
    config.pop("pages_text", None)
    config.pop("remember_token", None)
    config.pop("post_to_all_pages", None)

    return config


class Store:
    def __init__(self):
        ensure_app_dirs()
        with self._connect() as conn:
            conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                scheduled_at TEXT,
                post_type TEXT NOT NULL,
                message TEXT NOT NULL,
                media_path TEXT,
                status TEXT NOT NULL,
                facebook_id TEXT,
                error TEXT
            )
            """
            )
            self._ensure_column(conn, "scheduled_at", "TEXT")

    def _connect(self):
        return sqlite3.connect(DB_PATH)

    def _ensure_column(self, conn, column, column_type):
        columns = [row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()]
        if column not in columns:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {column} {column_type}")

    def add_post(self, post_type, message, media_path, status, facebook_id="", error="", scheduled_at=""):
        with self._connect() as conn:
            cur = conn.execute(
            """
            INSERT INTO posts (created_at, scheduled_at, post_type, message, media_path, status, facebook_id, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                scheduled_at,
                post_type,
                message,
                media_path,
                status,
                facebook_id,
                error,
            ),
            )
            return cur.lastrowid

    def latest_posts(self):
        with self._connect() as conn:
            return conn.execute(
            """
            SELECT created_at, scheduled_at, post_type, status, facebook_id, error, substr(message, 1, 120)
            FROM posts
            ORDER BY id DESC
            LIMIT 100
            """
            ).fetchall()

    def recent_messages(self, limit=50):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT message FROM posts
                WHERE status IN ('posted', 'scheduled', 'draft')
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [row[0] for row in rows]

    def due_scheduled_posts(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT id, post_type, message, media_path
                FROM posts
                WHERE status = 'scheduled' AND scheduled_at <= ?
                ORDER BY scheduled_at ASC
                LIMIT 1
                """,
                (now,),
            ).fetchall()

    def update_post_status(self, post_id, status, facebook_id="", error=""):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE posts
                SET status = ?, facebook_id = ?, error = ?
                WHERE id = ?
                """,
                (status, facebook_id, error, post_id),
            )


@dataclass
class ApiResult:
    ok: bool
    data: dict
    error: str = ""


class FacebookApi:
    GRAPH_BASE = "https://graph.facebook.com/v20.0"

    @staticmethod
    def _read_response(req):
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return ApiResult(True, json.loads(raw or "{}"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw)
                error = data.get("error", {})
                error_msg = error.get("message", raw)

                # Build detailed error message
                details = []
                details.append(f"Lỗi Facebook API:")
                details.append(f"  • Message: {error.get('message', 'N/A')}")
                details.append(f"  • Type: {error.get('type', 'N/A')}")
                details.append(f"  • Code: {error.get('code', 'N/A')}")
                if 'fbtrace_id' in error:
                    details.append(f"  • Trace ID: {error['fbtrace_id']}")

                # Add troubleshooting hints based on error code
                code = error.get('code')
                message = error.get('message', '').lower()
                hints = []
                if code == 190:
                    hints.append("Token hết hạn/không hợp lệ -> Đổi User Token sang long-lived token rồi tải lại Pages")
                elif code == 200:
                    hints.append("Thiếu quyền → Thêm permissions pages_read_engagement, pages_manage_posts")
                elif code == 803:
                    hints.append("Page ID không tồn tại → Kiểm tra lại Page ID")
                elif code == 100:
                    hints.append("Parameter sai → Kiểm tra Page ID format")

                if hints:
                    details.append(f"\nGợi ý: {' | '.join(hints)}")

                return ApiResult(False, {}, "\n".join(details))
            except Exception:
                return ApiResult(False, {}, raw or str(exc))
        except Exception as exc:
            return ApiResult(False, {}, str(exc))

    @staticmethod
    def get_user_info(user_token):
        """Lấy thông tin user (ID, tên)"""
        params = urllib.parse.urlencode({
            "fields": "id,name",
            "access_token": user_token
        })
        req = urllib.request.Request(f"{GRAPH_BASE}/me?{params}", method="GET")
        return FacebookApi._read_response(req)

    @staticmethod
    def exchange_long_lived_user_token(user_token, app_id, app_secret):
        """Exchange a short-lived user token for a long-lived user token."""
        params = urllib.parse.urlencode({
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": user_token,
        })
        req = urllib.request.Request(f"{GRAPH_BASE}/oauth/access_token?{params}", method="GET")
        return FacebookApi._read_response(req)

    @staticmethod
    def get_my_pages(user_token):
        """
        Lấy danh sách tất cả Pages mà user là admin/editor.
        IMPORTANT: Lấy cả page access token và permissions!
        fields: id,name,access_token,tasks,category,picture

        Returns: ApiResult với data là list[dict]
        """
        params = urllib.parse.urlencode({
            "fields": "id,name,access_token,tasks,category,picture",
            "access_token": user_token
        })
        req = urllib.request.Request(f"{GRAPH_BASE}/me/accounts?{params}", method="GET")
        result = FacebookApi._read_response(req)

        if not result.ok:
            return result

        pages = []
        for item in result.data.get("data", []):
            page = {
                "id": item["id"],
                "name": item["name"],
                "access_token": item["access_token"],
                "permissions": item.get("tasks", item.get("perms", [])),
                "category": item.get("category", ""),
                "picture": item.get("picture", {}).get("data", {}).get("url", "")
            }
            pages.append(page)

        result.data = pages
        return result

    @staticmethod
    def post_text(page_id, token, message):
        data = urllib.parse.urlencode({"message": message, "access_token": token}).encode("utf-8")
        req = urllib.request.Request(f"{GRAPH_BASE}/{page_id}/feed", data=data, method="POST")
        return FacebookApi._read_response(req)

    @staticmethod
    def post_photo(page_id, token, message, media_path):
        return FacebookApi._multipart_post(
            f"{GRAPH_BASE}/{page_id}/photos",
            {"caption": message, "access_token": token},
            "source",
            media_path,
        )

    @staticmethod
    def upload_photo_unpublished(page_id, token, media_path):
        return FacebookApi._multipart_post(
            f"{GRAPH_BASE}/{page_id}/photos",
            {"published": "false", "access_token": token},
            "source",
            media_path,
        )

    @staticmethod
    def post_photo_album(page_id, token, message, media_paths):
        media_fbids = []
        for media_path in media_paths:
            result = FacebookApi.upload_photo_unpublished(page_id, token, media_path)
            if not result.ok:
                return result
            media_id = result.data.get("id")
            if not media_id:
                return ApiResult(False, {}, f"Facebook did not return photo id for {media_path}")
            media_fbids.append(media_id)

        data = {
            "message": message,
            "access_token": token,
        }
        for idx, media_id in enumerate(media_fbids):
            data[f"attached_media[{idx}]"] = json.dumps({"media_fbid": media_id})
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(f"{GRAPH_BASE}/{page_id}/feed", data=encoded, method="POST")
        return FacebookApi._read_response(req)

    @staticmethod
    def post_video(page_id, token, message, media_path):
        return FacebookApi._multipart_post(
            f"{GRAPH_BASE}/{page_id}/videos",
            {"description": message, "access_token": token},
            "source",
            media_path,
        )

    @staticmethod
    def _multipart_post(url, fields, file_field, file_path):
        boundary = f"----ucmasposter{uuid.uuid4().hex}"
        parts = []
        for key, value in fields.items():
            parts.append(f"--{boundary}\r\n".encode())
            parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            parts.append(str(value).encode("utf-8"))
            parts.append(b"\r\n")

        path = Path(file_path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            (
                f'Content-Disposition: form-data; name="{file_field}"; filename="{path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        parts.append(path.read_bytes())
        parts.append(b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)

        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("Content-Length", str(len(body)))
        return FacebookApi._read_response(req)


class GeminiApi:
    @staticmethod
    def generate(api_key, model, system_instruction, user_prompt):
        model = model.strip() or DEFAULT_GEMINI_MODEL
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={urllib.parse.quote(api_key)}"
        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.85,
                "topP": 0.9,
                "maxOutputTokens": 1200,
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        result = FacebookApi._read_response(req)
        if not result.ok:
            return result
        try:
            parts = result.data["candidates"][0]["content"]["parts"]
            text = "\n".join(part.get("text", "") for part in parts).strip()
            return ApiResult(True, {"text": text})
        except Exception:
            return ApiResult(False, {}, "Không đọc được phần trả lời từ Gemini.")




class ContentGuard:
    RISKY_PHRASES = [
        "chac chan gioi",
        "gioi ngay",
        "dam bao diem cao",
        "cam ket diem cao",
        "tang iq",
        "thien tai",
        "hoc 1 buoi la",
        "100%",
    ]

    @staticmethod
    def check(message, previous_messages):
        warnings = []
        normalized = " ".join(message.lower().split())
        hashtags = [word for word in message.split() if word.startswith("#")]
        if len(hashtags) > 6:
            warnings.append(f"Co {len(hashtags)} hashtag, nen giu 3-6 hashtag.")
        if len(message) > 2200:
            warnings.append("Bai viet kha dai, nen rut gon de phu huynh de doc tren dien thoai.")
        for phrase in ContentGuard.RISKY_PHRASES:
            if phrase in normalized:
                warnings.append(f"Co cum tu de bi xem la noi qua: '{phrase}'.")
        for old in previous_messages:
            ratio = SequenceMatcher(None, normalized, " ".join(old.lower().split())).ratio()
            if ratio >= 0.72:
                warnings.append("Noi dung qua giong bai da luu/dang gan day, nen viet lai truoc khi dang.")
                break
        cta_count = sum(normalized.count(cta) for cta in ["inbox", "dang ky", "hoc thu", "nhan tin"])
        if cta_count > 4:
            warnings.append("CTA lap lai nhieu lan, nen giu loi moi hanh dong nhe hon.")
        return warnings


def page_key(account_id, page_id):
    return f"{account_id}:{page_id}"


class PosterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("UCMAS Facebook Poster - Multi-Account")
        self.root.geometry("1250x850")
        self.root.minsize(1100, 760)
        self.store = Store()

        # Load và migrate config
        raw_config = load_config()
        self.config = migrate_old_config(raw_config)

        self.events = queue.Queue()

        # Load accounts từ config
        self.accounts = []
        self._load_accounts_from_config()

        # UI state variables
        self.status_text = StringVar(value="Sẵn sàng")
        self.media_path = StringVar(value="")
        self.media_paths = []
        self.post_type = StringVar(value="text")
        self.gemini_key = StringVar(value=self.config.get("gemini_key", ""))
        self.gemini_model = StringVar(value=self.config.get("gemini_model", DEFAULT_GEMINI_MODEL))
        self.gemini_url = StringVar(value=self.config.get("gemini_url", "https://gemini.google.com/app"))
        self.facebook_app_id = StringVar(value=self.config.get("facebook_app_id", ""))
        self.facebook_app_secret = StringVar(value=self.config.get("facebook_app_secret", ""))
        self.ai_topic = StringVar(value="Viết bài thu hút phụ huynh đăng ký học thử UCMAS cho con 5-10 tuổi")
        self.schedule_time = StringVar(value=(datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"))

        # New account form variables
        self.new_account_token = StringVar()
        self.new_account_name = StringVar()

        # Account/Page selection tracking
        self.account_vars = {}  # account_id -> BooleanVar
        self.page_vars = {}     # page_id -> BooleanVar

        # UI references (will be set in _build_ui)
        self.accounts_container = None
        self.pages_container = None
        self.pages_count_label = None
        self.message_box = None
        self.pages_text_widget = None  # For legacy compatibility

        self._build_ui()
        self._refresh_accounts_ui()
        self._refresh_pages_ui()
        self.refresh_history()
        self.root.after(150, self._process_events)
        self.root.after(30000, self._scheduler_tick)

    def _load_accounts_from_config(self):
        """Load accounts from config"""
        accounts_data = self.config.get("accounts", [])
        self.accounts = []
        for acc_data in accounts_data:
            try:
                account = FacebookAccount.from_dict(acc_data)
                self.accounts.append(account)
            except Exception as e:
                print(f"Warning: Failed to load account {acc_data.get('id')}: {e}")

    def _refresh_accounts_ui(self):
        """Rebuild accounts list with visible checkboxes."""
        if not self.accounts_container:
            return

        for widget in self.accounts_container.winfo_children():
            widget.destroy()

        if not self.accounts:
            ttk.Label(self.accounts_container, text="Chưa có Accounts nào. Hãy thêm account bên trên.").pack(anchor="w", pady=6)
            self._update_status_count()
            return

        for account in self.accounts:
            var = self.account_vars.get(account.id)
            if var is None:
                var = BooleanVar(value=account.selected)
                self.account_vars[account.id] = var
            else:
                var.set(account.selected)

            row = ttk.Frame(self.accounts_container)
            row.pack(fill="x", pady=2)

            text = f"{account.name} (ID: {account.id}) - {len(account.pages)} pages"
            
            # Khôi phục trạng thái login
            if PlaywrightManager:
                account.is_browser_logged_in = PlaywrightManager.check_is_logged_in(account.id)
                status_text = "✅ Đã đăng nhập Trình duyệt" if account.is_browser_logged_in else "❌ Chưa đăng nhập Trình duyệt"
            else:
                status_text = "⚠️ Chưa cài Playwright"

            ttk.Checkbutton(
                row,
                text=text,
                variable=var,
                command=lambda acc=account, v=var: self._on_account_toggle(acc, v),
            ).pack(side="left", anchor="w")

            ttk.Label(row, text=f"[{status_text}]").pack(side="left", padx=10)

            if PlaywrightManager:
                ttk.Button(row, text="🔌 Đăng nhập Trình duyệt", command=lambda acc=account: self._open_browser_login(acc)).pack(side="left", padx=(0, 5))

            ttk.Button(row, text="🗑 Xóa", command=lambda acc=account: self._delete_single_account(acc)).pack(side="left")

        self._update_status_count()

    def _on_account_toggle(self, account, var):
        """Sync account checkbox with account.selected."""
        account.selected = var.get()
        self._refresh_pages_ui()
        self._update_status_count()

    def _open_browser_login(self, account):
        """Open Playwright browser for the user to login to Facebook"""
        if not PlaywrightManager:
            messagebox.showerror("Lỗi", "Chưa cài đặt thư viện Playwright.")
            return
            
        def login_thread():
            self.status_text.set(f"Đang mở trình duyệt cho {account.name}...")
            try:
                PlaywrightManager.login_account(account.id)
                self.after(0, lambda: self._on_browser_login_success(account))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Lỗi", f"Không thể mở trình duyệt: {str(e)}"))
                self.status_text.set("Sẵn sàng")

        threading.Thread(target=login_thread, daemon=True).start()

    def _on_browser_login_success(self, account):
        account.is_browser_logged_in = True
        self.save_settings()
        self._refresh_accounts_ui()
        self._refresh_pages_ui()
        self.status_text.set("Đã đóng trình duyệt đăng nhập.")

    def _select_all_accounts(self):
        """Select all accounts"""
        for account in self.accounts:
            account.selected = True
            self.account_vars[account.id] = BooleanVar(value=True)
        self._refresh_accounts_ui()
        self._refresh_pages_ui()

    def _deselect_all_accounts(self):
        """Deselect all accounts"""
        for account in self.accounts:
            account.selected = False
            self.account_vars[account.id] = BooleanVar(value=False)
        self._refresh_accounts_ui()
        self._refresh_pages_ui()

    def _refresh_pages_ui(self):
        """Rebuild pages list grouped by selected accounts"""
        if not self.pages_container:
            return

        # Clear container
        for widget in self.pages_container.winfo_children():
            widget.destroy()

        selected_accounts = [acc for acc in self.accounts if acc.selected]
        if not selected_accounts:
            ttk.Label(self.pages_container, text="Chưa chọn account nào. Chọn accounts từ danh sách bên trên.").pack(pady=20)
            self._update_status_count()
            return

        # Create a frame for each selected account
        for account in selected_accounts:
            acc_frame = ttk.LabelFrame(self.pages_container, text=f"📘 {account.name}", padding=8)
            acc_frame.pack(fill="x", pady=(0, 8))

            # Personal account checkbox
            personal_key = f"personal:{account.id}"
            personal_var = self.page_vars.get(personal_key)
            if personal_var is None:
                personal_var = BooleanVar(value=account.post_to_personal)
                self.page_vars[personal_key] = personal_var
            else:
                personal_var.set(account.post_to_personal)

            cb_personal = ttk.Checkbutton(
                acc_frame,
                text=f"Đăng lên Profile cá nhân ({account.name})" + (" (Cần đăng nhập Trình duyệt)" if not account.is_browser_logged_in else ""),
                variable=personal_var,
                command=lambda acc=account, v=personal_var: self._on_personal_toggle(acc, v)
            )
            cb_personal.pack(anchor="w", pady=(2, 6))
            
            if not account.is_browser_logged_in:
                cb_personal.state(['disabled'])
                personal_var.set(False)
                account.post_to_personal = False

            if not account.pages:
                ttk.Label(acc_frame, text="Không có pages nào trong account này.").pack(pady=5)
                continue

            # Pages checkboxes
            for page in account.pages:
                key = page_key(account.id, page.id)
                var = self.page_vars.get(key)
                if var is None:
                    var = BooleanVar(value=page.selected)
                    self.page_vars[key] = var

                cb = ttk.Checkbutton(
                    acc_frame,
                    text=f"{page.name} (ID: {page.id})",
                    variable=var,
                    command=lambda p=page, v=var: self._on_page_toggle(p, v)
                )
                cb.pack(anchor="w", pady=2)

        self._update_status_count()

    def _on_page_toggle(self, page, var):
        """Handle page checkbox toggle"""
        page.selected = var.get()
        self._update_status_count()

    def _on_personal_toggle(self, account, var):
        """Handle personal profile checkbox toggle"""
        account.post_to_personal = var.get()
        self._update_status_count()

    def _update_status_count(self):
        """Update selected pages count in status"""
        selected_pages = sum(1 for acc in self.accounts for p in acc.pages if p.selected)
        selected_pages += sum(1 for acc in self.accounts if acc.post_to_personal)
        
        total_pages = sum(len(acc.pages) for acc in self.accounts)
        total_pages += sum(1 for acc in self.accounts)
        
        selected_accounts = sum(1 for acc in self.accounts if acc.selected)

        if self.pages_count_label:
            self.pages_count_label.config(text=f"Đã chọn: {selected_pages}/{total_pages} nơi đăng từ {selected_accounts} accounts")

    def _select_all_pages(self):
        """Select all pages from selected accounts"""
        for account in self.accounts:
            if account.selected:
                account.post_to_personal = True
                personal_key = f"personal:{account.id}"
                if personal_key not in self.page_vars:
                    self.page_vars[personal_key] = BooleanVar(value=True)
                else:
                    self.page_vars[personal_key].set(True)
                
                for page in account.pages:
                    page.selected = True
                    key = page_key(account.id, page.id)
                    if key not in self.page_vars:
                        self.page_vars[key] = BooleanVar(value=True)
                    else:
                        self.page_vars[key].set(True)
        self._refresh_pages_ui()

    def _deselect_all_pages(self):
        """Deselect all pages from selected accounts"""
        for account in self.accounts:
            if account.selected:
                account.post_to_personal = False
                personal_key = f"personal:{account.id}"
                if personal_key not in self.page_vars:
                    self.page_vars[personal_key] = BooleanVar(value=False)
                else:
                    self.page_vars[personal_key].set(False)
                
                for page in account.pages:
                    page.selected = False
                    key = page_key(account.id, page.id)
                    if key not in self.page_vars:
                        self.page_vars[key] = BooleanVar(value=False)
                    else:
                        self.page_vars[key].set(False)
        self._refresh_pages_ui()

    def _exchange_new_account_token(self):
        """Exchange the token in the add-account form for a long-lived token."""
        token = self.new_account_token.get().strip()
        app_id = self.facebook_app_id.get().strip()
        app_secret = self.facebook_app_secret.get().strip()

        if not token:
            messagebox.showwarning("Thiếu token", "Hãy dán User Access Token trước.")
            return
        if not app_id or not app_secret:
            messagebox.showwarning("Thiếu App ID/Secret", "Hãy nhập Facebook App ID và App Secret.")
            return

        self.save_settings()
        self.status_text.set("Dang doi sang long-lived token...")
        threading.Thread(
            target=self._exchange_token_worker,
            args=(token, app_id, app_secret),
            daemon=True,
        ).start()

    def _exchange_token_worker(self, token, app_id, app_secret):
        result = FacebookApi.exchange_long_lived_user_token(token, app_id, app_secret)
        self.events.put(("token_exchanged", result))

    def _add_account(self):
        """Add new account from token"""
        token = self.new_account_token.get().strip()
        name = self.new_account_name.get().strip()

        if not token:
            messagebox.showwarning("Thiếu Token", "Hãy nhập User Access Token.")
            return

        self.status_text.set("Đang lấy thông tin account...")
        threading.Thread(target=self._add_account_worker, args=(token, name), daemon=True).start()

    def _add_account_worker(self, token, name):
        """Worker thread to add account"""
        # Thử đổi sang long-lived token tự động nếu có App ID & Secret
        app_id = self.facebook_app_id.get().strip()
        app_secret = self.facebook_app_secret.get().strip()
        final_token = token
        
        if app_id and app_secret:
            exchange_result = FacebookApi.exchange_long_lived_user_token(token, app_id, app_secret)
            if exchange_result.ok and exchange_result.data.get("access_token"):
                final_token = exchange_result.data["access_token"]
                # Thông báo đã đổi thành công
                self.status_text.set("✅ Đã tự động đổi sang Long-lived Token (60 ngày)")
            else:
                self.status_text.set("⚠️ Không đổi được Long-lived Token, dùng Short-lived Token (1-2 tiếng)")
        else:
            self.status_text.set("⚠️ Chưa có App ID/Secret → Token chỉ sống 1-2 tiếng!")

        # Get user info
        user_result = FacebookApi.get_user_info(final_token)
        if not user_result.ok:
            self.events.put(("add_account_error", f"Không lấy được user info: {user_result.error}"))
            return

        user_id = user_result.data.get("id")
        user_name = user_result.data.get("name", name or user_id)

        # Get pages
        pages_result = FacebookApi.get_my_pages(final_token)
        if not pages_result.ok:
            self.events.put(("add_account_error", f"Không lấy được pages: {pages_result.error}"))
            return

        # Create account object
        pages = []
        for page_data in pages_result.data:
            page = FacebookPage(
                id=page_data["id"],
                name=page_data["name"],
                access_token=page_data["access_token"],
                permissions=page_data.get("permissions", []),
                category=page_data.get("category", ""),
                account_id=user_id,
                selected=False
            )
            pages.append(page)

        account = FacebookAccount(
            id=user_id,
            name=user_name,
            user_token=final_token,
            pages=pages,
            selected=True
        )

        self.events.put(("account_added", account))

    def _remove_account(self):
        """Remove checked accounts."""
        selected_accounts = [acc for acc in self.accounts if acc.selected]
        if not selected_accounts:
            messagebox.showwarning("Chưa chọn", "Hãy tích account cần xóa.")
            return

        if not messagebox.askyesno("Xác nhận", f"Xóa {len(selected_accounts)} account đã tích?"):
            return

        selected_ids = {acc.id for acc in selected_accounts}
        self.accounts = [acc for acc in self.accounts if acc.id not in selected_ids]
        for account_id in selected_ids:
            self.account_vars.pop(account_id, None)
            for key in list(self.page_vars):
                if key.startswith(f"{account_id}:"):
                    self.page_vars.pop(key, None)

        self._refresh_accounts_ui()
        self._refresh_pages_ui()
        self.save_settings()

    def _delete_single_account(self, account):
        """Delete a single account directly."""
        if not messagebox.askyesno("Xác nhận", f"Bạn có chắc muốn xóa account '{account.name}'?"):
            return
            
        self.accounts = [acc for acc in self.accounts if acc.id != account.id]
        self.account_vars.pop(account.id, None)
        for key in list(self.page_vars):
            if key.startswith(f"{account.id}:"):
                self.page_vars.pop(key, None)
                
        self._refresh_accounts_ui()
        self._refresh_pages_ui()
        self.save_settings()

    def _reload_account_pages(self):
        """Reload pages for selected accounts"""
        selected_accounts = [acc for acc in self.accounts if acc.selected]
        if not selected_accounts:
            messagebox.showwarning("Chưa chọn", "Hãy chọn ít nhất 1 account để tải pages.")
            return

        self.status_text.set(f"Đang tải pages cho {len(selected_accounts)} accounts...")
        threading.Thread(target=self._reload_pages_worker, daemon=True).start()

    def _reload_pages_worker(self):
        """Worker to reload pages for selected accounts"""
        for account in self.accounts:
            if not account.selected:
                continue

            result = FacebookApi.get_my_pages(account.user_token)
            if result.ok:
                selected_by_id = {page.id: page.selected for page in account.pages}
                new_pages = []
                for page_data in result.data:
                    page = FacebookPage(
                        id=page_data["id"],
                        name=page_data["name"],
                        access_token=page_data["access_token"],
                        permissions=page_data.get("permissions", []),
                        category=page_data.get("category", ""),
                        account_id=account.id,
                        selected=selected_by_id.get(page_data["id"], False)
                    )
                    new_pages.append(page)
                account.pages = new_pages
                # Clear page vars for these pages
                for key in list(self.page_vars):
                    if key.startswith(f"{account.id}:"):
                        self.page_vars.pop(key, None)

        self.events.put(("pages_reloaded", None))

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", padding=(10, 6))
        style.configure("TLabel", padding=(2, 2))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"))

        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        top = ttk.Frame(container)
        top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="UCMAS Facebook Poster - Multi-Account", style="Header.TLabel").pack(side="left")
        ttk.Label(top, textvariable=self.status_text).pack(side="right")

        notebook = ttk.Notebook(container)
        notebook.pack(fill="both", expand=True)

        self.settings_tab = ttk.Frame(notebook, padding=12)
        self.compose_tab = ttk.Frame(notebook, padding=12)
        self.history_tab = ttk.Frame(notebook, padding=12)
        self.prompt_tab = ttk.Frame(notebook, padding=12)

        notebook.add(self.compose_tab, text="Soạn bài")
        notebook.add(self.settings_tab, text="Cấu hình Account")
        notebook.add(self.history_tab, text="Lịch sử")
        notebook.add(self.prompt_tab, text="Prompt UCMAS")

        self._build_settings_tab()
        self._build_compose_tab()
        self._build_history_tab()
        self._build_prompt_tab()

    def _build_settings_tab(self):
        """Build redesigned Settings tab with Multi-Account support"""
        self.settings_scroll = ScrollableFrame(self.settings_tab)
        self.settings_scroll.pack(fill="both", expand=True)
        main_frame = self.settings_scroll.inner

        # === Section 1: Thêm Account Mới ===
        add_account_frame = ttk.LabelFrame(main_frame, text="Thêm Facebook Account", padding=10)
        add_account_frame.pack(fill="x", pady=(0, 10))

        # User Access Token
        token_row = ttk.Frame(add_account_frame)
        token_row.pack(fill="x", pady=5)
        ttk.Label(token_row, text="User Access Token:", width=18).pack(side="left")
        token_entry = ttk.Entry(token_row, textvariable=self.new_account_token, width=60, show="*")
        token_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(token_row, text="👁", width=3, command=lambda: self._toggle_show(token_entry)).pack(side="left")

        # Account name (optional)
        name_row = ttk.Frame(add_account_frame)
        name_row.pack(fill="x", pady=5)
        ttk.Label(name_row, text="Tên Account:", width=18).pack(side="left")
        ttk.Entry(name_row, textvariable=self.new_account_name, width=60).pack(side="left", fill="x", expand=True)

        # Add button
        btn_row = ttk.Frame(add_account_frame)
        btn_row.pack(fill="x", pady=10)
        ttk.Button(btn_row, text="➕ Thêm Account", command=self._add_account).pack(side="left")

        # === Section 2: Danh sách Accounts ===
        accounts_frame = ttk.LabelFrame(main_frame, text="Danh sách Accounts", padding=10)
        accounts_frame.pack(fill="both", expand=True, pady=(0, 10))

        # Accounts controls
        acc_control = ttk.Frame(accounts_frame)
        acc_control.pack(fill="x", pady=(0, 5))
        ttk.Button(acc_control, text="Chọn tất cả", command=self._select_all_accounts).pack(side="right", padx=(0, 5))
        ttk.Button(acc_control, text="Bỏ chọn tất cả", command=self._deselect_all_accounts).pack(side="right", padx=(0, 5))
        ttk.Button(acc_control, text="🗑 Xóa Account", command=self._remove_account).pack(side="left")
        ttk.Button(acc_control, text="🔄 Tải Pages", command=self._reload_account_pages).pack(side="left", padx=(0, 5))

        # Accounts checkbox list
        list_frame = ttk.Frame(accounts_frame)
        list_frame.pack(fill="both", expand=True)

        self.accounts_container = ttk.Frame(list_frame)
        self.accounts_container.pack(fill="both", expand=True)

        # === Section 3: Pages từ Accounts đã chọn ===
        pages_frame = ttk.LabelFrame(main_frame, text="Pages từ Accounts đã chọn", padding=10)
        pages_frame.pack(fill="both", expand=True, pady=(0, 10))

        # Pages controls
        page_control = ttk.Frame(pages_frame)
        page_control.pack(fill="x", pady=(0, 5))
        self.pages_count_label = ttk.Label(page_control, text="Chưa có pages nào")
        self.pages_count_label.pack(side="left")
        ttk.Button(page_control, text="Chọn tất cả pages", command=self._select_all_pages).pack(side="right", padx=(0, 5))
        ttk.Button(page_control, text="Bỏ chọn tất cả pages", command=self._deselect_all_pages).pack(side="right")

        # Pages container (dynamic)
        self.pages_container = ttk.Frame(pages_frame)
        self.pages_container.pack(fill="both", expand=True)

        # === Section 4: Gemini Configuration ===
        gemini_frame = ttk.LabelFrame(main_frame, text="Gemini AI", padding=10)
        gemini_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(gemini_frame, text="Gemini API Key:").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(gemini_frame, textvariable=self.gemini_key, width=60, show="*").grid(row=0, column=1, sticky="ew", pady=5, padx=(0, 10))

        ttk.Label(gemini_frame, text="Gemini Model:").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(gemini_frame, textvariable=self.gemini_model, width=60).grid(row=1, column=1, sticky="ew", pady=5, padx=(0, 10))

        ttk.Label(gemini_frame, text="Gemini Web URL:").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Entry(gemini_frame, textvariable=self.gemini_url, width=60).grid(row=2, column=1, sticky="ew", pady=5, padx=(0, 10))

        gemini_frame.columnconfigure(1, weight=1)

        # Save button
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill="x", pady=10)
        ttk.Button(action_frame, text="Lưu cấu hình", command=self.save_settings).pack(side="right")

        # Notes
        note_text = (
            "Hướng dẫn:\n"
            "1. Nhập User Access Token của một Facebook account (có quyền pages_show_list, pages_manage_posts)\n"
            "2. Bấm 'Thêm Account' để thêm account vào danh sách\n"
            "3. Tích một hoặc nhiều accounts trong danh sách\n"
            "4. Bấm 'Tải Pages' để lấy pages từ các account đã chọn\n"
            "5. Pages của các account sẽ hiển thị bên dưới - chọn pages cần đăng\n"
            "6. Lưu cấu hình và đăng bài trong tab 'Soạn bài'\n"
            "\n"
            "Lưu ý: Mỗi account cần có User Access Token riêng với đúng permissions."
        )
        ttk.Label(main_frame, text=note_text, wraplength=800, justify="left").pack(anchor="w", pady=10)

    def _toggle_show(self, entry):
        """Toggle password visibility"""
        current = entry.cget("show")
        entry.config(show="" if current == "*" else "*")

    def _build_compose_tab(self):
        self.compose_scroll = ScrollableFrame(self.compose_tab)
        self.compose_scroll.pack(fill="both", expand=True)
        left = ttk.Frame(self.compose_scroll.inner)
        left.pack(fill="both", expand=True)

        ai_bar = ttk.Frame(left)
        ai_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(ai_bar, text="Chủ đề AI").pack(side="left", padx=(0, 8))
        ttk.Entry(ai_bar, textvariable=self.ai_topic).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(ai_bar, text="Copy prompt + mở Gemini", command=self.copy_prompt_and_open_gemini).pack(side="left", padx=(0, 8))
        ttk.Button(ai_bar, text="Mở Gemini", command=self.open_gemini_web).pack(side="left", padx=(0, 8))
        ttk.Button(ai_bar, text="Sinh bằng API", command=self.generate_with_gemini).pack(side="left")

        self.message_box = Text(left, height=24, wrap="word", undo=True)
        self.message_box.pack(fill="both", expand=True)
        self.message_box.insert(
            "1.0",
            "Ba mẹ có từng thấy con mất tập trung khi làm bài toán?\n\n"
            "Tại UCMAS, trẻ được rèn luyện toán tư duy thông qua bàn tính và các bài tập phù hợp độ tuổi, "
            "giúp con từng bước tăng khả năng tập trung, tư duy logic và tự tin hơn với con số.\n\n"
            "Ba mẹ inbox Fanpage để được tư vấn lộ trình và đăng ký buổi học thử cho con nhé.\n\n"
            "#UCMAS #ToanTưDuy #HọcThử #PhátTriểnTưDuy",
        )

        media = ttk.LabelFrame(left, text="Media đính kèm", padding=8)
        media.pack(fill="x", pady=10)
        media_buttons = ttk.Frame(media)
        media_buttons.pack(fill="x", pady=(0, 6))
        ttk.Button(media_buttons, text="Thêm ảnh", command=self.add_images).pack(side="left", padx=(0, 8))
        ttk.Button(media_buttons, text="Thêm video", command=self.add_videos).pack(side="left", padx=(0, 8))
        ttk.Button(media_buttons, text="Xóa media", command=self.clear_media).pack(side="left")
        ttk.Label(media, textvariable=self.media_path, wraplength=1100, justify="left").pack(fill="x")

        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=(2, 0))
        ttk.Button(actions, text="Tạo ý tưởng UCMAS", command=self.insert_ucmas_idea).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Kiểm tra spam", command=self.show_content_guard).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Copy để đăng acc", command=self.copy_post_and_open_facebook).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Lưu nháp", command=self.save_draft).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="Đăng ngay", command=self.publish_now).pack(side="right")

        schedule = ttk.Frame(left)
        schedule.pack(fill="x", pady=(10, 0))
        ttk.Label(schedule, text="Lên lịch lúc").pack(side="left", padx=(0, 8))
        ttk.Entry(schedule, textvariable=self.schedule_time, width=22).pack(side="left", padx=(0, 8))
        ttk.Button(schedule, text="Lên lịch bài này", command=self.schedule_current_post).pack(side="left")
        ttk.Label(schedule, text="Định dạng: YYYY-MM-DD HH:MM:SS").pack(side="left", padx=(10, 0))
        self._refresh_media_display()

    def _build_history_tab(self):
        main = ttk.Frame(self.history_tab)
        main.pack(fill="both", expand=True)

        # Table header
        cols = ("Thời gian", "Lịch đăng", "Kiểu", "Trạng thái", "Facebook ID", "Lỗi", "Nội dung")
        tree = ttk.Treeview(main, columns=cols, show="headings", height=20)
        for col in cols:
            tree.heading(col, text=col)
            tree.column(col, width=120 if col in ["Thời gian", "Lịch đăng", "Kiểu", "Trạng thái"] else 180)
        tree.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(main, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        self.history_tree = tree

        refresh_btn = ttk.Button(main, text="Làm mới", command=self.refresh_history)
        refresh_btn.pack(pady=10)

    def _build_prompt_tab(self):
        main = ttk.Frame(self.prompt_tab)
        main.pack(fill="both", expand=True)

        txt = Text(main, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", UCMAS_PROMPT)
        txt.config(state="disabled")

    def _get_message(self):
        return self.message_box.get("1.0", END).strip()

    def _refresh_media_display(self):
        if not self.media_paths:
            self.media_path.set("Chua chon media. Bai viet se dang dang text neu khong them anh/video.")
            return
        lines = []
        for idx, path in enumerate(self.media_paths, 1):
            kind = "video" if self._is_video_path(path) else "anh"
            lines.append(f"{idx}. [{kind}] {Path(path).name}")
        self.media_path.set("\n".join(lines))

    def _add_media_paths(self, paths):
        existing = set(self.media_paths)
        for path in paths:
            if path and path not in existing:
                self.media_paths.append(path)
                existing.add(path)
        self._refresh_media_display()

    def add_images(self):
        paths = filedialog.askopenfilenames(
            title="Chon anh",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.gif"), ("All files", "*.*")],
        )
        self._add_media_paths(paths)

    def add_videos(self):
        paths = filedialog.askopenfilenames(
            title="Chon video",
            filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv"), ("All files", "*.*")],
        )
        self._add_media_paths(paths)

    def clear_media(self):
        self.media_paths = []
        self._refresh_media_display()

    def choose_media(self):
        paths = filedialog.askopenfilenames(
            title="Chon anh/video",
            filetypes=[("Media files", "*.jpg *.jpeg *.png *.gif *.mp4 *.mov *.avi *.mkv"), ("All files", "*.*")],
        )
        self._add_media_paths(paths)

    def _is_video_path(self, path):
        return Path(path).suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}

    def _split_media_paths(self, media_paths):
        photos = [path for path in media_paths if not self._is_video_path(path)]
        videos = [path for path in media_paths if self._is_video_path(path)]
        return photos, videos

    def _current_post_type(self, media_paths):
        photos, videos = self._split_media_paths(media_paths)
        if photos and videos:
            return "mixed"
        if photos:
            return "photo"
        if videos:
            return "video"
        return "text"

    def _serialize_media(self, media_paths):
        return json.dumps({"media_paths": list(media_paths)}, ensure_ascii=False)

    def _parse_media(self, media):
        if not media:
            return []
        if isinstance(media, list):
            return media
        try:
            data = json.loads(media)
            if isinstance(data, dict) and isinstance(data.get("media_paths"), list):
                return data["media_paths"]
        except Exception:
            pass
        return [media]

    def _serialize_scheduled_payload(self, media_paths, destinations):
        return json.dumps({
            "media_paths": list(media_paths),
            "destinations": [page.to_dict() for page in destinations],
        }, ensure_ascii=False)

    def _parse_scheduled_payload(self, media):
        media_paths = self._parse_media(media)
        destinations = []
        try:
            data = json.loads(media or "{}")
            if isinstance(data, dict):
                if isinstance(data.get("media_paths"), list):
                    media_paths = data["media_paths"]
                if isinstance(data.get("destinations"), list):
                    destinations = [FacebookPage.from_dict(item) for item in data["destinations"]]
        except Exception:
            pass
        return media_paths, destinations

    def copy_post_and_open_facebook(self):
        msg = self._get_message()
        if not msg:
            messagebox.showwarning("Chưa có nội dung", "Hãy nhập nội dung bài viết.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(msg)
        self.root.update()
        webbrowser.open("https://www.facebook.com")
        messagebox.showinfo("Copied", "Nội dung đã được copy vào clipboard. Mở Facebook thành công.")

    def copy_prompt_and_open_gemini(self):
        prompt = UCMAS_PROMPT
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.root.update()
        webbrowser.open(self.gemini_url.get())
        messagebox.showinfo("Copied", "Prompt UCMAS đã được copy. Mở Gemini thành công.")

    def open_gemini_web(self):
        webbrowser.open(self.gemini_url.get())

    def generate_with_gemini(self):
        topic = self.ai_topic.get().strip()
        if not topic:
            messagebox.showwarning("Chưa có chủ đề", "Hãy nhập chủ đề cho AI.")
            return
        api_key = self.gemini_key.get().strip()
        if not api_key:
            messagebox.showwarning("Thiếu API Key", "Hãy nhập Gemini API Key trong tab Cấu hình.")
            return

        self.status_text.set("Đang sinh bài bằng Gemini...")
        threading.Thread(target=self._generate_worker, args=(topic, api_key), daemon=True).start()

    def _generate_worker(self, topic, api_key):
        result = GeminiApi.generate(
            api_key,
            self.gemini_model.get(),
            UCMAS_PROMPT,
            f"Chủ đề: {topic}\n\nHãy viết bài Facebook theo hướng dẫn ở prompt."
        )
        self.events.put(("gemini_result", result))

    def insert_ucmas_idea(self):
        self.message_box.delete("1.0", END)
        self.message_box.insert("1.0",
            "Ba mẹ có từng thấy con mất tập trung khi làm bài toán?\n\n"
            "Tại UCMAS, trẻ được rèn luyện toán tư duy thông qua bàn tính và các bài tập phù hợp độ tuổi, "
            "giúp con từng bước tăng khả năng tập trung, tư duy logic và tự tin hơn với con số.\n\n"
            "Ba mẹ inbox Fanpage để được tư vấn lộ trình và đăng ký buổi học thử cho con nhé.\n\n"
            "#UCMAS #ToanTưDuy #HọcThử #PhátTriểnTưDuy"
        )

    def show_content_guard(self):
        msg = self._get_message()
        if not msg:
            messagebox.showwarning("Chưa có nội dung", "Hãy nhập nội dung bài viết.")
            return
        warnings = ContentGuard.check(msg, self.store.recent_messages())
        if warnings:
            messagebox.showwarning("Cần xem lại", "\n".join(warnings))
        else:
            messagebox.showinfo("OK", "Nội dung hợp lệ, không có vấn đề gì.")

    def save_draft(self):
        msg = self._get_message()
        if not msg:
            messagebox.showwarning("Chưa có nội dung", "Hãy nhập nội dung bài viết.")
            return
        self.store.add_post(
            post_type=self._current_post_type(self.media_paths),
            message=msg,
            media_path=self._serialize_media(self.media_paths),
            status="draft"
        )
        messagebox.showinfo("Đã lưu", "Bài nháp đã được lưu.")

    def refresh_history(self):
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for row in self.store.latest_posts():
            self.history_tree.insert("", END, values=row)

    def _process_events(self):
        """Process events from worker threads"""
        try:
            while True:
                event_type, data = self.events.get_nowait()

                if event_type == "load_pages":
                    # Legacy support
                    pass
                elif event_type == "add_account_error":
                    self.status_text.set("Lỗi khi thêm account")
                    messagebox.showerror("Lỗi", data)
                elif event_type == "token_exchanged":
                    if data.ok and data.data.get("access_token"):
                        self.new_account_token.set(data.data["access_token"])
                        self.save_settings()
                        expires = data.data.get("expires_in")
                        note = "Long-lived token đã được điền lại vào ô token."
                        if expires:
                            note += f"\nThời hạn còn lại khoảng {round(int(expires) / 86400)} ngày."
                        self.status_text.set("Đã đổi token dài hạn")
                        messagebox.showinfo("Đổi token thành công", note)
                    else:
                        self.status_text.set("Đổi token thất bại")
                        messagebox.showerror("Đổi token thất bại", data.error)
                elif event_type == "account_added":
                    existing_index = next((idx for idx, acc in enumerate(self.accounts) if acc.id == data.id), None)
                    if existing_index is None:
                        self.accounts.append(data)
                    else:
                        self.accounts[existing_index] = data
                    self._refresh_accounts_ui()
                    self._refresh_pages_ui()
                    self.save_settings()
                    self.status_text.set(f"Đã thêm account {data.name}")
                    self.new_account_token.set("")
                    self.new_account_name.set("")
                elif event_type == "pages_reloaded":
                    self._refresh_pages_ui()
                    self.status_text.set("Đã tải lại pages")
                elif event_type == "gemini_result":
                    if data.ok:
                        self.message_box.delete("1.0", END)
                        self.message_box.insert("1.0", data.data.get("text", ""))
                        self.status_text.set("Sinh bài thành công")
                    else:
                        self.status_text.set("Lỗi Gemini")
                        messagebox.showerror("Lỗi Gemini", data.error)
                elif event_type == "publish_done":
                    results, post_type, message, media, seconds = data
                    self._handle_publish_results(results, post_type, message, media, seconds)
                elif event_type == "scheduled_publish_done":
                    post_id, results = data
                    self._handle_scheduled_results(post_id, results)

        except queue.Empty:
            pass

        self.root.after(150, self._process_events)

    def _handle_publish_results(self, results, post_type, message, media, seconds):
        """Handle results from publish worker"""
        success_count = 0
        error_count = 0
        errors = []

        for page, result in results:
            record_message = f"[{page.name}] {message}"
            if result.ok:
                success_count += 1
                facebook_id = result.data.get("post_id") or result.data.get("id", "")
                self.store.add_post(post_type, record_message, media, "posted", facebook_id)
            else:
                error_count += 1
                self.store.add_post(post_type, record_message, media, "failed", "", result.error)
                errors.append(f"{page.name}: {result.error}")

        total = len(results)
        self.status_text.set(f"Dang bai xong sau {round(seconds, 1)}s: {success_count}/{total} thanh cong")

        if errors:
            messagebox.showerror("Loi dang bai", "\n".join(errors[:10])
                + (f"\n... va {len(errors) - 10} loi khac" if len(errors) > 10 else ""))

        self.refresh_history()

    def _handle_scheduled_results(self, post_id, results):
        """Handle results from scheduled publish"""
        success = 0
        for page, result in results:
            if result.ok:
                success += 1
            else:
                print(f"Failed to post to {page.name}: {result.error}")

        if success > 0:
            self.store.update_post_status(post_id, "posted")
        else:
            self.store.update_post_status(post_id, "failed", error=results[0][1].error if results else "Unknown error")

        self.refresh_history()

    def _parse_publish_destinations(self):
        """
        Get selected pages from selected accounts
        Returns: list[FacebookPage]
        """
        destinations = []

        for account in self.accounts:
            if not account.selected:
                continue
            
            if account.post_to_personal:
                destinations.append(FacebookPage(
                    id="me",
                    name=f"Profile cá nhân ({account.name})",
                    access_token=account.user_token,
                    account_id=account.id
                ))
                
            for page in account.pages:
                if page.selected:
                    destinations.append(page)

        return destinations

    def _publish_one(self, page: FacebookPage, message, media, post_type, account=None):
        """Publish one destination. Photos are grouped; videos are posted separately."""
        if page.id == "me":
            if PlaywrightManager and account and account.is_browser_logged_in:
                media_paths = self._parse_media(media)
                # Đăng cá nhân không chia ảnh/album/video phức tạp như Graph API, cứ nhét hết vào 1 cục
                success, result = PlaywrightManager.post_to_timeline(account.id, message, media_paths)
                return ApiResult(success, result if success else {}, result if not success else None)
            else:
                return ApiResult(False, {}, "PlaywrightManager not installed or account not logged in browser.")

        token = page.access_token
        media_paths = self._parse_media(media)
        photos, videos = self._split_media_paths(media_paths)
        results = []

        if photos:
            if len(photos) == 1:
                results.append(FacebookApi.post_photo(page.id, token, message, photos[0]))
            else:
                results.append(FacebookApi.post_photo_album(page.id, token, message, photos))

        for video_path in videos:
            results.append(FacebookApi.post_video(page.id, token, message, video_path))

        if not results:
            results.append(FacebookApi.post_text(page.id, token, message))

        failed = [result for result in results if not result.ok]
        if failed:
            return ApiResult(False, {"results": [result.data for result in results]}, "\n".join(result.error for result in failed))

        ids = []
        for result in results:
            facebook_id = result.data.get("post_id") or result.data.get("id")
            if facebook_id:
                ids.append(facebook_id)
        return ApiResult(True, {"id": ", ".join(ids), "results": [result.data for result in results]})

    def publish_now(self):
        message = self._get_message()
        media_paths = list(self.media_paths)
        post_type = self._current_post_type(media_paths)
        media = self._serialize_media(media_paths)

        destinations = self._parse_publish_destinations()

        if not destinations:
            messagebox.showwarning("Thiếu cấu hình", "Hãy tích ít nhất 1 account và 1 page để đăng bài.")
            return
        if not message:
            messagebox.showwarning("Thiếu nội dung", "Hãy nhập nội dung bài viết.")
            return

        missing = [path for path in media_paths if not Path(path).exists()]
        if missing:
            messagebox.showerror("Media khong ton tai", "Mot so file khong con ton tai:\n" + "\n".join(missing[:10]))
            return

        warnings = ContentGuard.check(message, self.store.recent_messages())
        if warnings:
            ok = messagebox.askyesno("Cần xem lại nội dung", "\n".join(warnings) + "\n\nVẫn Đăng ngay?")
            if not ok:
                return

        destination_names = []
        for page in destinations:
            account = next((acc for acc in self.accounts if acc.id == page.account_id), None)
            account_name = account.name if account else page.account_id
            destination_names.append(f"{page.name} ({account_name})")
        names = ", ".join(destination_names[:5])
        more_count = len(destination_names) - 5
        more = f" va {more_count} pages khac" if more_count > 0 else ""
        media_note = f"\nMedia: {len(media_paths)} file ({post_type})" if media_paths else "\nMedia: khong co"
        msg = f"Dang len {len(destinations)} pages:\n{names}{more}{media_note}\n\nTiep tuc?"

        if not messagebox.askyesno("X?c nh?n ??ng b?i", msg):
            return

        self.save_settings()
        self.status_text.set("?ang g?i b?i l?n Facebook...")
        threading.Thread(
            target=self._publish_worker,
            args=(destinations, message, media, post_type),
            daemon=True,
        ).start()

    def _publish_worker(self, destinations, message, media, post_type):
        start = time.time()
        results = []
        for page in destinations:
            account = next((acc for acc in self.accounts if acc.id == page.account_id), None)
            result = self._publish_one(page, message, media, post_type, account=account)
            results.append((page, result))
        seconds = time.time() - start
        self.events.put(("publish_done", (results, post_type, message, media, seconds)))

    def schedule_current_post(self):
        message = self._get_message()
        media_paths = list(self.media_paths)
        post_type = self._current_post_type(media_paths)
        destinations = self._parse_publish_destinations()

        if not destinations:
            messagebox.showwarning("Thiếu cấu hình", "Hãy tích ít nhất 1 account và 1 page.")
            return
        if not message:
            messagebox.showwarning("Thiếu nội dung", "Hãy nhập nội dung bài viết.")
            return

        missing = [path for path in media_paths if not Path(path).exists()]
        if missing:
            messagebox.showerror("Media khong ton tai", "Mot so file khong con ton tai:\n" + "\n".join(missing[:10]))
            return

        try:
            scheduled_at = datetime.strptime(self.schedule_time.get(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            messagebox.showerror("Sai dinh dang", "Thoi gian phai theo dinh dang YYYY-MM-DD HH:MM:SS")
            return

        self.store.add_post(
            post_type=post_type,
            message=message,
            media_path=self._serialize_scheduled_payload(media_paths, destinations),
            status="scheduled",
            scheduled_at=scheduled_at.strftime("%Y-%m-%d %H:%M:%S")
        )
        self.refresh_history()
        messagebox.showinfo("Đã lên lịch", f"Bài đã lên lịch cho {scheduled_at} với {len(destinations)} pages")
    def save_settings(self):
        """Save current configuration"""
        config = {
            "accounts": [acc.to_dict() for acc in self.accounts],
            "gemini_key": self.gemini_key.get(),
            "gemini_model": self.gemini_model.get(),
            "gemini_url": self.gemini_url.get(),
            "facebook_app_id": self.facebook_app_id.get(),
            "facebook_app_secret": self.facebook_app_secret.get()
        }
        save_config(config)

    def _scheduler_tick(self):
        due = self.store.due_scheduled_posts()
        if due:
            post_id, post_type, message, media = due[0]
            media_paths, destinations = self._parse_scheduled_payload(media)
            if not destinations:
                destinations = self._parse_publish_destinations()
            if destinations:
                self.store.update_post_status(post_id, "posting")
                threading.Thread(
                    target=self._publish_scheduled_worker,
                    args=(post_id, destinations, message, self._serialize_media(media_paths), post_type),
                    daemon=True,
                ).start()
            else:
                self.store.update_post_status(post_id, "failed", error="No scheduled destinations")
                self.refresh_history()
        self.root.after(30000, self._scheduler_tick)

    def _publish_scheduled_worker(self, post_id, destinations, message, media, post_type):
        results = []
        for page in destinations:
            result = self._publish_one(page, message, media, post_type)
            results.append((page, result))
        self.events.put(("scheduled_publish_done", post_id, results))




def main():
    root = Tk()
    try:
        PosterApp(root)
        root.mainloop()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        messagebox.showerror("Loi khoi dong", f"Loi:\n{exc}\n\nXem console de biet chi tiet.")


if __name__ == "__main__":
    main()
