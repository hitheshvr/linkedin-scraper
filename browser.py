import time
from playwright.sync_api import sync_playwright
from utils import GOTO_TIMEOUT


class Browser:

    def __init__(self):
        self.pw      = None
        self.context = None
        self.page    = None

    def start(self):
        print("🚀 Starting browser...")
        self.pw = sync_playwright().start()
        self.context = self.pw.chromium.launch_persistent_context(
            user_data_dir = "linkedin_profile",
            headless      = False,
            viewport      = {"width": 1440, "height": 900},
            args          = ["--disable-blink-features=AutomationControlled"],
        )
        self.page = self.context.new_page()
        print("✅ Browser ready")

    def stop(self):
        try:
            self.context.close()
            self.pw.stop()
        except:
            pass

    def goto(self, url, retries=3):
        for attempt in range(retries):
            try:
                print(f"🌐 {url}")
                self.page.goto(url, timeout=GOTO_TIMEOUT, wait_until="commit")
                time.sleep(5)
                return
            except Exception as e:
                print(f"  Retry {attempt+1}: {e}")
                time.sleep(5)
        raise Exception(f"Failed to load: {url}")

    def login(self, email, password):
        self.goto("https://www.linkedin.com/login")
        try:
            self.page.locator('input[name="session_key"]').fill(email)
            self.page.locator('input[name="session_password"]').fill(password)
            self.page.locator('button[type="submit"]').click()
            self.page.wait_for_url("**/feed/**", timeout=120_000)
            print("✅ Logged in")
        except:
            print("⚠  Manual login required — complete it in the browser window")
            self.page.wait_for_url("**/feed/**", timeout=300_000)
            print("✅ Manual login detected")