"""Facebook Graph API client — direct port of CommentService.cs."""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

from app.config import settings

# Constants
GRAPH_BASE = f"https://graph.facebook.com/{settings.GRAPH_API_VERSION}/"

TOKEN_CHECK_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
AUTHOR_RESOLVER_TIMEOUT = httpx.Timeout(connect=5.0, read=35.0, write=5.0, pool=5.0)
GRAPH_TIMEOUT = httpx.Timeout(connect=5.0, read=45.0, write=5.0, pool=5.0)

CHECKPOINT_CODES = {282, 459, 490, 492, 493, 494, 959}
CHECKPOINT_SUBCODES = {282, 459, 490, 492, 493, 494, 959}
TOKEN_OUT_SUBCODES = {458, 460, 463, 467}

IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".jfif", ".pjpeg", ".pjp",
    ".png", ".gif", ".webp", ".bmp", ".dib",
    ".tif", ".tiff", ".heic", ".heif", ".avif",
    ".ico", ".svg",
})

VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".m4v", ".avi", ".wmv", ".mpeg", ".mpg", ".webm", ".mkv",
})

MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jfif": "image/jpeg",
    ".pjpeg": "image/jpeg", ".pjp": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    ".bmp": "image/bmp", ".dib": "image/bmp",
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".heic": "image/heic", ".heif": "image/heic",
    ".avif": "image/avif", ".ico": "image/x-icon", ".svg": "image/svg+xml",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v",
    ".avi": "video/x-msvideo", ".wmv": "video/x-ms-wmv",
    ".mpeg": "video/mpeg", ".mpg": "video/mpeg", ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}


# ─── utilities ────────────────────────────────────────────────────────────────

def _trim(value: str, max_len: int = 240) -> str:
    value = value.replace("\r", " ").replace("\n", " ").strip()
    return value[:max_len] if len(value) > max_len else value


def _get_str(el: dict, name: str) -> str:
    v = el.get(name)
    return "" if v is None or v == "" else str(v)


def _get_int(el: dict, name: str) -> int:
    v = el.get(name)
    if v is None:
        return 0
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


# ─── URL parsing ──────────────────────────────────────────────────────────────

_RE_COMMENT_PATH = re.compile(
    r"(?:comment_id|comments?|reply_comment_id)[/=:\-]([^/?#]+)", re.IGNORECASE
)
_RE_COMMENT_FALLBACK = re.compile(r"comment_id[=:]([^&#\s]+)", re.IGNORECASE)

_RE_POST_PATH = re.compile(
    r"(?:posts|videos|photos|permalink)/([^/?#]+)", re.IGNORECASE
)
_RE_PFBID = re.compile(r"(pfbid[^/?#]+)", re.IGNORECASE)


