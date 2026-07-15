"""Playwright implementation for posting to a personal Facebook profile."""
from __future__ import annotations

import time
import base64
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit


def check_facebook_login(profile_dir: str) -> dict:
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "unknown": True, "message": f"Playwright is not installed in this service: {exc}"}

    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "message": "Hồ sơ trình duyệt chưa được đăng nhập."}

    try:
        with sync_playwright() as p:
            browser, remote_browser = _open_browser_context(p, settings.BROWSERLESS_WS_URL.strip(), str(path), True)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            is_login = page.locator("input[name='email']").is_visible()
            body_text = _visible_text(page).lower()
            _close_browser_context(browser, remote_browser)
            if is_login:
                return {"success": False, "message": "Phiên trình duyệt đã hết hạn hoặc chưa đăng nhập Facebook."}
            if _looks_checkpoint(body_text):
                return {"success": False, "status": "checkpoint", "message": "Facebook đang yêu cầu kiểm tra hoặc xác thực. Hãy kết nối trình duyệt để xử lý."}
            return {"success": True, "message": "Browser session logged in."}
    except Exception as exc:
        return {"success": False, "message": f"Không kiểm tra được phiên trình duyệt: {exc}"}


def post_to_timeline(profile_dir: str, message: str, media_paths: list[str] | None = None, headless: bool = True) -> dict:
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "message": f"Playwright is not installed in this service: {exc}"}

    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "message": "Hồ sơ trình duyệt chưa được đăng nhập. Hãy đăng nhập trình duyệt trước."}

    media_paths = media_paths or []
    try:
        with sync_playwright() as p:
            remote_browser = None
            browser = None
            if settings.BROWSERLESS_WS_URL.strip():
                remote_browser = p.chromium.connect_over_cdp(
                    _browserless_endpoint(settings.BROWSERLESS_WS_URL.strip(), str(path)),
                    timeout=30000,
                )
                browser = remote_browser.contexts[0] if remote_browser.contexts else remote_browser.new_context()
            else:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=str(path),
                    headless=headless,
                    args=[
                        "--disable-notifications",
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    timeout=30000,
                )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            if page.locator("input[name='email']").is_visible():
                browser.close()
                if remote_browser is not None:
                    remote_browser.close()
                return {"success": False, "message": "Phiên trình duyệt đã hết hạn hoặc chưa đăng nhập Facebook."}
            body_text = _visible_text(page).lower()
            if _looks_checkpoint(body_text):
                browser.close()
                if remote_browser is not None:
                    remote_browser.close()
                return {"success": False, "status": "checkpoint", "message": "Facebook đang yêu cầu kiểm tra hoặc xác thực. Hãy kết nối trình duyệt để xử lý."}

            trigger = page.locator("span:text-matches('nghĩ gì|nghi gi|on your mind', 'i')").first
            trigger.wait_for(state="visible", timeout=15000)
            trigger.click()
            time.sleep(2)

            textbox = page.locator("div[role='dialog'] div[role='textbox'][contenteditable='true']").first
            textbox.wait_for(state="visible", timeout=15000)
            if message:
                textbox.click()
                page.keyboard.insert_text(message)
                time.sleep(1)

            if media_paths:
                page.locator("input[type='file']").first.set_input_files(media_paths)
                time.sleep(3)

            post_btn = page.locator("div[role='dialog'] div[role='button'][aria-label='Đăng'], div[role='dialog'] div[role='button'][aria-label='Post']").first
            post_btn.wait_for(state="visible", timeout=10000)
            post_btn.click()
            page.locator("div[role='dialog']").first.wait_for(state="hidden", timeout=45000)
            browser.close()
            if remote_browser is not None:
                remote_browser.close()
            return {"success": True, "message": "Đã đăng lên trang cá nhân bằng trình duyệt.", "post_url": "https://www.facebook.com/"}
    except Exception as exc:
        return {"success": False, "message": f"Lỗi trình duyệt worker: {exc}"}


