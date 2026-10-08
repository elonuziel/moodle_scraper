import os
import re
import sys
import time
import shutil
import zipfile
import argparse
import getpass
import subprocess
import threading
from urllib.parse import urljoin, unquote, urlparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
try:
    import requests
    from requests.adapters import HTTPAdapter
    from bs4 import BeautifulSoup
except ImportError as e:
    missing_mod = getattr(e, 'name', 'required packages')
    print(f"\n[!] Missing dependency: {missing_mod}")
    print("Please install required packages first:")
    print("    pip install -r requirements.txt\n")
    sys.exit(1)


# Ensure UTF-8 console output for Hebrew and international filenames on Windows
if sys.platform == "win32":
    os.system("")
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    WHITE = "\033[37m"

print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    """Thread-safe console printing."""
    with print_lock:
        print(*args, **kwargs)

def print_banner():
    print(f"\n{Style.CYAN}{'=' * 70}{Style.RESET}")
    print(f"{Style.BOLD}{Style.WHITE}           MOODLE COURSE MATERIAL DOWNLOADER{Style.RESET}")
    print(f"{Style.DIM}   Fast parallel downloads for presentations, files, folders & solutions{Style.RESET}")
    print(f"{Style.CYAN}{'=' * 70}{Style.RESET}\n")

def sanitize_filename(name: str, max_length: int = 200) -> str:
    """
    Removes invalid characters for Windows/Linux/macOS file systems and prevents path traversal.
    """
    if not name:
        return "unnamed_file"
    
    name = name.strip()
    # Prevent path traversal
    name = re.sub(r'^[./\\]+', '', name)
    # Replace directory separators and forbidden characters (\ / * ? : " < > |)
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    # Remove control characters and clean trailing spaces/dots
    name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip('. ')
    
    if not name:
        return "unnamed_file"
        
    return name[:max_length]

def format_size(bytes_num: int) -> str:
    """Formats bytes into human readable KB/MB/GB."""
    if not bytes_num:
        return ""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_num < 1024.0:
            return f"{bytes_num:.1f} {unit}" if unit != 'B' else f"{bytes_num} B"
        bytes_num /= 1024.0
    return f"{bytes_num:.1f} TB"

def get_filename_from_cd(cd: str) -> str:
    """
    Extracts and decodes the filename from the Content-Disposition header.
    Prioritizes RFC 5987 / RFC 6266 (filename*=UTF-8''...) over ASCII fallback (filename="...").
    """
    if not cd:
        return None
    
    # 1. Check for RFC 5987 / 6266 filename*=UTF-8''... (highest priority for international characters)
    match_star = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", cd, re.IGNORECASE)
    if match_star:
        raw_val = match_star.group(1).strip().strip('"\'')
        decoded = unquote(raw_val)
        return sanitize_filename(decoded)
        
    # 2. Check for filename="..."
    match_quoted = re.search(r'filename\s*=\s*"([^"]+)"', cd, re.IGNORECASE)
    if match_quoted:
        raw_val = match_quoted.group(1).strip()
        try:
            raw_val = raw_val.encode('latin1').decode('utf-8')
        except Exception:
            pass
        return sanitize_filename(unquote(raw_val))
        
    # 3. Check for filename=unquoted
    match_unquoted = re.search(r'filename\s*=\s*([^; ]+)', cd, re.IGNORECASE)
    if match_unquoted:
        raw_val = match_unquoted.group(1).strip().strip('"\'')
        try:
            raw_val = raw_val.encode('latin1').decode('utf-8')
        except Exception:
            pass
        return sanitize_filename(unquote(raw_val))
        
    return None

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

