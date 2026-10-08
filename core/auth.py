import sys
import time
import subprocess
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

from core.utils import Style, safe_print


def setup_session(moodle_cookie: str, pool_size: int = 20) -> requests.Session:
    """
    Initializes a requests.Session with connection pooling for multi-threading.
    """
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size, max_retries=2)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,he;q=0.8',
    })

    moodle_cookie = moodle_cookie.strip().strip('"\'')

    if '=' in moodle_cookie:
        for part in moodle_cookie.split(';'):
            if '=' in part:
                k, v = part.strip().split('=', 1)
                session.cookies.set(k.strip(), v.strip())
    else:
        session.cookies.set('MoodleSession', moodle_cookie)

    return session


def ensure_playwright_ready(auto_install_prompt: bool = True) -> bool:
    """Verifies if playwright is installed, offering to install it if missing."""
    try:
        import playwright
        return True
    except ImportError:
        if not auto_install_prompt:
            return False
        print(f"\n{Style.YELLOW}[!] Playwright is not currently installed.{Style.RESET}")
        print("Playwright is required to automatically fetch Moodle cookies.")
        choice = input(f"Would you like to install playwright now? [Y/n] (default: Y) > ").strip().lower()
        if choice in ['', 'y', 'yes', '1']:
            print(f"\n{Style.CYAN}[*] Installing playwright via pip...{Style.RESET}")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
                print(f"{Style.CYAN}[*] Installing Chromium browser for Playwright...{Style.RESET}")
                subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
                print(f"{Style.GREEN}[+] Playwright installed successfully!{Style.RESET}\n")
                return True
            except Exception as e:
                print(f"{Style.RED}[!] Failed to install Playwright: {e}{Style.RESET}")
                return False
        return False