def check_target_access(profile_dir: str, target_url: str, target_type: str = "target") -> dict:
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "status": "error", "message": f"Playwright is not installed in this service: {exc}"}

    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "status": "login_required", "message": "Hồ sơ trình duyệt chưa được đăng nhập."}

    try:
        with sync_playwright() as p:
            browser, remote_browser = _open_browser_context(p, settings.BROWSERLESS_WS_URL.strip(), str(path), True)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
            if _is_login_page(page):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "status": "login_required", "message": "Phiên trình duyệt đã hết hạn hoặc chưa đăng nhập Facebook."}
            if _looks_checkpoint(_visible_text(page).lower()):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "status": "checkpoint", "message": "Facebook đang yêu cầu kiểm tra hoặc xác thực. Hãy kết nối trình duyệt để xử lý."}
            title = page.title() or target_url
            text = _visible_text(page).lower()
            _close_browser_context(browser, remote_browser)
            if any(mark in text for mark in ["content isn't available", "page isn't available", "this content isn't available", "khong hien thi", "khong kha dung"]):
                return {"success": False, "status": "not_found", "message": "Không thể truy cập mục tiêu hoặc mục tiêu không tồn tại.", "title": title}
            return {"success": True, "status": "available", "message": f"{target_type} available.", "title": title}
    except Exception as exc:
        return {"success": False, "status": "error", "message": f"Không kiểm tra được mục tiêu: {exc}"}


def post_to_group(profile_dir: str, group_url: str, message: str, media_paths: list[str] | None = None, headless: bool = True) -> dict:
    return _post_to_facebook_surface(
        profile_dir=profile_dir,
        target_url=group_url,
        message=message,
        media_paths=media_paths or [],
        action_name="group",
        headless=headless,
    )


