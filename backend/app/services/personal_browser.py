"""Playwright implementation for posting to a personal Facebook profile."""
from __future__ import annotations

import time
import base64
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl


def check_facebook_login(profile_dir: str) -> dict:
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "unknown": True, "message": f"Playwright is not installed in this service: {exc}"}

    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "message": "Browser profile chua duoc login."}

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
                return {"success": False, "message": "Browser session het han hoac chua login Facebook."}
            if _looks_checkpoint(body_text):
                return {"success": False, "status": "checkpoint", "message": "Facebook dang yeu cau checkpoint/xac thuc. Hay connect browser de xu ly."}
            return {"success": True, "message": "Browser session logged in."}
    except Exception as exc:
        return {"success": False, "message": f"Khong check duoc browser session: {exc}"}


def post_to_timeline(profile_dir: str, message: str, media_paths: list[str] | None = None, headless: bool = True) -> dict:
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "message": f"Playwright is not installed in this service: {exc}"}

    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "message": "Browser profile chua duoc login. Hay login browser truoc."}

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
                return {"success": False, "message": "Browser session het han hoac chua login Facebook."}
            body_text = _visible_text(page).lower()
            if _looks_checkpoint(body_text):
                browser.close()
                if remote_browser is not None:
                    remote_browser.close()
                return {"success": False, "status": "checkpoint", "message": "Facebook dang yeu cau checkpoint/xac thuc. Hay connect browser de xu ly."}

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
            return {"success": True, "message": "Da dang len trang ca nhan bang browser.", "post_url": "https://www.facebook.com/"}
    except Exception as exc:
        return {"success": False, "message": f"Loi browser worker: {exc}"}


def check_target_access(profile_dir: str, target_url: str, target_type: str = "target") -> dict:
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "status": "error", "message": f"Playwright is not installed in this service: {exc}"}

    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "status": "login_required", "message": "Browser profile chua duoc login."}

    try:
        with sync_playwright() as p:
            browser, remote_browser = _open_browser_context(p, settings.BROWSERLESS_WS_URL.strip(), str(path), True)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
            if _is_login_page(page):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "status": "login_required", "message": "Browser session het han hoac chua login Facebook."}
            if _looks_checkpoint(_visible_text(page).lower()):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "status": "checkpoint", "message": "Facebook dang yeu cau checkpoint/xac thuc. Hay connect browser de xu ly."}
            title = page.title() or target_url
            text = _visible_text(page).lower()
            _close_browser_context(browser, remote_browser)
            if any(mark in text for mark in ["content isn't available", "page isn't available", "this content isn't available", "khong hien thi", "khong kha dung"]):
                return {"success": False, "status": "not_found", "message": "Target khong truy cap duoc hoac khong ton tai.", "title": title}
            return {"success": True, "status": "available", "message": f"{target_type} available.", "title": title}
    except Exception as exc:
        return {"success": False, "status": "error", "message": f"Khong check duoc target: {exc}"}


def post_to_group(profile_dir: str, group_url: str, message: str, media_paths: list[str] | None = None, headless: bool = True) -> dict:
    return _post_to_facebook_surface(
        profile_dir=profile_dir,
        target_url=group_url,
        message=message,
        media_paths=media_paths or [],
        action_name="group",
        headless=headless,
    )


def share_to_target(profile_dir: str, target_url: str, source_url: str, message: str = "", job_type: str = "share_to_group", headless: bool = True) -> dict:
    final_message = f"{message}\n\n{source_url}".strip() if source_url else message
    action_name = "external page" if job_type == "share_to_external_page" else "group"
    return _post_to_facebook_surface(
        profile_dir=profile_dir,
        target_url=target_url,
        message=final_message,
        media_paths=[],
        action_name=action_name,
        headless=headless,
    )


def _post_to_facebook_surface(profile_dir: str, target_url: str, message: str, media_paths: list[str], action_name: str, headless: bool) -> dict:
    try:
        from playwright.sync_api import sync_playwright
        from app.config import settings
    except Exception as exc:
        return {"success": False, "message": f"Playwright is not installed in this service: {exc}"}

    path = Path(profile_dir)
    if not path.exists() or not any(path.iterdir()):
        return {"success": False, "message": "Browser profile chua duoc login. Hay login browser truoc."}

    try:
        with sync_playwright() as p:
            browser, remote_browser = _open_browser_context(p, settings.BROWSERLESS_WS_URL.strip(), str(path), headless)
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(4)
            if _is_login_page(page):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "message": "Browser session het han hoac chua login Facebook."}
            if _looks_checkpoint(_visible_text(page).lower()):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "status": "checkpoint", "message": "Facebook dang yeu cau checkpoint/xac thuc. Hay connect browser de xu ly."}

            if not _open_composer(page):
                _close_browser_context(browser, remote_browser)
                return {"success": False, "message": f"Facebook UI khong cho dang/share toi {action_name} nay hoac selector da thay doi."}

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
                "message": f"Da gui bai len {action_name} bang browser.",
                "post_url": target_url,
            }
    except Exception as exc:
        return {"success": False, "message": f"Loi browser worker: {exc}"}


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
