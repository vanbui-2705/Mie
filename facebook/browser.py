import time
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

class PlaywrightManager:
    BROWSER_DATA_DIR = Path.home() / ".ucmas_facebook_poster" / "browser_profiles"

    @classmethod
    def get_profile_path(cls, account_id):
        cls.BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return str(cls.BROWSER_DATA_DIR / account_id)

    @classmethod
    def _kill_zombie_chrome(cls):
        """Giết hết tiến trình Chrome zombie trước khi mở trình duyệt mới"""
        try:
            os.system("taskkill /F /IM chrome.exe /T >nul 2>&1")
            time.sleep(1)
        except:
            pass

    @classmethod
    def login_account(cls, account_id, on_status=None):
        """Mở trình duyệt để người dùng tự đăng nhập Facebook"""
        profile_path = cls.get_profile_path(account_id)
        if on_status:
            on_status("Đang mở trình duyệt. Hãy đăng nhập Facebook...")
            
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                headless=False,
                channel="chrome",
                args=["--disable-notifications"]
            )
            page = browser.pages[0]
            page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            
            # Đợi cho đến khi người dùng đóng trình duyệt
            try:
                while True:
                    if len(browser.pages) == 0 or browser.pages[0].is_closed():
                        break
                    time.sleep(1)
            except Exception:
                pass
                
            try:
                browser.close()
            except:
                pass
            return True

    @classmethod
    def check_is_logged_in(cls, account_id):
        """Kiểm tra xem thư mục profile có tồn tại không để tối ưu tốc độ UI"""
        profile_path = cls.get_profile_path(account_id)
        return Path(profile_path).exists()

    @classmethod
    def post_to_timeline(cls, account_id, message, media_paths=None, headless=False):
        """Đăng bài lên tường cá nhân bằng Playwright"""
        profile_path = cls.get_profile_path(account_id)
        
        # Giết zombie Chrome trước khi khởi chạy
        cls._kill_zombie_chrome()
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=headless,
                    channel="chrome",
                    args=[
                        "--disable-notifications",
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    timeout=30000
                )
                page = browser.pages[0]
                
                # Dùng domcontentloaded thay vì networkidle (Facebook không bao giờ idle)
                page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
                
                # Chờ thêm vài giây cho trang render xong
                time.sleep(3)

                try:
                    # Kiểm tra xem có bị văng đăng nhập không
                    if page.locator("input[name='email']").is_visible():
                        browser.close()
                        return False, "Chưa đăng nhập Facebook. Vui lòng bấm 'Đăng nhập Trình duyệt' lại."

                    # Nhấn vào ô "Bạn đang nghĩ gì?" (FB hiện dạng "Vaan ơi, bạn đang nghĩ gì thế?")
                    trigger = page.locator("span:text-matches('nghĩ gì', 'i'), span:text-matches('on your mind', 'i')").first
                    trigger.wait_for(state="visible", timeout=15000)
                    trigger.click()
                    time.sleep(2)

                    # Chờ hộp thoại tạo bài viết mở ra
                    textbox = page.locator("div[role='dialog'] div[role='textbox'][contenteditable='true']").first
                    textbox.wait_for(state="visible", timeout=15000)
                    
                    # Gõ chữ thay vì fill để tương thích Draft.js
                    if message:
                        textbox.click()
                        time.sleep(0.5)
                        page.keyboard.insert_text(message)
                        time.sleep(1)

                    # Tải ảnh/video lên nếu có
                    if media_paths:
                        file_input = page.locator("input[type='file']").first
                        file_input.set_input_files(media_paths)
                        time.sleep(3)

                    # Bấm nút Đăng
                    post_btn = page.locator("div[role='dialog'] div[role='button'][aria-label='Đăng'], div[role='dialog'] div[role='button'][aria-label='Post']").first
                    post_btn.wait_for(state="visible", timeout=10000)
                    post_btn.click()

                    # Đợi hộp thoại biến mất (đăng xong)
                    page.locator("div[role='dialog']").first.wait_for(state="hidden", timeout=30000)
                    time.sleep(2)

                    browser.close()
                    return True, {"id": "timeline_post", "message": "Đăng thành công bằng trình duyệt"}
                except Exception as e:
                    try:
                        page.screenshot(path="debug_facebook.png")
                    except:
                        pass
                    try:
                        browser.close()
                    except:
                        pass
                    return False, f"Lỗi thao tác trình duyệt: {str(e)}"
        except Exception as e:
            return False, f"Lỗi khởi chạy trình duyệt: {str(e)}"
