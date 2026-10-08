import sys
from unittest.mock import MagicMock

# Mock bs4 so we can test moodle_downloader without bs4 installed
sys.modules['bs4'] = MagicMock()

import moodle_downloader

def test_resolve_course_url():
    # 1. Numeric ID only
    url, cid, domain = moodle_downloader.resolve_course_url("1234")
    assert cid == "1234", f"Expected '1234', got '{cid}'"
    assert url == "https://moodle.ruppin.ac.il/course/view.php?id=1234", f"Unexpected url: {url}"
    assert domain == "moodle.ruppin.ac.il", f"Unexpected domain: {domain}"

    # 2. Full URL with ID
    url, cid, domain = moodle_downloader.resolve_course_url("https://moodle.tau.ac.il/course/view.php?id=5678")
    assert cid == "5678", f"Expected '5678', got '{cid}'"
    assert url == "https://moodle.tau.ac.il/course/view.php?id=5678", f"Unexpected url: {url}"
    assert domain == "moodle.tau.ac.il", f"Unexpected domain: {domain}"

    # 3. URL without scheme
    url, cid, domain = moodle_downloader.resolve_course_url("moodle.ruppin.ac.il/course/view.php?id=9999")
    assert cid == "9999", f"Expected '9999', got '{cid}'"
    assert url == "https://moodle.ruppin.ac.il/course/view.php?id=9999", f"Unexpected url: {url}"
    assert domain == "moodle.ruppin.ac.il", f"Unexpected domain: {domain}"

    # 4. Custom site with numeric ID
    url, cid, domain = moodle_downloader.resolve_course_url("4321", default_site="https://custom.edu")
    assert cid == "4321"
    assert url == "https://custom.edu/course/view.php?id=4321"
    assert domain == "custom.edu"

    print("[PASS] test_resolve_course_url")

def test_session_cookies():
    cookie_str = "MoodleSession=abc123xyz; OtherCookie=hello_world"
    session = moodle_downloader.setup_session(cookie_str)
    assert session.cookies.get("MoodleSession") == "abc123xyz"
    assert session.cookies.get("OtherCookie") == "hello_world"

    single_cookie = "mysessionvalue"
    session2 = moodle_downloader.setup_session(single_cookie)
    assert session2.cookies.get("MoodleSession") == "mysessionvalue"

    print("[PASS] test_session_cookies")

def test_playwright_missing_handling():
    assert moodle_downloader.ensure_playwright_ready(auto_install_prompt=False) == False
    cookie, err = moodle_downloader.login_with_playwright("https://moodle.ruppin.ac.il", "user", "pass")
    assert cookie is None
    assert "playwright" in err.lower()

    print("[PASS] test_playwright_missing_handling")

if __name__ == "__main__":
    test_resolve_course_url()
    test_session_cookies()
    test_playwright_missing_handling()
    print("\nALL LOGIC TESTS PASSED SUCCESSFULLY!")