def login_with_playwright(
    site_url: str,
    username: str,
    password: str,
    course_url: str = None,
    headless: bool = True,
    timeout_sec: int = 45
) -> tuple[str, str]:
    """
    Automates Moodle login via Playwright to extract session cookies.
    Supports standard Moodle forms, Microsoft/Office 365 SSO, and interactive 2FA completion.
    Returns (cookie_header_string, error_message).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "The 'playwright' package is not installed."

    safe_print(f"\n{Style.CYAN}[*] Starting automated browser ({'headless' if headless else 'visible'})...{Style.RESET}")

    playwright_instance = None
    browser = None
    context = None
    try:
        playwright_instance = sync_playwright().start()
        launch_args = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        try:
            browser = playwright_instance.chromium.launch(headless=headless, args=launch_args)
        except Exception as launch_err:
            err_str = str(launch_err).lower()
            if "executable doesn't exist" in err_str or "playwright install" in err_str:
                safe_print(f"{Style.YELLOW}[*] Chromium browser binary not found. Downloading Chromium for Playwright (one-time setup)...{Style.RESET}")
                try:
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                    browser = playwright_instance.chromium.launch(headless=headless, args=launch_args)
                except Exception as install_err:
                    return None, f"Failed to download Chromium: {install_err}"
            else:
                return None, f"Failed to launch browser: {launch_err}"

        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            locale='he-IL',
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()

        target_url = course_url if course_url else f"{site_url.rstrip('/')}/login/index.php"
        safe_print(f"{Style.CYAN}[*] Navigating to {target_url} ...{Style.RESET}")

        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as nav_err:
            safe_print(f"{Style.YELLOW}[!] Page navigation warning: {nav_err}. Continuing...{Style.RESET}")

        # Check if already authenticated
        cookies = context.cookies()
        if any('moodlesession' in c['name'].lower() for c in cookies) and "/login/" not in page.url.lower():
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            return cookie_str, None

        # Check for direct username field or SSO button
        username_selectors = [
            'input#username',
            'input[name="username"]',
            'input#login_username',
            'input[name="login_username"]',
            'input#i0116',
            'input[name="loginfmt"]',
            'input[autocomplete="username"]',
            'input[type="email"]'
        ]

        has_username = False
        for sel in username_selectors:
            try:
                if page.locator(sel).first.is_visible(timeout=1500):
                    has_username = True
                    break
            except Exception:
                pass

        if not has_username:
            # Check for SSO / IdP button
            sso_selectors = [
                'a[href*="auth/oauth2"]',
                'a[href*="auth/oidc"]',
                'a[href*="login/microsoft"]',
                '.potentialidp a',
                'a:has-text("Office 365")',
                'a:has-text("Microsoft")',
                'a:has-text("הזדהות אחידה")',
                'a:has-text("התחברות באמצעות")'
            ]
            for sso_sel in sso_selectors:
                try:
                    sso_btn = page.locator(sso_sel).first
                    if sso_btn.is_visible(timeout=1500):
                        safe_print(f"{Style.CYAN}[*] Clicking SSO login button...{Style.RESET}")
                        sso_btn.click()
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                        break
                except Exception:
                    pass

        # Fill Username
        safe_print(f"{Style.CYAN}[*] Entering credentials...{Style.RESET}")
        typed_user = False
        for sel in username_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=2000):
                    loc.fill(username)
                    typed_user = True
                    break
            except Exception:
                pass

        if not typed_user:
            # Fallback to any visible text input
            try:
                inputs = page.locator('input:visible').all()
                for inp in inputs:
                    inp_type = (inp.get_attribute('type') or 'text').lower()
                    if inp_type in ['text', 'email']:
                        inp.fill(username)
                        typed_user = True
                        break
            except Exception:
                pass

        # Check if password field is visible
        password_selectors = [
            'input#password',
            'input[name="password"]',
            'input[type="password"]',
            'input#i0118',
            'input[name="passwd"]'
        ]

        password_visible = False
        for sel in password_selectors:
            try:
                if page.locator(sel).first.is_visible(timeout=1500):
                    password_visible = True
                    break
            except Exception:
                pass

        # If password field is not visible (e.g. Microsoft 2-step prompt where Next is needed)
        if not password_visible:
            next_buttons = [
                'input#idSIButton9',
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Next")',
                'button:has-text("הבא")'
            ]
            for btn_sel in next_buttons:
                try:
                    loc = page.locator(btn_sel).first
                    if loc.is_visible(timeout=1500):
                        loc.click()
                        page.wait_for_timeout(1000)
                        break
                except Exception:
                    pass

        # Fill Password
        typed_pass = False
        for sel in password_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=3000):
                    loc.fill(password)
                    typed_pass = True
                    break
            except Exception:
                pass

        if not typed_pass:
            try:
                pass_input = page.locator('input[type="password"]:visible').first
                if pass_input.is_visible(timeout=2000):
                    pass_input.fill(password)
                    typed_pass = True
            except Exception:
                pass

        # Submit Login Form
        submit_selectors = [
            'button#loginbtn',
            'input#loginbtn',
            'input#idSIButton9',
            'button[type="submit"]',
            'input[type="submit"]'
        ]
        submitted = False
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    submitted = True
                    break
            except Exception:
                pass

        if not submitted:
            page.keyboard.press("Enter")

        # Handle Microsoft "Stay signed in?" screen if it appears
        page.wait_for_timeout(1500)
        stay_signed_in_buttons = [
            'input#idSIButton9',
            'button:has-text("Yes")',
            'button:has-text("כן")',
            'input[value="Yes"]',
            'input[value="כן"]',
            '#idBtn_Back'
        ]
        for btn_sel in stay_signed_in_buttons:
            try:
                btn = page.locator(btn_sel).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    break
            except Exception:
                pass

        # Polling loop: Wait for login completion
        safe_print(f"{Style.CYAN}[*] Waiting for Moodle session authentication...{Style.RESET}")
        if not headless:
            safe_print(f"{Style.DIM}    (If an MFA / 2FA or CAPTCHA prompt is shown in the browser window, please complete it now){Style.RESET}")

        start_time = time.time()
        parsed_domain = urlparse(site_url).netloc.lower()

        while time.time() - start_time < timeout_sec:
            page.wait_for_timeout(1000)

            # Check for visible login error messages
            error_selectors = [
                '#loginerrormsg',
                '.loginerrors',
                '.alert-danger',
                '#passwordError',
                '#usernameError',
                '[role="alert"]'
            ]
            for err_sel in error_selectors:
                try:
                    err_elem = page.locator(err_sel).first
                    if err_elem.is_visible(timeout=200):
                        err_text = err_elem.text_content().strip()
                        if err_text and len(err_text) < 150:
                            return None, f"Login rejected by server: {err_text}"
                except Exception:
                    pass

            # Check cookies
            cookies = context.cookies()
            moodle_cookies = [c for c in cookies if 'moodlesession' in c['name'].lower()]
            curr_url = page.url.lower()

            not_on_login_page = not any(x in curr_url for x in ['/login/index.php', 'login.microsoftonline', 'signin', 'auth/oauth2'])

            if moodle_cookies and (not_on_login_page or parsed_domain in curr_url):
                page.wait_for_timeout(1000)
                all_cookies = context.cookies()
                cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in all_cookies])
                safe_print(f"{Style.GREEN}[+] Successfully authenticated! Captured session cookies.{Style.RESET}")
                return cookie_str, None

        return None, "Timed out waiting for Moodle session cookies. Check your credentials or MFA."

    except Exception as e:
        return None, f"Playwright automation error: {e}"
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if playwright_instance:
            try:
                playwright_instance.stop()
            except Exception:
                pass