def safe_extract_zip(zip_path: str, target_dir: str, remove_zip: bool = True) -> tuple[int, str]:
    """
    Safely unpacks a ZIP archive into a dedicated subfolder.
    Protects against Zip-Slip vulnerabilities and handles UTF-8 paths.
    Returns (file_count, extracted_folder_name).
    """
    base_name = os.path.splitext(os.path.basename(zip_path))[0]
    extract_dir = os.path.join(target_dir, base_name)
    os.makedirs(extract_dir, exist_ok=True)
    
    file_count = 0
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for member in zf.infolist():
                filename = member.filename
                try:
                    filename = filename.encode('cp437').decode('utf-8')
                except Exception:
                    pass
                
                # Prevent zip-slip
                target_path = os.path.abspath(os.path.join(extract_dir, filename))
                if not target_path.startswith(os.path.abspath(extract_dir)):
                    continue
                    
                if member.is_dir():
                    os.makedirs(target_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with zf.open(member) as source, open(target_path, 'wb') as dest:
                        shutil.copyfileobj(source, dest)
                    file_count += 1
                    
        if remove_zip and os.path.exists(zip_path):
            os.remove(zip_path)
            
        return file_count, base_name
    except Exception as e:
        return 0, str(e)

def stream_download_file(session: requests.Session, url: str, target_dir: str, default_name: str = None, 
                         method: str = 'GET', data: dict = None, initial_res: requests.Response = None,
                         auto_unpack: bool = True) -> tuple[str, int, int]:
    """
    Streams a file download to target_dir. Resolves filename from headers or URL.
    Optionally extracts ZIP archives automatically.
    Returns (saved_name, bytes_downloaded, extracted_files_count) or (None, 0, 0) on failure.
    """
    try:
        if initial_res is not None:
            res = initial_res
        else:
            if method.upper() == 'POST':
                res = session.post(url, data=data, stream=True, allow_redirects=True)
            else:
                res = session.get(url, stream=True, allow_redirects=True)
            res.raise_for_status()
        
        cd = res.headers.get('Content-Disposition', '')
        filename = get_filename_from_cd(cd)
        
        if not filename:
            if default_name:
                filename = sanitize_filename(default_name)
            else:
                parsed = urlparse(res.url)
                path_last = parsed.path.split('/')[-1]
                filename = sanitize_filename(unquote(path_last)) if path_last else "downloaded_file"
                
        filepath = os.path.join(target_dir, filename)
        
        # Handle file name collisions in the same folder
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(filepath):
            filepath = os.path.join(target_dir, f"{base} ({counter}){ext}")
            counter += 1
            
        total_downloaded = 0
        with open(filepath, 'wb') as f:
            for chunk in res.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    total_downloaded += len(chunk)
                    
        # Check if downloaded file is a ZIP archive that should be unpacked
        extracted_count = 0
        final_display_name = os.path.basename(filepath)
        
        if auto_unpack and filepath.lower().endswith('.zip'):
            count, folder_name = safe_extract_zip(filepath, target_dir, remove_zip=True)
            if count > 0:
                extracted_count = count
                final_display_name = f"{folder_name}/ (Unpacked {count} files)"
                
        return final_display_name, total_downloaded, extracted_count
    except Exception as e:
        safe_print(f"   {Style.RED}[!] Failed download from {url}: {e}{Style.RESET}")
        return None, 0, 0

def extract_clean_title(a_tag) -> str:
    """
    Extracts the clean activity title without Moodle accessibility tags (e.g. 'קובץ' or 'Assignment').
    """
    instance_span = a_tag.find(class_='instancename')
    if instance_span:
        for hide in instance_span.find_all(class_=re.compile(r'accesshide|sr-only')):
            hide.decompose()
        title = instance_span.get_text(strip=True)
    else:
        title = a_tag.get_text(strip=True)
        
    title = re.sub(r'(קובץ|File|תיקייה|Folder|מטלה|Assignment|דף|Page|קישור|URL)\s*$', '', title, flags=re.IGNORECASE).strip()
    return title or "Activity"

def can_run_headed() -> bool:
    """Checks whether the environment supports displaying a graphical browser window."""
    if sys.platform in ["win32", "darwin"]:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

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

def resolve_course_url(raw_input: str, default_site: str = "https://moodle.ruppin.ac.il") -> tuple[str, str, str]:
    """
    Resolves raw input into (clean_course_url, course_id, domain).
    Input can be:
      - A numeric course ID: "1234"
      - A full course URL: "https://moodle.ruppin.ac.il/course/view.php?id=1234"
      - A site URL: "https://moodle.ruppin.ac.il"
    """
    raw_input = raw_input.strip()
    if not default_site.startswith(('http://', 'https://')):
        default_site = f"https://{default_site}"
    default_site = default_site.rstrip('/')

    # 1. Numeric ID only
    if raw_input.isdigit():
        course_id = raw_input
        clean_url = f"{default_site}/course/view.php?id={course_id}"
        domain = urlparse(default_site).netloc or "moodle"
        return clean_url, course_id, domain

    # 2. URL or domain
    if not raw_input.startswith(('http://', 'https://')):
        raw_input = f"https://{raw_input}"

    parsed = urlparse(raw_input)
    domain = parsed.netloc or "moodle"
    site_base = f"{parsed.scheme}://{domain}"

    match = re.search(r'id=(\d+)', raw_input)
    course_id = match.group(1) if match else ""

    if course_id:
        clean_url = f"{site_base}/course/view.php?id={course_id}"
    else:
        clean_url = raw_input

    return clean_url, course_id, domain

def prompt_auth_method(has_cli_user: bool = False, has_cli_cookie: bool = False) -> str:
    if has_cli_cookie:
        return 'manual'
    if has_cli_user:
        return 'auto'

    print(f"\n{Style.BOLD}--- STEP 1: AUTHENTICATION METHOD ---{Style.RESET}")
    print("Choose how to authenticate with Moodle:")
    print(f"  {Style.BOLD}[1]{Style.RESET} {Style.GREEN}Auto-login via Playwright{Style.RESET} (Enter username & password)")
    print(f"  {Style.BOLD}[2]{Style.RESET} Manual cookie (Copy MoodleSession from browser DevTools)")
    
    choice = input(f"\n{Style.BOLD}Login method [1/2] (default: 1) > {Style.RESET}").strip()
    if choice in ['2', 'manual', 'cookie', 'm']:
        return 'manual'
    return 'auto'

def prompt_playwright_credentials(
    cli_username: str = None,
    cli_password: str = None,
    cli_site: str = None,
    cli_course_id: str = None,
    cli_url: str = None
) -> tuple[str, str, str, str]:
    """
    Gathers credentials and course details for Playwright auto-login.
    Returns (site_url, username, password, course_id).
    """
    site_url = cli_site or "https://moodle.ruppin.ac.il"
    course_id = cli_course_id or ""

    # Check if course info was passed via CLI url
    if cli_url:
        clean_url, c_id, domain = resolve_course_url(cli_url, site_url)
        if c_id:
            course_id = c_id
        if domain:
            site_url = f"https://{domain}"

    print(f"\n{Style.BOLD}--- PLAYWRIGHT AUTO-LOGIN SETUP ---{Style.RESET}")

    # Site URL (only prompted if neither url nor custom site was specified)
    if not cli_url and (not cli_site or cli_site == "https://moodle.ruppin.ac.il"):
        site_in = input(f"Moodle Site URL [default: {Style.CYAN}https://moodle.ruppin.ac.il{Style.RESET}]: ").strip()
        if site_in:
            clean_url, c_id, domain = resolve_course_url(site_in)
            site_url = f"https://{domain}"
            if c_id and not course_id:
                course_id = c_id

    if not site_url.startswith(('http://', 'https://')):
        site_url = f"https://{site_url}"
    site_url = site_url.rstrip('/')

    # Username
    username = cli_username.strip() if cli_username else ""
    while not username:
        username = input(f"{Style.BOLD}Username / Student ID > {Style.RESET}").strip()
        if not username:
            print(f"{Style.RED}Username cannot be empty.{Style.RESET}")

    # Password
    password = cli_password if cli_password is not None else ""
    while not password:
        password = getpass.getpass(f"{Style.BOLD}Password (input hidden) > {Style.RESET}").strip()
        if not password:
            print(f"{Style.RED}Password cannot be empty.{Style.RESET}")

    # Course ID (if not already known)
    while not course_id or not course_id.isdigit():
        c_in = input(f"{Style.BOLD}Course ID number (e.g. 1234) > {Style.RESET}").strip()
        if not c_in:
            print(f"{Style.RED}Course ID cannot be empty.{Style.RESET}")
            continue
        _, extracted_id, _ = resolve_course_url(c_in, site_url)
        if extracted_id:
            course_id = extracted_id
            break
        print(f"{Style.RED}Invalid Course ID. Please enter numeric ID (e.g. 1234).{Style.RESET}")

    return site_url, username, password, course_id

def prompt_course_url(cli_url: str = None, cli_course_id: str = None, cli_site: str = "https://moodle.ruppin.ac.il") -> tuple[str, str, str]:
    if cli_url:
        clean_url, course_id, domain = resolve_course_url(cli_url, cli_site)
        if course_id:
            return clean_url, course_id, domain
        while not course_id or not course_id.isdigit():
            course_id = input(f"{Style.YELLOW}Enter numeric Course ID: {Style.RESET}").strip()
        clean_url = f"{clean_url.split('?')[0]}?id={course_id}"
        return clean_url, course_id, domain

    if cli_course_id:
        return resolve_course_url(cli_course_id, cli_site)

    print(f"\n{Style.BOLD}--- MOODLE COURSE SELECTION ---{Style.RESET}")
    print("Enter your full Course URL or numeric Course ID.")
    print(f"Example URL: {Style.CYAN}https://moodle.ruppin.ac.il/course/view.php?id=1234{Style.RESET}")
    print(f"Example ID:  {Style.CYAN}1234{Style.RESET} (site: {cli_site})\n")

    user_in = input(f"{Style.BOLD}Course URL or ID > {Style.RESET}").strip()
    while not user_in:
        print(f"{Style.RED}Input cannot be empty.{Style.RESET}")
        user_in = input(f"{Style.BOLD}Course URL or ID > {Style.RESET}").strip()

    clean_url, course_id, domain = resolve_course_url(user_in, cli_site)

    if not course_id:
        course_id = input(f"\n{Style.YELLOW}Could not extract ID automatically. Enter numeric Course ID: {Style.RESET}").strip()
        while not course_id or not course_id.isdigit():
            print(f"{Style.RED}Error: Course ID must be numeric.{Style.RESET}")
            course_id = input("Enter numeric Course ID: ").strip()
        base_url = clean_url.split('?')[0]
        clean_url = f"{base_url}?id={course_id}"
    else:
        print(f"\n{Style.GREEN}[+] Target Course ID:{Style.RESET} {Style.BOLD}{course_id}{Style.RESET} on {Style.CYAN}{domain}{Style.RESET}")
        confirm = input(f"Press {Style.BOLD}ENTER{Style.RESET} to confirm, or type the correct numeric ID: ").strip()
        if confirm and confirm.isdigit():
            course_id = confirm
            base_url = clean_url.split('?')[0]
            clean_url = f"{base_url}?id={course_id}"

    return clean_url, course_id, domain

def prompt_cookie(cli_cookie: str = None) -> str:
    if cli_cookie:
        return cli_cookie.strip()
        
    print(f"\n{Style.BOLD}--- STEP 2: GET YOUR MOODLESESSION COOKIE ---{Style.RESET}")
    print("Moodle protects session cookies with 'HttpOnly', so it must be copied from DevTools:\n")
    print(f"  1. In your browser (Chrome / Edge / Firefox), open your Moodle page.")
    print(f"  2. Press {Style.BOLD}F12{Style.RESET} (or right-click anywhere and choose {Style.BOLD}Inspect{Style.RESET}).")
    print(f"  3. Go to the {Style.BOLD}Application{Style.RESET} tab at the top (in Firefox: {Style.BOLD}Storage{Style.RESET}).")
    print(f"     {Style.DIM}(If hidden, click the '>>' arrow on the top bar of DevTools){Style.RESET}")
    print(f"  4. In the left sidebar under {Style.BOLD}Cookies{Style.RESET}, click on your Moodle site.")
    print(f"  5. Find {Style.CYAN}MoodleSession{Style.RESET}, double-click its {Style.BOLD}Value{Style.RESET}, and copy it ({Style.BOLD}Ctrl+C{Style.RESET}).\n")

    cookie_val = input(f"{Style.BOLD}Paste MoodleSession value here > {Style.RESET}").strip()
    while not cookie_val:
        print(f"{Style.RED}The cookie cannot be empty.{Style.RESET}")
        cookie_val = input(f"{Style.BOLD}Paste MoodleSession value here > {Style.RESET}").strip()
        
    return cookie_val


def prompt_nested_option(cli_nested: bool = None) -> bool:
    if cli_nested is not None:
        return cli_nested
        
    print(f"\n{Style.BOLD}--- STEP 3: DOWNLOAD PREFERENCES ---{Style.RESET}")
    print(f"Include nested files? ({Style.CYAN}Assignments, Homework PDFs, Solution sheets, Pages{Style.RESET})")
    choice = input(f"{Style.BOLD}Download nested files? [Y/n] (default: Y) > {Style.RESET}").strip().lower()
    
    if choice in ['n', 'no', '0']:
        return False
    return True

def find_downloadable_files_in_page(page_soup: BeautifulSoup, base_page_url: str) -> list[str]:
    """
    Scans a Moodle sub-page (Assignment, Page, Resource) for all downloadable file links.
    """
    found_urls = []
    seen = set()

    file_re = re.compile(r'pluginfile\.php|draftfile\.php|\.(pdf|docx?|pptx?|xlsx?|zip|rar|7z|py|c|cpp|txt|tar|gz|mat|m)(\?|$)', re.I)

    # 1. <a> tags
    for a in page_soup.find_all('a', href=file_re):
        raw_href = a.get('href', '')
        if raw_href and not raw_href.startswith('javascript:'):
            full = urljoin(base_page_url, raw_href)
            if full not in seen:
                seen.add(full)
                found_urls.append(full)

    # 2. <iframe> / <embed> / <object>
    for tag in page_soup.find_all(['iframe', 'embed'], src=file_re):
        src = tag.get('src', '')
        if src:
            full = urljoin(base_page_url, src)
            if full not in seen:
                seen.add(full)
                found_urls.append(full)
                
    for tag in page_soup.find_all('object', data=file_re):
        data_url = tag.get('data', '')
        if data_url:
            full = urljoin(base_page_url, data_url)
            if full not in seen:
                seen.add(full)
                found_urls.append(full)

    return found_urls

def process_item(item: dict, section_dir: str, session: requests.Session, auto_unpack: bool = True) -> tuple[int, int]:
    """
    Processes and downloads a single activity item (Resource, Folder, Assignment, Page).
    Returns (files_count, bytes_count).
    """
    link = item['href']
    mod_type = item['mod_type']
    item_title = item['title']

    type_label = {
        'assign': '📝 [Assignment]',
        'folder': '📁 [Folder]',
        'page': '📄 [Page]',
        'url': '🔗 [Link]',
        'resource': '📄'
    }.get(mod_type, '📄')

    downloaded_files = 0
    downloaded_bytes = 0

    try:
        res = session.get(link, allow_redirects=True, stream=True)

        # 1. Direct file download (e.g. forcedownload or direct link to file)
        cd = res.headers.get('Content-Disposition')
        content_type = res.headers.get('Content-Type', '').lower()
        is_html = 'text/html' in content_type

        if cd and ('filename' in cd or 'attachment' in cd) or (not is_html and res.status_code == 200):
            saved_name, byte_count, _ = stream_download_file(
                session, link, section_dir, initial_res=res, auto_unpack=auto_unpack
            )
            if saved_name:
                size_str = f" {Style.DIM}[{format_size(byte_count)}]{Style.RESET}" if byte_count else ""
                safe_print(f"  ├── {Style.GREEN}[+] Downloaded:{Style.RESET} {saved_name}{size_str}")
                return 1, byte_count
            return 0, 0

        # 2. Parse HTML page for folders, assignments, or embedded resources
        page_soup = BeautifulSoup(res.content, 'html.parser')

        # Check for Moodle mod/folder "Download folder" button
        folder_form = page_soup.find('form', action=re.compile(r'folder/download_folder\.php', re.I))
        if folder_form:
            action = urljoin(link, folder_form.get('action', ''))
            data = {inp.get('name'): inp.get('value', '') for inp in folder_form.find_all('input') if inp.get('name')}

            saved_name, byte_count, extracted_count = stream_download_file(
                session, action, section_dir, 
                default_name=f"{sanitize_filename(item_title)}.zip", 
                method='POST', data=data, auto_unpack=auto_unpack
            )
            if saved_name:
                size_str = f" {Style.DIM}[{format_size(byte_count)}]{Style.RESET}" if byte_count else ""
                if extracted_count > 0:
                    safe_print(f"  ├── {Style.GREEN}[+] Unpacked Folder:{Style.RESET} {saved_name}{size_str}")
                    return extracted_count, byte_count
                else:
                    safe_print(f"  ├── {Style.GREEN}[+] Downloaded Folder ZIP:{Style.RESET} {saved_name}{size_str}")
                    return 1, byte_count
            return 0, 0

        # Check for downloadable files inside assignment / page / resource
        found_file_urls = find_downloadable_files_in_page(page_soup, link)

        if found_file_urls:
            if mod_type in ['assign', 'page']:
                safe_print(f"  ├── {Style.BOLD}{type_label} {item_title}{Style.RESET} ({len(found_file_urls)} file{'s' if len(found_file_urls) > 1 else ''}):")
            
            for file_url in found_file_urls:
                if '?forcedownload=1' not in file_url and '&forcedownload=1' not in file_url:
                    file_url += "&forcedownload=1" if '?' in file_url else "?forcedownload=1"

                saved_name, byte_count, _ = stream_download_file(
                    session, file_url, section_dir, auto_unpack=auto_unpack
                )
                if saved_name:
                    size_str = f" {Style.DIM}[{format_size(byte_count)}]{Style.RESET}" if byte_count else ""
                    if mod_type in ['assign', 'page']:
                        safe_print(f"      ├── {Style.GREEN}[+] Downloaded:{Style.RESET} {saved_name}{size_str}")
                    else:
                        safe_print(f"  ├── {Style.GREEN}[+] Downloaded:{Style.RESET} {saved_name}{size_str}")
                    downloaded_files += 1
                    downloaded_bytes += byte_count
        else:
            if mod_type in ['assign', 'page']:
                safe_print(f"  ├── {Style.DIM}{type_label} {item_title}: No attached files found{Style.RESET}")
            else:
                safe_print(f"  ├── {Style.YELLOW}[-] No downloadable content found for {item_title}{Style.RESET}")

    except Exception as e:
        safe_print(f"  ├── {Style.RED}[!] Error processing {item_title}: {e}{Style.RESET}")

    return downloaded_files, downloaded_bytes

def main():
    parser = argparse.ArgumentParser(description="Moodle Course Downloader")
    parser.add_argument('--url', help="Full Moodle course URL (e.g., https://moodle.ruppin.ac.il/course/view.php?id=1234)")
    parser.add_argument('-c', '--course-id', help="Numeric course ID (e.g., 1234)")
    parser.add_argument('--site', default="https://moodle.ruppin.ac.il", help="Moodle site base URL (default: https://moodle.ruppin.ac.il)")
    parser.add_argument('--cookie', help="MoodleSession cookie value or full Cookie header")
    parser.add_argument('-u', '--username', help="Username or student ID for auto-login")
    parser.add_argument('-p', '--password', help="Password for auto-login")
    parser.add_argument('--headed', dest='headless', action='store_false', help="Run Playwright browser visibly (headed mode) to inspect login/2FA")
    parser.add_argument('--headless', dest='headless', action='store_true', help="Run Playwright browser in background (headless mode, default)")
    parser.add_argument('--output', help="Custom output directory path (optional)")
    parser.add_argument('--nested', dest='nested', action='store_true', help="Include nested files (Assignments, Solution sheets, Pages)")
    parser.add_argument('--no-nested', dest='nested', action='store_false', help="Only download direct resources and folders")
    parser.add_argument('--threads', type=int, default=5, help="Number of concurrent download threads (default: 5)")
    parser.add_argument('--no-unpack', dest='unpack', action='store_false', help="Do not automatically unpack folder ZIP archives")
    parser.set_defaults(nested=None, unpack=True, headless=True)
    args = parser.parse_args()

    print_banner()

    auth_method = prompt_auth_method(has_cli_user=bool(args.username), has_cli_cookie=bool(args.cookie))

    course_url = None
    course_id = None
    domain = None
    session = None
    course_title = "Moodle Course"
    user_name = None

    while True:
        moodle_cookie = None

        if auth_method == 'auto':
            if not ensure_playwright_ready(auto_install_prompt=not bool(args.username)):
                print(f"{Style.YELLOW}[*] Playwright unavailable. Switching to manual cookie mode.{Style.RESET}")
                auth_method = 'manual'
                continue

            site_url, username, password, course_id = prompt_playwright_credentials(
                cli_username=args.username,
                cli_password=args.password,
                cli_site=args.site,
                cli_course_id=args.course_id,
                cli_url=args.url
            )
            course_url = f"{site_url.rstrip('/')}/course/view.php?id={course_id}"
            domain = urlparse(site_url).netloc or "moodle"

            headless_mode = args.headless


            cookie_str, err = login_with_playwright(
                site_url=site_url,
                username=username,
                password=password,
                course_url=course_url,
                headless=headless_mode
            )

            if cookie_str:
                moodle_cookie = cookie_str
            else:
                print(f"\n{Style.RED}[!] Auto-login failed: {err}{Style.RESET}")
                if can_run_headed() and headless_mode:
                    print(f"{Style.YELLOW}[*] Tip: If your institution requires 2FA or CAPTCHA, try visible browser mode.{Style.RESET}")

                if args.username and args.password:
                    # Non-interactive CLI invocation failed
                    return

                print(f"\nHow would you like to proceed?")
                print(f"  [1] Retry auto-login in visible browser mode")
                print(f"  [2] Re-enter username & password")
                print(f"  [3] Enter MoodleSession cookie manually")
                print(f"  [4] Exit")
                c = input(f"Choice [1/2/3/4] (default: 1) > ").strip()
                if c == '2':
                    args.username = None
                    args.password = None
                    continue
                elif c in ['3', 'manual']:
                    auth_method = 'manual'
                    continue
                elif c in ['4', 'exit', 'q']:
                    return
                else:
                    args.headless = False
                    continue

        else: # auth_method == 'manual'
            if not course_url:
                course_url, course_id, domain = prompt_course_url(args.url, args.course_id, args.site)
            moodle_cookie = prompt_cookie(args.cookie)

        # Validate session by connecting to course_url
        session = setup_session(moodle_cookie, pool_size=max(20, args.threads * 3))

        print(f"\nConnecting to {Style.CYAN}{domain}{Style.RESET} ...")
        try:
            response = session.get(course_url)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"{Style.RED}Failed to reach {course_url}: {e}{Style.RESET}")
            if args.cookie or (args.username and args.password):
                return
            retry = input("Try again? [Y/n] > ").strip().lower()
            if retry in ['n', 'no']:
                return
            continue

        soup = BeautifulSoup(response.content, 'html.parser')

        # Check for login redirection or login form
        if "login" in response.url.lower() or soup.find('form', action=re.compile(r"login", re.I)):
            print(f"\n{Style.RED}[!] ERROR: Authentication failed.{Style.RESET}")
            print("Your session was not authenticated or the cookie was invalid/expired.\n")
            if args.cookie or (args.username and args.password):
                return
            args.cookie = None
            args.password = None
            auth_method = prompt_auth_method()
            continue

        # Extract Course Name & User name
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag:
            raw_title = title_tag.get_text(strip=True)
            course_title = re.sub(r'^(Course:\s*|\s*קורס:\s*)', '', raw_title, flags=re.IGNORECASE)
            course_title = course_title.split(' | ')[0].split(' - ')[0].strip()

        user_tag = soup.find(class_=re.compile(r'usertext|user-name|avatarmenu'))
        if user_tag:
            user_name = user_tag.get_text(strip=True)

        break

    # Step 3: Nested Files Option
    include_nested = prompt_nested_option(args.nested)

    # Setup Download Directory
    download_dir = args.output if args.output else f"moodle_course_{course_id}"
    os.makedirs(download_dir, exist_ok=True)
    abs_download_path = os.path.abspath(download_dir)

    # Clean Pre-flight Summary
    print(f"\n{Style.GREEN}{'=' * 70}{Style.RESET}")
    print(f"{Style.BOLD}{Style.GREEN}[+] AUTHENTICATED SUCCESSFULLY{Style.RESET}")
    print(f"  {Style.BOLD}Course:{Style.RESET}       {course_title}")
    if user_name:
        print(f"  {Style.BOLD}User:{Style.RESET}         {user_name}")
    print(f"  {Style.BOLD}Site:{Style.RESET}         {domain} (Course ID: {course_id})")
    print(f"  {Style.BOLD}Speed:{Style.RESET}        {args.threads} parallel download threads")
    print(f"  {Style.BOLD}Auto-Unpack:{Style.RESET}  {'Enabled (Folder archives extracted automatically)' if args.unpack else 'Disabled'}")
    print(f"  {Style.BOLD}Nested Files:{Style.RESET} {'Enabled (Assignments, Solutions, Pages)' if include_nested else 'Disabled (Resources & Folders only)'}")
    print(f"  {Style.BOLD}Folder:{Style.RESET}       {abs_download_path}")
    print(f"{Style.GREEN}{'=' * 70}{Style.RESET}\n")

    # Define module regex pattern based on user preference
    if include_nested:
        mod_regex = re.compile(r'/mod/(resource|folder|assign|page|url|h5pactivity)/view\.php\?id=\d+')
    else:
        mod_regex = re.compile(r'/mod/(resource|folder)/view\.php\?id=\d+')

    all_activity_links = soup.find_all('a', href=mod_regex)
    
    if not all_activity_links:
        print(f"{Style.YELLOW}[!] No downloadable resources or activities found on this course page.{Style.RESET}")
        print("Please check that materials are published and that you are enrolled.")
        return

    # Group links by section (preserving page order)
    grouped_links = OrderedDict()

    for a in all_activity_links:
        raw_href = a['href']
        href = urljoin(course_url, raw_href)
        activity_title = extract_clean_title(a)

        mod_match = re.search(r'/mod/(\w+)/', href)
        mod_type = mod_match.group(1) if mod_match else 'resource'

        section_name = "General"
        parent_section = a.find_parent(
            ['li', 'div', 'section'],
            class_=lambda c: c and ('course-section' in c or ('section' in c and 'main' in c) or 'section-item' in c)
        )

        if parent_section:
            heading = parent_section.find(['h2', 'h3', 'h4', 'h5', 'span'], class_=re.compile(r'sectionname|title|name|section-title'))
            if heading:
                section_name = heading.get_text(strip=True)
            else:
                aria_label = parent_section.get('aria-label')
                if aria_label:
                    section_name = aria_label

        safe_section_name = sanitize_filename(section_name)
        if not safe_section_name:
            safe_section_name = "General"

        if safe_section_name not in grouped_links:
            grouped_links[safe_section_name] = []

        if not any(item['href'] == href for item in grouped_links[safe_section_name]):
            grouped_links[safe_section_name].append({
                'href': href,
                'title': activity_title,
                'mod_type': mod_type
            })

    total_items = sum(len(items) for items in grouped_links.values())
    print(f"Found {len(grouped_links)} sections with {total_items} items to download.\n")

    total_downloaded_files = 0
    total_downloaded_bytes = 0

    # Process each section with parallel thread pool
    for section_idx, (safe_section_name, items) in enumerate(grouped_links.items(), 1):
        safe_print(f"{Style.BOLD}{Style.CYAN}[{section_idx}/{len(grouped_links)}] Section: {safe_section_name}{Style.RESET} {Style.DIM}({len(items)} items){Style.RESET}")
        section_dir = os.path.join(download_dir, safe_section_name)
        os.makedirs(section_dir, exist_ok=True)

        if len(items) > 1 and args.threads > 1:
            with ThreadPoolExecutor(max_workers=min(args.threads, len(items))) as executor:
                future_to_item = {
                    executor.submit(process_item, item, section_dir, session, args.unpack): item
                    for item in items
                }
                for future in as_completed(future_to_item):
                    f_count, b_count = future.result()
                    total_downloaded_files += f_count
                    total_downloaded_bytes += b_count
        else:
            for item in items:
                f_count, b_count = process_item(item, section_dir, session, args.unpack)
                total_downloaded_files += f_count
                total_downloaded_bytes += b_count

        safe_print()

    # Final Summary Box
    print(f"{Style.CYAN}{'=' * 70}{Style.RESET}")
    print(f"{Style.BOLD}{Style.GREEN}   ALL DONE! DOWNLOAD COMPLETED{Style.RESET}")
    print(f"   {Style.BOLD}Total Files:{Style.RESET}  {total_downloaded_files}")
    print(f"   {Style.BOLD}Total Size:{Style.RESET}   {format_size(total_downloaded_bytes)}")
    print(f"   {Style.BOLD}Saved To:{Style.RESET}     {abs_download_path}")
    print(f"{Style.CYAN}{'=' * 70}{Style.RESET}\n")

if __name__ == "__main__":
    main()
