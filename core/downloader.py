import os
import re
import shutil
from urllib.parse import urlparse, unquote, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from core.utils import (
    Style,
    safe_print,
    sanitize_filename,
    format_size,
    get_filename_from_cd,
    safe_extract_zip
)
from core.scraper import find_downloadable_files_in_page


def stream_download_file(
    session: requests.Session,
    url: str,
    target_dir: str,
    default_name: str = None,
    method: str = 'GET',
    data: dict = None,
    initial_res: requests.Response = None,
    auto_unpack: bool = True
) -> tuple[str, int, int]:
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


def download_course_sections(
    grouped_links: dict,
    download_dir: str,
    session: requests.Session,
    threads: int = 5,
    auto_unpack: bool = True
) -> tuple[int, int]:
    """
    Downloads all items in grouped_links section by section using ThreadPoolExecutor.
    Returns (total_downloaded_files, total_downloaded_bytes).
    """
    total_downloaded_files = 0
    total_downloaded_bytes = 0

    for section_idx, (safe_section_name, items) in enumerate(grouped_links.items(), 1):
        safe_print(f"{Style.BOLD}{Style.CYAN}[{section_idx}/{len(grouped_links)}] Section: {safe_section_name}{Style.RESET} {Style.DIM}({len(items)} items){Style.RESET}")
        section_dir = os.path.join(download_dir, safe_section_name)
        os.makedirs(section_dir, exist_ok=True)

        if len(items) > 1 and threads > 1:
            with ThreadPoolExecutor(max_workers=min(threads, len(items))) as executor:
                future_to_item = {
                    executor.submit(process_item, item, section_dir, session, auto_unpack): item
                    for item in items
                }
                for future in as_completed(future_to_item):
                    f_count, b_count = future.result()
                    total_downloaded_files += f_count
                    total_downloaded_bytes += b_count
        else:
            for item in items:
                f_count, b_count = process_item(item, section_dir, session, auto_unpack)
                total_downloaded_files += f_count
                total_downloaded_bytes += b_count

        safe_print()

    return total_downloaded_files, total_downloaded_bytes

