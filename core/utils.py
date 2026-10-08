import os
import re
import sys
import shutil
import zipfile
import threading
from urllib.parse import unquote

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
    """Prints the application banner."""
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


def can_run_headed() -> bool:
    """Checks whether the environment supports displaying a graphical browser window."""
    if sys.platform in ["win32", "darwin"]:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

