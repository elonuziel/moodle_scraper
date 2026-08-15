import os
import re
import sys
import shutil
import zipfile
import argparse
import threading
from urllib.parse import urljoin, unquote, urlparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

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

def prompt_course_url(cli_url: str = None) -> tuple[str, str, str]:
    course_url = cli_url.strip() if cli_url else ""
    
    if not course_url:
        print(f"{Style.BOLD}--- STEP 1: MOODLE COURSE URL ---{Style.RESET}")
        print("Paste the full link of your course page.")
        print(f"Example: {Style.CYAN}https://moodle.ruppin.ac.il/course/view.php?id=1234{Style.RESET}\n")
        
        course_url = input(f"{Style.BOLD}Course URL > {Style.RESET}").strip()
        while not course_url:
            print(f"{Style.RED}Please enter a valid URL.{Style.RESET}")
            course_url = input(f"{Style.BOLD}Course URL > {Style.RESET}").strip()

    parsed = urlparse(course_url)
    domain = parsed.netloc or "moodle"
    
    match = re.search(r'id=(\d+)', course_url)
    course_id = match.group(1) if match else ""

    if not cli_url:
        if course_id:
            print(f"\n{Style.GREEN}[+] Detected Course ID:{Style.RESET} {Style.BOLD}{course_id}{Style.RESET} on {Style.CYAN}{domain}{Style.RESET}")
            confirm = input(f"Press {Style.BOLD}ENTER{Style.RESET} to confirm, or type the correct numeric ID: ").strip()
            if confirm:
                course_id = confirm
        else:
            course_id = input(f"\n{Style.YELLOW}Could not extract ID automatically. Enter numeric Course ID: {Style.RESET}").strip()

    while not course_id or not course_id.isdigit():
        print(f"{Style.RED}Error: Course ID must be numeric.{Style.RESET}")
        course_id = input("Enter numeric Course ID: ").strip()

    base_url = course_url.split('?')[0] if '?' in course_url else course_url
    clean_course_url = f"{base_url}?id={course_id}"
    
    return clean_course_url, course_id, domain

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
    parser.add_argument('--cookie', help="MoodleSession cookie value or full Cookie header")
    parser.add_argument('--output', help="Custom output directory path (optional)")
    parser.add_argument('--nested', dest='nested', action='store_true', help="Include nested files (Assignments, Solution sheets, Pages)")
    parser.add_argument('--no-nested', dest='nested', action='store_false', help="Only download direct resources and folders")
    parser.add_argument('--threads', type=int, default=5, help="Number of concurrent download threads (default: 5)")
    parser.add_argument('--no-unpack', dest='unpack', action='store_false', help="Do not automatically unpack folder ZIP archives")
    parser.set_defaults(nested=None, unpack=True)
    args = parser.parse_args()

    print_banner()

    # Step 1: Course URL
    course_url, course_id, domain = prompt_course_url(args.url)

    # Step 2: Cookie Authentication Loop
    session = None
    course_title = "Moodle Course"
    user_name = None

    while True:
        moodle_cookie = prompt_cookie(args.cookie)
        session = setup_session(moodle_cookie, pool_size=max(20, args.threads * 3))

        print(f"\nConnecting to {Style.CYAN}{domain}{Style.RESET} ...")
        try:
            response = session.get(course_url)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"{Style.RED}Failed to reach {course_url}: {e}{Style.RESET}")
            if args.cookie:
                return
            continue

        soup = BeautifulSoup(response.content, 'html.parser')

        # Check for login redirection or login form
        if "login" in response.url.lower() or soup.find('form', action=re.compile(r"login", re.I)):
            print(f"\n{Style.RED}[!] ERROR: Authentication failed.{Style.RESET}")
            print("Your MoodleSession cookie was invalid or expired.")
            print("Please make sure you are logged into Moodle in your browser and copied the fresh value.\n")
            if args.cookie:
                return
            args.cookie = None
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
