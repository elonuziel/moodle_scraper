#!/usr/bin/env python3
"""
Moodle Course Material Downloader
Fast parallel downloads for presentations, files, folders & solutions.
"""

import os
import sys

# Ensure the repository root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Dependency pre-flight check for user-friendly errors
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    missing_mod = getattr(e, 'name', 'required packages')
    print(f"\n[!] Missing dependency: {missing_mod}")
    print("Please install required dependencies:")
    print("    pip install -r requirements.txt\n")
    sys.exit(1)

from core.cli import (
    main,
    resolve_course_url,
    prompt_course_url,
    prompt_cookie,
    prompt_auth_method,
    prompt_playwright_credentials,
    prompt_nested_option,
)
from core.utils import Style, safe_print, print_banner, sanitize_filename, format_size, can_run_headed
from core.auth import setup_session, login_with_playwright, ensure_playwright_ready
from core.downloader import stream_download_file, process_item, download_course_sections
from core.scraper import extract_clean_title, find_downloadable_files_in_page, parse_course_activities

__all__ = [
    "main",
    "Style",
    "safe_print",
    "print_banner",
    "sanitize_filename",
    "format_size",
    "can_run_headed",
    "setup_session",
    "login_with_playwright",
    "ensure_playwright_ready",
    "stream_download_file",
    "process_item",
    "download_course_sections",
    "extract_clean_title",
    "find_downloadable_files_in_page",
    "parse_course_activities",
    "resolve_course_url",
    "prompt_course_url",
    "prompt_cookie",
    "prompt_auth_method",
    "prompt_playwright_credentials",
    "prompt_nested_option",
]

if __name__ == "__main__":
    main()
