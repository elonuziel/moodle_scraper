import os
import re
import sys
import argparse
from urllib.parse import urljoin, unquote, urlparse
from collections import OrderedDict
import requests
from bs4 import BeautifulSoup

def sanitize_filename(name: str, max_length: int = 200) -> str:
    """
    Removes invalid characters for Windows/Linux/macOS file systems and prevents path traversal.
    """
    if not name:
        return "unnamed_file"
    
    name = name.strip()
    # Prevent path traversal by stripping leading dots and slashes
    name = re.sub(r'^[./\\]+', '', name)
    # Replace directory separators and forbidden filesystem characters (\ / * ? : " < > |)
    name = re.sub(r'[\\/*?:"<>|]', '_', name)
    # Remove control characters and clean trailing spaces/dots
    name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip('. ')
    
    if not name:
        return "unnamed_file"
        
    return name[:max_length]

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
        # Fix Moodle's UTF-8 filenames sent as raw bytes over HTTP latin1 headers
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

def setup_session(moodle_cookie: str) -> requests.Session:
    """
    Initializes a requests.Session with browser-like headers and user cookies.
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,he;q=0.8',
    })
    
    # Handle full cookie header (e.g. "MoodleSession=abc; other=123") or raw session value
    if '=' in moodle_cookie:
        for part in moodle_cookie.split(';'):
            if '=' in part:
                k, v = part.strip().split('=', 1)
                session.cookies.set(k.strip(), v.strip())
    else:
        session.cookies.set('MoodleSession', moodle_cookie.strip())
        
    return session

def stream_download_file(session: requests.Session, url: str, target_dir: str, default_name: str = None, 
                         method: str = 'GET', data: dict = None, initial_res: requests.Response = None) -> str:
    """
    Streams a file download to target_dir. Resolves filename from headers or URL.
    Avoids filename collisions by appending (1), (2), etc.
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
                # Derive from final response URL path
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
            
        with open(filepath, 'wb') as f:
            for chunk in res.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    
        return os.path.basename(filepath)
    except Exception as e:
        print(f"   [!] Failed download from {url}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Moodle Course Downloader")
    parser.add_argument('--url', help="Full Moodle course URL (e.g., https://moodle.ruppin.ac.il/course/view.php?id=1234)")
    parser.add_argument('--cookie', help="MoodleSession cookie value or full Cookie header")
    parser.add_argument('--output', help="Output directory path (optional)")
    args = parser.parse_args()

    print("=== Moodle Course Downloader ===")
    print("This script will download all resources and folders from a Moodle course.")
    print("-" * 80)
    print()

    # Step 1: Course URL
    course_url = args.url.strip() if args.url else ""
    if not course_url:
        print("STEP 1: MOODLE COURSE URL")
        print("Please paste the full URL of your Moodle course page.")
        print("Example: https://moodle.ruppin.ac.il/course/view.php?id=1234")
        print()
        course_url = input("Enter the full Moodle course URL: ").strip()
        while not course_url:
            print("Please enter a valid URL.")
            course_url = input("Enter the full Moodle course URL: ").strip()

    # Extract ID from URL
    match = re.search(r'id=(\d+)', course_url)
    course_id = match.group(1) if match else ""

    if not args.url:
        if course_id:
            print(f"\n[?] Extracted Course ID: {course_id}")
            confirm = input("Press ENTER to confirm, or type the correct ID: ").strip()
            if confirm:
                course_id = confirm
        if not course_id:
            course_id = input("\nCould not extract ID automatically. Please enter the numeric Course ID: ").strip()

    if not course_id or not course_id.isdigit():
        print("Error: Course ID must be numeric.")
        return

    # Reconstruct course URL in case ID changed
    base_url = course_url.split('?')[0] if '?' in course_url else course_url
    course_url = f"{base_url}?id={course_id}"

    # Step 2: Cookie
    moodle_cookie = args.cookie.strip() if args.cookie else ""
    if not moodle_cookie:
        print(f"\n[OK] Using Course ID: {course_id}")
        print()
        print("STEP 2: GET YOUR LOGIN COOKIE")
        print("To download files, this script needs your active Moodle login.")
        print("  1. Log into your Moodle in a web browser.")
        print("  2. Press F12 to open Developer Tools.")
        print("  3. Go to the Application tab (or Storage in Firefox).")
        print("  4. Click on 'Cookies' on the left side.")
        print("  5. Find the row named 'MoodleSession' and copy its exact Value.")
        print("     (Example: 6ir67p4doaf4pb0gb4oavl6puq)")
        print()
        moodle_cookie = input("Paste your MoodleSession cookie value: ").strip()
        while not moodle_cookie:
            print("The cookie cannot be empty. We need it to bypass the login screen.")
            moodle_cookie = input("Paste your MoodleSession cookie value: ").strip()

    session = setup_session(moodle_cookie)

    download_dir = args.output if args.output else f"moodle_course_{course_id}"
    os.makedirs(download_dir, exist_ok=True)
    print(f"\nFiles will be saved to: {os.path.abspath(download_dir)}")

    print(f"Accessing {course_url} ...")
    try:
        response = session.get(course_url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to access course: {e}")
        return

    soup = BeautifulSoup(response.content, 'html.parser')

    # Check for login redirection or login form
    if "login" in response.url.lower() or soup.find('form', action=re.compile(r"login", re.I)):
        print("\n[!] ERROR: Authentication failed.")
        print("Your MoodleSession cookie might be invalid, expired, or incorrect.")
        print("Please log into Moodle in your browser, and copy the fresh 'MoodleSession' cookie.")
        return

    # Find all resource and folder links anywhere on the page
    all_links = soup.find_all('a', href=re.compile(r'/mod/(resource|folder)/view\.php\?id='))
    if not all_links:
        print("Could not find any downloadable resources or folders in this course.")
        print("Make sure you are enrolled, the course has files, and the ID is correct.")
        return

    print(f"Found {len(all_links)} downloadable items.")

    # Group links by section (preserving order)
    grouped_links = OrderedDict()

    for a in all_links:
        raw_href = a['href']
        href = urljoin(course_url, raw_href)

        section_name = "General"
        # Match Moodle 3/4 course sections
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

        if href not in grouped_links[safe_section_name]:
            grouped_links[safe_section_name].append(href)

    for safe_section_name, links in grouped_links.items():
        print(f"\n--- Processing '{safe_section_name}' ({len(links)} items) ---")
        section_dir = os.path.join(download_dir, safe_section_name)
        os.makedirs(section_dir, exist_ok=True)

        for link in links:
            try:
                print(f"Evaluating link: {link}")
                res = session.get(link, allow_redirects=True, stream=True)

                # 1. Direct file download (e.g. forcedownload or direct redirect to file)
                cd = res.headers.get('Content-Disposition')
                content_type = res.headers.get('Content-Type', '').lower()
                is_html = 'text/html' in content_type

                if cd and ('filename' in cd or 'attachment' in cd) or (not is_html and res.status_code == 200):
                    saved_name = stream_download_file(session, link, section_dir, initial_res=res)
                    if saved_name:
                        print(f"   [+] Downloaded direct file: {saved_name}")
                    continue

                # 2. If it's an HTML page, parse for folders or embedded resources
                page_soup = BeautifulSoup(res.content, 'html.parser')

                # Check for "Download folder" button (Moodle mod/folder)
                folder_form = page_soup.find('form', action=re.compile(r'folder/download_folder\.php', re.I))
                if folder_form:
                    action = urljoin(link, folder_form.get('action', ''))
                    data = {inp.get('name'): inp.get('value', '') for inp in folder_form.find_all('input') if inp.get('name')}

                    print("   [*] Found folder. Downloading ZIP archive...")
                    saved_name = stream_download_file(session, action, section_dir, 
                                                      default_name=f"folder_{link.split('=')[-1]}.zip", 
                                                      method='POST', data=data)
                    if saved_name:
                        print(f"   [+] Downloaded folder: {saved_name}")
                    continue

                # Check for embedded or listed file links (pluginfile.php)
                file_elements = page_soup.find_all('a', href=re.compile(r'pluginfile\.php'))
                # Also check iframe / object / embed tags in case resources are embedded in an iframe
                for tag in page_soup.find_all(['iframe', 'embed'], src=re.compile(r'pluginfile\.php')):
                    file_elements.append(tag)
                for tag in page_soup.find_all('object', data=re.compile(r'pluginfile\.php')):
                    file_elements.append(tag)

                downloaded_something = False
                seen_file_urls = set()

                for elem in file_elements:
                    raw_file_url = elem.get('href') or elem.get('src') or elem.get('data')
                    if not raw_file_url:
                        continue

                    file_url = urljoin(link, raw_file_url)
                    if file_url in seen_file_urls:
                        continue
                    seen_file_urls.add(file_url)

                    # Ensure forcedownload is added to bypass the in-browser viewer
                    if '?forcedownload=1' not in file_url and '&forcedownload=1' not in file_url:
                        file_url += "&forcedownload=1" if '?' in file_url else "?forcedownload=1"

                    saved_name = stream_download_file(session, file_url, section_dir)
                    if saved_name:
                        print(f"   [+] Downloaded file: {saved_name}")
                        downloaded_something = True

                if not downloaded_something:
                    print("   [-] Did not find any downloadable content at this link.")

            except Exception as e:
                print(f"   [!] Error processing {link}: {e}")

    print(f"\nDone! All files have been downloaded to the '{download_dir}' directory.")

if __name__ == "__main__":
    main()