def _parse_query(query: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in query.strip("?").split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            result[k] = v
    return result


def extract_comment_id(link: str) -> Optional[str]:
    """Extract comment ID from a Facebook comment link or raw ID string."""
    trimmed = link.strip()
    if not trimmed:
        return None
    if not trimmed.lower().startswith("http"):
        return trimmed
    try:
        parsed = urlparse(trimmed)
        q = _parse_query(parsed.query)
        for key in ("comment_id", "commentid", "comment", "id"):
            val = q.get(key, "").strip()
            if val:
                return val
        m = _RE_COMMENT_PATH.search(parsed.path)
        if m:
            return m.group(1)
    except Exception:
        pass
    m = _RE_COMMENT_FALLBACK.search(trimmed)
    return m.group(1) if m else None


def extract_post_id(value: str) -> Optional[str]:
    """Extract post ID from a Facebook post link or raw ID string."""
    trimmed = value.strip()
    if not trimmed:
        return None
    if not trimmed.lower().startswith("http"):
        return trimmed
    try:
        parsed = urlparse(trimmed)
        q = _parse_query(parsed.query)
        for key in ("story_fbid", "fbid", "id"):
            val = q.get(key, "").strip()
            if val:
                return val
        path = parsed.path.strip("/")
        m = _RE_POST_PATH.search(path)
        if m:
            return m.group(1)
        m = _RE_PFBID.search(path)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


# ─── Graph error handling ─────────────────────────────────────────────────────

def detect_token_issue(
    message: str, user_message: str, code: int, subcode: int
) -> Optional[dict]:
    """Return a TokenIssue dict or None."""
    issue_code = subcode if subcode != 0 else code
    combined = f"{message} {user_message}".lower()

    if (
        code in CHECKPOINT_CODES
        or subcode in CHECKPOINT_SUBCODES
        or "checkpoint" in combined
        or "security check" in combined
        or "verify" in combined
    ):
        return {
            "kind": "Checkpoint",
            "code": code,
            "subcode": subcode,
            "status": f"Checkpoint {issue_code}" if issue_code != 0 else "Checkpoint",
        }

    if (
        code == 190
        or subcode in TOKEN_OUT_SUBCODES
        or ("access token" in combined and "expired" in combined)
        or "invalid oauth" in combined
        or "session has expired" in combined
    ):
        return {
            "kind": "Token out",
            "code": code,
            "subcode": subcode,
            "status": f"Token out {issue_code}" if issue_code != 0 else "Token out",
        }
    return None


RE_RETRY_DELAY = re.compile(
    r"(?:Gửi lại sau|Gui lai sau|retry after|try again in)"
    r"\s*(\d+)\s*(?:giây|giay|s|sec|secs|second|seconds)?",
    re.IGNORECASE,
)


def _normalize_retry_message(error_body: str) -> str:
    match = RE_RETRY_DELAY.search(error_body)
    if match:
        return f"Gửi lại sau {match.group(1)}s"
    return _trim(error_body, 180)


def build_graph_error_result(status_code: int, body: str) -> dict:
    """Build a CommentResult-style error dict from a Graph API error response."""
    try:
        import json
        data = json.loads(body)
        err = data.get("error", {})
        message = err.get("message", body)
        code = _get_int(err, "code")
        subcode = _get_int(err, "error_subcode")
        user_message = _get_str(err, "error_user_msg")

        hint = ""
        if code == 200:
            hint = " Token không có quyền với comment này."
        elif code == 100:
            hint = " Sai ID/link bài viết."

        full_msg = (
            f"Graph API {status_code}: {_trim(message)} "
            f"(code {code}, subcode {subcode}). "
            f"{user_message}{hint}"
        ).strip()
        token_issue = detect_token_issue(message, user_message, code, subcode)
        return {"success": False, "message": full_msg, "token_issue": token_issue}
    except Exception:
        return {
            "success": False,
            "message": f"Graph API {status_code}: {_trim(body)}",
            "token_issue": None,
        }


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def _build_proxy_handler(proxy_url: Optional[str] = None) -> Optional[httpx.Proxy]:
    if not proxy_url:
        return None
    return httpx.Proxy(proxy_url)


# ─── API functions ────────────────────────────────────────────────────────────

async def check_token(token: str, proxy_url: Optional[str] = None) -> dict:
    """GET /me?fields=id — token health check."""
    url = f"https://graph.facebook.com/me?fields=id&access_token={token}"
    try:
        async with httpx.AsyncClient(
            timeout=TOKEN_CHECK_TIMEOUT,
            proxy=_build_proxy_handler(proxy_url),
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return {
                    "live": True,
                    "status": "Live",
                    "fb_id": resp.json().get("id", ""),
                }
            return build_graph_error_result(resp.status_code, resp.text)
    except httpx.TimeoutException:
        return {"live": False, "status": "Die", "error": "Timeout"}
    except Exception as ex:
        return {"live": False, "status": "Die", "error": str(ex)}


async def exchange_long_lived_user_token(token: str, proxy_url: Optional[str] = None) -> dict:
    """Exchange a short-lived user token for a long-lived user token using the app secret."""
    if not settings.META_APP_ID or not settings.META_APP_SECRET:
        return {
            "success": False,
            "skipped": True,
            "message": "META_APP_ID/META_APP_SECRET is not configured.",
        }
    try:
        async with httpx.AsyncClient(
            timeout=GRAPH_TIMEOUT,
            proxy=_build_proxy_handler(proxy_url),
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                "https://graph.facebook.com/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.META_APP_ID,
                    "client_secret": settings.META_APP_SECRET,
                    "fb_exchange_token": token,
                },
            )
            if resp.status_code != 200:
                result = build_graph_error_result(resp.status_code, resp.text)
                result["skipped"] = False
                return result
            data = resp.json()
            long_token = str(data.get("access_token") or "")
            if not long_token:
                return {"success": False, "message": "Meta did not return access_token.", "skipped": False}
            return {
                "success": True,
                "access_token": long_token,
                "expires_in": data.get("expires_in"),
                "token_type": data.get("token_type", ""),
            }
    except httpx.TimeoutException:
        return {"success": False, "message": "Timeout exchanging long-lived token.", "skipped": False}
    except Exception as ex:
        return {"success": False, "message": str(ex), "skipped": False}


async def get_user_info(token: str, proxy_url: Optional[str] = None) -> dict:
    url = f"https://graph.facebook.com/me?fields=id,name&access_token={token}"
    async with httpx.AsyncClient(
        timeout=TOKEN_CHECK_TIMEOUT,
        proxy=_build_proxy_handler(proxy_url),
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return build_graph_error_result(resp.status_code, resp.text)
        data = resp.json()
        return {"success": True, "id": data.get("id", ""), "name": data.get("name", "")}


async def get_my_pages(token: str, proxy_url: Optional[str] = None) -> dict:
    url = (
        f"{GRAPH_BASE}me/accounts"
        f"?fields=id,name,access_token,tasks,category&access_token={token}"
    )
    async with httpx.AsyncClient(
        timeout=GRAPH_TIMEOUT,
        proxy=_build_proxy_handler(proxy_url),
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return build_graph_error_result(resp.status_code, resp.text)
        pages = []
        for item in resp.json().get("data", []):
            pages.append({
                "page_id": item.get("id", ""),
                "page_name": item.get("name", ""),
                "page_access_token": item.get("access_token", ""),
                "permissions": item.get("tasks", []),
                "category": item.get("category", ""),
            })
        return {"success": True, "pages": pages}


async def post_page_feed(
    page_id: str,
    page_token: str,
    message: str,
    link: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> dict:
    if not message.strip() and not (link or "").strip():
        return {"success": False, "message": "Nội dung hoặc link đang trống."}
    data = {"message": message, "access_token": page_token}
    if link:
        data["link"] = link
    async with httpx.AsyncClient(
        timeout=GRAPH_TIMEOUT,
        proxy=_build_proxy_handler(proxy_url),
        follow_redirects=True,
    ) as client:
        resp = await client.post(f"{GRAPH_BASE}{page_id}/feed", data=data)
        if resp.status_code != 200:
            return build_graph_error_result(resp.status_code, resp.text)
        created_id = resp.json().get("id", "")
        return {
            "success": True,
            "message": "Đã đăng bài lên Fanpage.",
            "post_id": created_id,
            "post_url": f"https://www.facebook.com/{created_id}" if created_id else "",
        }


async def post_page_media(
    page_id: str,
    page_token: str,
    message: str,
    media_paths: list[str],
    link: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> dict:
    existing = [path for path in media_paths if path]
    if not existing:
        return await post_page_feed(page_id, page_token, message, link, proxy_url)

    final_message = f"{message}\n\n{link}".strip() if link else message
    results = []
    for path in existing:
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in VIDEO_EXTENSIONS:
            results.append(await post_page_video(page_id, page_token, final_message, path, proxy_url))
        else:
            results.append(await post_page_photo(page_id, page_token, final_message, path, proxy_url))

    failed = [result for result in results if not result.get("success")]
    if failed:
        return {
            "success": False,
            "message": "\n".join(str(result.get("message") or result.get("error") or "Upload failed") for result in failed),
            "results": results,
        }

    ids = [str(result.get("post_id") or "") for result in results if result.get("post_id")]
    return {
        "success": True,
        "message": "Da dang media len Fanpage.",
        "post_id": ", ".join(ids),
        "post_url": f"https://www.facebook.com/{ids[0]}" if ids else "",
        "results": results,
    }


async def post_page_photo(
    page_id: str,
    page_token: str,
    message: str,
    media_path: str,
    proxy_url: Optional[str] = None,
) -> dict:
    try:
        with open(media_path, "rb") as file_obj:
            files = {"source": (media_path.rsplit("/", 1)[-1], file_obj, get_image_content_type(media_path))}
            data = {"message": message, "access_token": page_token}
            async with httpx.AsyncClient(
                timeout=GRAPH_TIMEOUT,
                proxy=_build_proxy_handler(proxy_url),
                follow_redirects=True,
            ) as client:
                resp = await client.post(f"{GRAPH_BASE}{page_id}/photos", data=data, files=files)
    except OSError as ex:
        return {"success": False, "message": f"Khong mo duoc file media: {ex}"}

    if resp.status_code != 200:
        return build_graph_error_result(resp.status_code, resp.text)
    created_id = resp.json().get("post_id") or resp.json().get("id", "")
    return {
        "success": True,
        "message": "Da dang anh len Fanpage.",
        "post_id": created_id,
        "post_url": f"https://www.facebook.com/{created_id}" if created_id else "",
    }


async def post_page_video(
    page_id: str,
    page_token: str,
    message: str,
    media_path: str,
    proxy_url: Optional[str] = None,
) -> dict:
    video_base = GRAPH_BASE.replace("https://graph.facebook.com/", "https://graph-video.facebook.com/")
    try:
        with open(media_path, "rb") as file_obj:
            files = {"source": (media_path.rsplit("/", 1)[-1], file_obj, get_image_content_type(media_path))}
            data = {"description": message, "access_token": page_token}
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=180.0, write=180.0, pool=10.0),
                proxy=_build_proxy_handler(proxy_url),
                follow_redirects=True,
            ) as client:
                resp = await client.post(f"{video_base}{page_id}/videos", data=data, files=files)
    except OSError as ex:
        return {"success": False, "message": f"Khong mo duoc file video: {ex}"}

    if resp.status_code != 200:
        return build_graph_error_result(resp.status_code, resp.text)
    created_id = resp.json().get("id", "")
    return {
        "success": True,
        "message": "Da dang video len Fanpage.",
        "post_id": created_id,
        "post_url": f"https://www.facebook.com/{created_id}" if created_id else "",
    }


async def resolve_author_uid(
    comment_link: str, token: str, proxy_url: Optional[str] = None
) -> dict:
    """GET /v19.0/{commentId}?fields=id,from — resolve author UID."""
    comment_id = extract_comment_id(comment_link)
    if not comment_id:
        return {"uid": None, "message": "Không đọc được comment_id từ link."}

    url = f"{GRAPH_BASE}{comment_id}?fields=id,from&access_token={token}"
    try:
        async with httpx.AsyncClient(
            timeout=AUTHOR_RESOLVER_TIMEOUT,
            proxy=_build_proxy_handler(proxy_url),
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Graph read UID {resp.status_code}: {_trim(resp.text, 220)}"
                )
            data = resp.json()
            from_data = data.get("from", {})
            uid = from_data.get("id", "")
            if uid and len(uid) >= 5 and len(uid) <= 30 and uid.isdigit():
                return {"uid": uid, "message": "Lấy UID bằng Graph với token kiểm tra."}
            return {"uid": None, "message": "Graph API không trả về from.id hợp lệ."}
    except RuntimeError:
        raise
    except Exception as ex:
        raise RuntimeError(f"Request kiểm tra UID bị lỗi: {ex}") from ex


def get_image_content_type(path: str) -> str:
    ext = path[path.rfind("."):].lower() if "." in path else ""
    return MIME_MAP.get(ext, "application/octet-stream")


def _build_edit_url(comment_id: str) -> str:
    return f"{GRAPH_BASE}{comment_id}"


def _build_delete_url(comment_id: str, token: str) -> str:
    return f"{GRAPH_BASE}{comment_id}?access_token={token}"


def _build_create_url(post_id: str) -> str:
    return f"{GRAPH_BASE}{post_id}/comments"


# ─── low-level _execute helper ────────────────────────────────────────────────

async def _execute_edit(
    http: httpx.AsyncClient,
    comment_id: str,
    token: str,
    new_text: Optional[str],
    image_path: Optional[str],
) -> dict:
    if not new_text or not new_text.strip():
        return {"success": False, "message": "Nội dung chỉnh sửa đang trống."}

    if image_path:
        return await _execute_edit_with_image(http, comment_id, token, new_text, image_path)

    url = _build_edit_url(comment_id)
    resp = await http.post(url, data={"message": new_text, "access_token": token})
    if resp.status_code != 200:
        return build_graph_error_result(resp.status_code, resp.text)
    return {"success": True, "message": "Đã chỉnh sửa comment."}


async def _execute_edit_with_image(
    http: httpx.AsyncClient, comment_id: str, token: str,
    new_text: str, image_path: str,
) -> dict:
    url = _build_edit_url(comment_id)
    try:
        with open(image_path, "rb") as f:
            files = {
                "source": (image_path.split("/")[-1], f, get_image_content_type(image_path)),
            }
            data = {
                "message": new_text,
                "access_token": token,
            }
            resp = await http.post(url, data=data, files=files)
    except OSError as ex:
        return {"success": False, "message": f"Không mở được file ảnh: {ex}"}
    except Exception as ex:
        return {"success": False, "message": str(ex)}

    if resp.status_code != 200:
        return build_graph_error_result(resp.status_code, resp.text)
    return {
        "success": True,
        "message": f"Đã chỉnh sửa comment kèm ảnh {image_path.split('/')[-1]}.",
    }


async def _execute_delete(http: httpx.AsyncClient, comment_id: str, token: str) -> dict:
    url = _build_delete_url(comment_id, token)
    resp = await http.delete(url)
    if resp.status_code != 200:
        return build_graph_error_result(resp.status_code, resp.text)
    return {"success": True, "message": "Đã xóa comment."}


async def _execute_create(
    http: httpx.AsyncClient,
    post_id: str,
    token: str,
    text: str,
    image_path: Optional[str],
) -> dict:
    if not text or not text.strip():
        return {"success": False, "message": "Nội dung comment đang trống."}

    url = _build_create_url(post_id)
    if image_path:
        try:
            with open(image_path, "rb") as f:
                files = {
                    "source": (
                        post_id.split("/")[-1],
                        f,
                        get_image_content_type(image_path),
                    ),
                }
                data = {"message": text, "access_token": token}
                resp = await http.post(url, data=data, files=files)
        except OSError as ex:
            return {"success": False, "message": f"Không mở được file ảnh: {ex}"}
        except Exception as ex:
            return {"success": False, "message": str(ex)}
    else:
        resp = await http.post(url, data={"message": text, "access_token": token})

    if resp.status_code != 200:
        return build_graph_error_result(resp.status_code, resp.text)

    try:
        created_id: Optional[str] = resp.json().get("id")
    except Exception:
        created_id = None

    output_link = _build_comment_link(post_id, created_id)
    image_note = f" kèm ảnh {image_path.split('/')[-1]}" if image_path else ""
    return {
        "success": True,
        "message": f"Đã tạo comment mới{image_note}.",
        "output_link": output_link,
    }


def _build_comment_link(post_id: str, comment_id: Optional[str]) -> str:
    if not comment_id:
        return f"https://www.facebook.com/{post_id}"
    normalized = _normalize_comment_id(post_id, comment_id)
    if not normalized:
        return f"https://www.facebook.com/{post_id}"
    return f"https://www.facebook.com/{post_id}?comment_id={normalized}"


def _normalize_comment_id(post_id: str, comment_id: str) -> str:
    prefix = f"{post_id}_"
    if comment_id.startswith(prefix):
        return comment_id[len(prefix):]
    idx = comment_id.rfind("_")
    if idx >= 0 and idx < len(comment_id) - 1:
        return comment_id[idx + 1:]
    return comment_id


# ─── main entry ───────────────────────────────────────────────────────────────

async def execute_comment_action(
    action: str,
    comment_link: str,
    token: str,
    new_text: Optional[str] = None,
    image_path: Optional[str] = None,
    proxy_url: Optional[str] = None,
) -> dict:
    """
    Execute a Facebook Graph API comment action.
    Returns: { success: bool, message: str, output_link?: str, token_issue?: dict }
    """
    try:
        async with httpx.AsyncClient(
            timeout=GRAPH_TIMEOUT,
            proxy=_build_proxy_handler(proxy_url),
            follow_redirects=True,
        ) as http:
            if action == "new_comment":
                post_id = extract_post_id(comment_link)
                if not post_id:
                    return {"success": False, "message": "Không đọc được ID/link bài viết."}
                return await _execute_create(http, post_id, token, new_text or "", image_path)

            comment_id = extract_comment_id(comment_link)
            if not comment_id:
                return {"success": False, "message": "Không đọc được comment_id từ link."}

            if action == "delete":
                return await _execute_delete(http, comment_id, token)

            return await _execute_edit(http, comment_id, token, new_text, image_path)
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Tác vụ bị hủy hoặc kết nối bị ngắt.",
        }
    except httpx.NetworkError:
        return {
            "success": False,
            "message": "Tác vụ bị hủy hoặc kết nối bị ngắt.",
        }
    except Exception as ex:
        return {"success": False, "message": str(ex)}