def share_to_target(
    profile_dir: str,
    target_url: str,
    source_url: str,
    message: str = "",
    job_type: str = "share_to_group",
    headless: bool = True,
    target_name: str = "",
) -> dict:
    """Use Facebook's native Share UI so the original post/card is preserved."""
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "message": f"Playwright is not installed in this service: {exc}"}

    if not source_url:
        return {"success": False, "message": "Thiếu URL bài nguồn để thực hiện native Share."}
    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "message": "Hồ sơ trình duyệt chưa được đăng nhập. Hãy đăng nhập trình duyệt trước."}

    try:
        with sync_playwright() as p:
            browser, remote_browser = _open_browser_context(
                p, settings.BROWSERLESS_WS_URL.strip(), str(path), headless
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            try:
                page.goto(source_url, wait_until="domcontentloaded", timeout=45000)
                time.sleep(4)
                if _is_login_page(page):
                    return {"success": False, "message": "Phiên trình duyệt đã hết hạn hoặc chưa đăng nhập Facebook."}
                if _looks_checkpoint(_visible_text(page).lower()):
                    return {
                        "success": False,
                        "status": "checkpoint",
                        "message": "Facebook đang yêu cầu kiểm tra hoặc xác thực.",
                    }
                return _native_share_from_source(page, source_url, target_url, target_name, message, job_type)
            finally:
                _close_browser_context(browser, remote_browser)
    except Exception as exc:
        return {"success": False, "message": f"Lỗi native Share bằng trình duyệt worker: {exc}"}


def _native_share_from_source(page, source_url: str, target_url: str, target_name: str, message: str, job_type: str) -> dict:
    scope = _source_post_scope(page, source_url)
    if scope is None:
        return {"success": False, "message": f"Không xác định được đúng bài nguồn {source_url}; từ chối click nút Share của bài khác."}

    share_trigger = _visible_matching(
        scope,
        "div[role='button'], button, [aria-label][role='button']",
        re.compile(r"^(share|chia\s*sẻ|chia\s*se)$", re.IGNORECASE),
        use_accessible_text=True,
    )
    if share_trigger is None:
        return {"success": False, "message": "Không tìm thấy nút Share/Chia sẻ trên đúng bài nguồn."}
    share_trigger.click()
    time.sleep(2)

    destination_pattern = (
        re.compile(r"share (to|in|with) (a )?group|chia sẻ (đến|tới|vào|lên) nhóm|chia se (den|toi|vao|len) nhom", re.IGNORECASE)
        if job_type == "share_to_group"
        else re.compile(r"share (to|as) a page|chia sẻ (đến|tới|lên) trang|chia se (den|toi|len) trang", re.IGNORECASE)
    )
    destination = _wait_visible_matching(
        page,
        "div[role='menuitem'], div[role='button'], button",
        destination_pattern,
        timeout_seconds=12,
    )
    if destination is None:
        return {"success": False, "message": "Không thấy lựa chọn Share đến nhóm/trang trong menu Facebook."}
    destination.click()
    time.sleep(2)

    search = _first_visible(page, [
        "div[role='dialog'] input[type='search']",
        "div[role='dialog'] input[placeholder*='Search' i]",
        "div[role='dialog'] input[placeholder*='Tìm kiếm' i]",
        "div[role='dialog'] div[role='textbox'][contenteditable='true']",
    ], timeout_seconds=8)
    query = (target_name or _facebook_target_query(target_url)).strip()
    if search is not None and query:
        search.fill(query)
        time.sleep(2)

    target = _find_native_share_target(page, query, target_url, timeout_seconds=15)
    if target is None:
        return {"success": False, "message": f"Không tìm thấy đúng nhóm/trang đích '{query or target_url}' trong danh sách Share."}
    target.click()
    time.sleep(2)

    if message:
        textbox = _first_visible(page, [
            "div[role='dialog'] div[role='textbox'][contenteditable='true']",
        ], timeout_seconds=8, prefer_last=True)
        if textbox is not None:
            textbox.click()
            page.keyboard.insert_text(message)
            time.sleep(1)

    submit = _wait_visible_matching(
        page,
        "div[role='dialog'] div[role='button'], div[role='dialog'] button",
        re.compile(
            r"^(share|share now|share post|post|post now|chia sẻ|chia sẻ ngay|đăng|đăng ngay|đăng lên nhóm|đăng ngay lên nhóm)$",
            re.IGNORECASE,
        ),
        timeout_seconds=15,
        prefer_last=True,
    )
    if submit is None:
        return {"success": False, "message": "Không tìm thấy nút xác nhận native Share cuối cùng."}
    submit.click()
    time.sleep(5)
    return {
        "success": True,
        "pending_review": job_type == "share_to_group" and _looks_pending_review(page),
        "message": "Đã native Share đúng bài nguồn qua Facebook UI.",
        "post_url": source_url,
    }


def _source_post_scope(page, source_url: str):
    tokens = _facebook_post_identity_tokens(source_url)
    dialogs = page.locator("div[role='dialog']:visible")
    for token in tokens:
        matched = dialogs.filter(has=page.locator(f"a[href*='{token}']"))
        if matched.count():
            return matched.last
    if dialogs.count():
        article_dialogs = dialogs.filter(has=page.locator("[role='article'], article"))
        if article_dialogs.count() == 1:
            return article_dialogs.first

    articles = page.locator("[role='main'] [role='article']:visible, [role='main'] article:visible")
    for token in tokens:
        matched = articles.filter(has=page.locator(f"a[href*='{token}']"))
        if matched.count():
            return matched.first
    if articles.count() == 1:
        return articles.first
    return None


def _facebook_post_identity_tokens(value: str) -> list[str]:
    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query)
        tokens = [str(query[key][0]).lower() for key in ("story_fbid", "fbid", "v") if query.get(key)]
        parts = [unquote(part).lower() for part in parsed.path.split("/") if part]
        for marker in ("posts", "videos", "reel"):
            if marker in parts and parts.index(marker) + 1 < len(parts):
                tokens.append(parts[parts.index(marker) + 1])
        if len(parts) >= 3 and parts[0] == "share" and parts[1] in {"p", "r", "v"}:
            tokens.append(parts[2])
        return list(dict.fromkeys(token for token in tokens if token))
    except Exception:
        return []


