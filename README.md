# Moodle Course Downloader

A simple Python script to download all resources, presentations, documents, and folders from a Moodle course and organize them neatly into folders grouped by course sections.

## Features

- **Automated Login via Playwright**: Automatically logs in using your username and password to capture session cookies — no DevTools or manual cookie copying needed!
- **MFA / 2FA & SSO Compatible**: Supports Microsoft / Office 365 SSO, SAML, and visible browser (`--headed`) mode for SMS/Authenticator 2FA approval.
- **High-Speed Parallel Downloads**: Uses multi-threading (5 concurrent workers) for fast downloads
- **Auto-Unpack Folder Archives**: Automatically extracts downloaded Moodle folder ZIP archives into clean subdirectories
- **Nested Files Support**: Downloads attached homework PDFs, solution sheets, and page documents from inside Moodle Assignments (`mod/assign`) and Pages (`mod/page`)
- **Organized Course Structure**: Organizes all materials neatly by course sections/topics
- **UTF-8 & International Support**: Safely handles Hebrew, Arabic, and Unicode filenames on Windows/Linux/macOS
- **Automatic Course ID Extraction**: Parses course IDs from numeric input or full URLs automatically
- **Flexible CLI Options**: Supports `--username`, `--password`, `--course-id`, `--site`, `--url`, `--cookie`, `--headed`, `--nested`, `--threads`, `--no-unpack`, and `--output` flags

## Requirements

- Python 3.8+
- Internet connection
- Active Moodle account

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
   *(Note: Chromium will also be automatically installed on first run if missing).*

## Usage

### Windows (Batch / PowerShell)
Double-click `run_downloader.bat` or run `run_downloader.ps1`.

### Interactive Python Execution
```bash
python moodle_downloader.py
```
You will be prompted to:
1. **Choose Authentication Method**:
   - `[1] Auto-login with Playwright`: Enter your Moodle site (defaults to `https://moodle.ruppin.ac.il`), your username, password, and course ID. The script opens the browser in the background, logs in, extracts cookies, and begins downloading.
   - `[2] Manual MoodleSession cookie`: Enter the course URL and paste your `MoodleSession` cookie from browser DevTools (Application/Storage → Cookies).
2. **Download Preferences**: Choose whether to download nested files (Assignments, homework PDFs, solutions).

### Command-Line (CLI / Headless) Mode

#### 1. Automated Login (Playwright)
Provide your username, password, and course ID:
```bash
python moodle_downloader.py --username "my_user" --password "my_pass" --course-id 1234
```
*(If `--site` is omitted, it defaults to `https://moodle.ruppin.ac.il`).*

For other Moodle sites:
```bash
python moodle_downloader.py --site "https://moodle.tau.ac.il" --course-id 5678 --username "my_user" --password "my_pass"
```

To prompt securely for your password (hides input from terminal history):
```bash
python moodle_downloader.py --username "my_user" --course-id 1234
```

If your institution uses 2FA / CAPTCHA / Microsoft Authenticator approval, run with `--headed` to complete the verification prompt visually:
```bash
python moodle_downloader.py --username "my_user" --course-id 1234 --headed
```

#### 2. Manual Cookie Mode
```bash
python moodle_downloader.py --url "https://moodle.ruppin.ac.il/course/view.php?id=1234" --cookie "YOUR_MOODLESESSION_COOKIE" --output "./my_course_folder"
```

## CLI Arguments Reference

| Argument | Description | Default |
|---|---|---|
| `-u`, `--username` | Username or student ID for auto-login | None (prompted) |
| `-p`, `--password` | Password for auto-login (masked if prompted) | None (prompted) |
| `-c`, `--course-id`| Numeric Moodle Course ID (e.g., `1234`) | None (prompted) |
| `--site` | Moodle base URL | `https://moodle.ruppin.ac.il` |
| `--url` | Full Moodle course URL | None |
| `--cookie` | Manual `MoodleSession` cookie string | None |
| `--headed` | Run browser visibly (useful for 2FA / SSO approval) | Disabled (headless) |
| `--headless` | Run browser in background | Enabled |
| `--nested` / `--no-nested` | Download nested files (Assignments, solutions) | Enabled |
| `--threads` | Number of concurrent download workers | `5` |
| `--output` | Destination download directory | `moodle_course_{ID}` |
| `--no-unpack` | Keep folder ZIP archives zipped | False (auto-unpacks) |

## Output

Files are saved in a folder named `moodle_course_{ID}` with subfolders for each course section.

## Dependencies

- `requests==2.31.0` - HTTP connection pooling and file streaming
- `beautifulsoup4==4.12.3` - HTML parsing
- `playwright>=1.40.0` - Automated browser login and cookie extraction

## Disclaimer

This tool is for educational purposes only. Make sure you have permission to download course materials. Respect copyright and your institution's terms of service.

## License

MIT License - see LICENSE file for details