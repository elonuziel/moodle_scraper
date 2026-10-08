import os
import re
import sys
import getpass
import argparse
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from core.utils import (
    Style,
    safe_print,
    print_banner,
    format_size,
    can_run_headed,
)
from core.auth import (
    setup_session,
    ensure_playwright_ready,
    login_with_playwright,
)
from core.scraper import parse_course_activities
from core.downloader import download_course_sections


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
    """Prompts the user to choose their preferred authentication method."""
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
    """Prompts or resolves course URL for manual cookie mode."""
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
    """Prompts the user to paste their MoodleSession cookie from DevTools."""
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
    """Prompts for downloading nested files (assignments, pages, solutions)."""
    if cli_nested is not None:
        return cli_nested

    print(f"\n{Style.BOLD}--- DOWNLOAD PREFERENCES ---{Style.RESET}")
    print(f"Include nested files? ({Style.CYAN}Assignments, Homework PDFs, Solution sheets, Pages{Style.RESET})")
    choice = input(f"{Style.BOLD}Download nested files? [Y/n] (default: Y) > {Style.RESET}").strip().lower()

    if choice in ['n', 'no', '0']:
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    """Builds and returns the CLI argument parser."""
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
    return parser


def main():
    """Main application entrypoint."""
    parser = build_parser()
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
                    print(f"{Style.YELLOW}[*] Tip: If your institution requires 2FA or CAPTCHA, try visible browser mode (--headed).{Style.RESET}")

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

        else:  # auth_method == 'manual'
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

    # Download Preferences
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

    # Parse course page activities
    grouped_links = parse_course_activities(soup, course_url, include_nested=include_nested)

    if not grouped_links:
        print(f"{Style.YELLOW}[!] No downloadable resources or activities found on this course page.{Style.RESET}")
        print("Please check that materials are published and that you are enrolled.")
        return

    total_items = sum(len(items) for items in grouped_links.values())
    print(f"Found {len(grouped_links)} sections with {total_items} items to download.\n")

    # Process parallel downloads
    total_downloaded_files, total_downloaded_bytes = download_course_sections(
        grouped_links=grouped_links,
        download_dir=download_dir,
        session=session,
        threads=args.threads,
        auto_unpack=args.unpack
    )

    # Final Summary Box
    print(f"{Style.CYAN}{'=' * 70}{Style.RESET}")
    print(f"{Style.BOLD}{Style.GREEN}   ALL DONE! DOWNLOAD COMPLETED{Style.RESET}")
    print(f"   {Style.BOLD}Total Files:{Style.RESET}  {total_downloaded_files}")
    print(f"   {Style.BOLD}Total Size:{Style.RESET}   {format_size(total_downloaded_bytes)}")
    print(f"   {Style.BOLD}Saved To:{Style.RESET}     {abs_download_path}")
    print(f"{Style.CYAN}{'=' * 70}{Style.RESET}\n")