def _facebook_target_query(target_url: str) -> str:
    parts = [unquote(part) for part in urlsplit(target_url).path.split("/") if part]
    if parts and parts[0].lower() == "groups" and len(parts) > 1:
        return parts[1]
    return parts[-1] if parts else target_url


def _find_native_share_target(page, target_name: str, target_url: str, timeout_seconds: int):
    deadline = time.monotonic() + timeout_seconds
    name_pattern = re.compile(rf"^{re.escape(target_name)}(?:\s*[•(\-|].*)?$", re.IGNORECASE) if target_name else None
    url_keys = [
        unquote(part).casefold()
        for part in urlsplit(target_url).path.split("/")
        if part and part.casefold() != "groups"
    ]
    url_keys = [key for key in url_keys if len(key) >= 3]
    while time.monotonic() < deadline:
        if name_pattern is not None:
            for selector in ("div[role='option']", "div[role='menuitem']", "li", "a[role='link']"):
                found = _visible_matching(page, selector, name_pattern)
                if found is not None:
                    return found
        if url_keys:
            for selector in ("div[role='option']", "div[role='menuitem']", "li"):
                candidates = page.locator(selector)
                for index in range(candidates.count()):
                    candidate = candidates.nth(index)
                    try:
                        if not candidate.is_visible():
                            continue
                        text = candidate.inner_text(timeout=500)
                        if any(_share_target_text_matches_url_key(text, key) for key in url_keys):
                            return candidate
                    except Exception:
                        continue
        for key in url_keys:
            links = page.locator(f"a[href*='{key}']:visible")
            if links.count():
                return links.first
        time.sleep(0.3)
    return None


def _share_target_text_matches_url_key(text: str, url_key: str) -> bool:
    normalized_text = " ".join(re.sub(r"[^\w]+", " ", unquote(text).casefold()).split())
    normalized_key = " ".join(re.sub(r"[^\w]+", " ", unquote(url_key).casefold()).split())
    return len(normalized_key) >= 3 and normalized_key in normalized_text


def _visible_matching(root, selector: str, pattern: re.Pattern, use_accessible_text: bool = False, prefer_last: bool = False):
    candidates = root.locator(selector)
    indexes = range(candidates.count() - 1, -1, -1) if prefer_last else range(candidates.count())
    for index in indexes:
        candidate = candidates.nth(index)
        try:
            if not candidate.is_visible():
                continue
            text = " ".join(filter(None, [
                candidate.inner_text(timeout=1000),
                candidate.get_attribute("aria-label") if use_accessible_text else "",
            ])).strip()
            if pattern.search(text):
                return candidate
        except Exception:
            continue
    return None


def _wait_visible_matching(root, selector: str, pattern: re.Pattern, timeout_seconds: int, prefer_last: bool = False):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        found = _visible_matching(root, selector, pattern, use_accessible_text=True, prefer_last=prefer_last)
        if found is not None:
            return found
        time.sleep(0.3)
    return None


def _first_visible(page, selectors: list[str], timeout_seconds: int, prefer_last: bool = False):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for selector in selectors:
            candidates = page.locator(selector)
            indexes = range(candidates.count() - 1, -1, -1) if prefer_last else range(candidates.count())
            for index in indexes:
                candidate = candidates.nth(index)
                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    continue
        time.sleep(0.3)
    return None


def _post_to_facebook_surface(profile_dir: str, target_url: str, message: str, media_paths: list[str], action_name: str, headless: bool) -> dict:
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "message": f"Playwright is not installed in this service: {exc}"}

    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "message": "Hồ sơ trình duyệt chưa được đăng nhập. Hãy đăng nhập trình duyệt trước."}

    try:
        with sync_playwright() as p:
            browser, remote_browser = _open_browser_context(p, settings.BROWSERLESS_WS_URL.strip(), str(path), headless)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(4)
            if _is_login_page(page):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "message": "Phiên trình duyệt đã hết hạn hoặc chưa đăng nhập Facebook."}
            if _looks_checkpoint(_visible_text(page).lower()):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "status": "checkpoint", "message": "Facebook đang yêu cầu kiểm tra hoặc xác thực. Hãy kết nối trình duyệt để xử lý."}

            if not _open_composer(page):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "message": f"Giao diện Facebook không cho phép đăng/chia sẻ tới {action_name} này hoặc bộ chọn đã thay đổi."}

            textbox = page.locator("div[role='dialog'] div[role='textbox'][contenteditable='true']").first
            textbox.wait_for(state="visible", timeout=15000)
            if message:
                textbox.click()
                page.keyboard.insert_text(message)
                time.sleep(1)

            if media_paths:
                page.locator("input[type='file']").first.set_input_files(media_paths)
                time.sleep(4)

            post_btn = page.locator(
                "div[role='dialog'] div[role='button'][aria-label='Post'], "
                "div[role='dialog'] div[role='button'][aria-label='Dang'], "
                "div[role='dialog'] div[role='button']:has-text('Post'), "
                "div[role='dialog'] div[role='button']:has-text('Dang')"
            ).first
            post_btn.wait_for(state="visible", timeout=15000)
            post_btn.click()
            time.sleep(6)
            pending_review = _looks_pending_review(page)
            try:
                page.locator("div[role='dialog']").first.wait_for(state="hidden", timeout=45000)
            except Exception:
                pass
            _close_browser_context(browser, remote_browser)
            return {
                "success": True,
                "pending_review": pending_review,
                "message": f"Đã gửi bài lên {action_name} bằng trình duyệt.",
                "post_url": target_url,
            }
    except Exception as exc:
        return {"success": False, "message": f"Lỗi trình duyệt worker: {exc}"}


def _open_composer(page) -> bool:
    selectors = [
        "span:text-matches('Write something|Create a public post|Say something|Bạn viết gì|Ban viet gi|Viết gì đó|Viet gi do', 'i')",
        "div[role='button']:has-text('Write something')",
        "div[role='button']:has-text('Create a public post')",
        "div[role='button']:has-text('Bạn viết gì')",
        "div[role='button']:has-text('Viet gi do')",
    ]
    for selector in selectors:
        try:
            trigger = page.locator(selector).first
            trigger.wait_for(state="visible", timeout=5000)
            trigger.click()
            time.sleep(2)
            return True
        except Exception:
            continue
    return False


def _is_login_page(page) -> bool:
    try:
        return page.locator("input[name='email']").is_visible(timeout=1000)
    except Exception:
        return False


def _visible_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def _looks_pending_review(page) -> bool:
    text = _visible_text(page).lower()
    return any(mark in text for mark in ["pending", "review", "duyet", "cho phe duyet", "approval"])


def _looks_checkpoint(text: str) -> bool:
    return any(mark in text for mark in [
        "checkpoint",
        "security check",
        "confirm your identity",
        "two-factor authentication",
        "login approval",
        "xac minh",
        "xác minh",
        "kiem tra bao mat",
        "kiểm tra bảo mật",
    ])


def _open_browser_context(playwright, base_ws_url: str, profile_dir: str, headless: bool):
    remote_browser = None
    if base_ws_url:
        remote_browser = playwright.chromium.connect_over_cdp(
            _browserless_endpoint(base_ws_url, profile_dir),
            timeout=30000,
        )
        browser = remote_browser.contexts[0] if remote_browser.contexts else remote_browser.new_context()
        return browser, remote_browser
    browser = playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=headless,
        args=[
            "--disable-notifications",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        timeout=30000,
    )
    return browser, None


def _close_browser_context(browser, remote_browser=None) -> None:
    try:
        browser.close()
    finally:
        if remote_browser is not None:
            try:
                remote_browser.close()
            except Exception:
                pass


def _browserless_endpoint(base_ws_url: str, profile_dir: str) -> str:
    launch = {
        "args": [
            f"--user-data-dir={profile_dir}",
            "--disable-notifications",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    }
    encoded_launch = base64.b64encode(json.dumps(launch).encode("utf-8")).decode("ascii")
    parts = urlsplit(base_ws_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("launch", encoded_launch)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
