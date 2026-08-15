# Moodle Course Downloader

A simple Python script to download all resources, presentations, documents, and folders from a Moodle course and organize them neatly into folders grouped by course sections.

## Features

- **High-Speed Parallel Downloads**: Uses multi-threading (5 concurrent workers) for fast downloads
- **Auto-Unpack Folder Archives**: Automatically extracts downloaded Moodle folder ZIP archives into clean subdirectories
- **Nested Files Support**: Downloads attached homework PDFs, solution sheets, and page documents from inside Moodle Assignments (`mod/assign`) and Pages (`mod/page`)
- **Organized Course Structure**: Organizes all materials neatly by course sections/topics
- **UTF-8 & International Support**: Safely handles Hebrew, Arabic, and Unicode filenames on Windows/Linux/macOS
- **Automatic Course ID Extraction**: Parses course IDs from URLs automatically
- **Flexible CLI Options**: Supports `--url`, `--cookie`, `--nested`, `--threads`, `--no-unpack`, and `--output` flags

## Requirements

- Python 3.6+
- Internet connection
- Valid Moodle login session

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Windows (Batch File)
Double-click `run_downloader.bat` or run it from command prompt.

### Manual Python Execution
Interactive mode:
```bash
python moodle_downloader.py
```

Command-line (headless) mode:
```bash
python moodle_downloader.py --url "https://moodle.ruppin.ac.il/course/view.php?id=1234" --cookie "YOUR_MOODLESESSION_COOKIE" --output "./my_course_folder"
```

### What the script does:

1. **Course URL**: Enter the full URL of your Moodle course page
   - Example: `https://moodle.ruppin.ac.il/course/view.php?id=1234`

2. **Course ID Confirmation**: The script extracts the course ID automatically
   - Press ENTER to confirm or enter a different ID if needed

3. **Login Cookie**: The script needs your active Moodle session:
   - Log into Moodle in your browser (Chrome / Edge / Firefox)
   - Press `F12` (or right-click → **Inspect**)
   - Go to the **Application** tab at the top (in Firefox: **Storage**)
   - In the left sidebar under **Cookies**, click your Moodle domain
   - Copy the **Value** of `MoodleSession` (double-click value → `Ctrl+C`) and paste it into the script

4. **Download**: The script automatically validates your session, displays the course name and user details, and downloads all files structured neatly by section with progress and size indicators.

## Output

Files are saved in a folder named `moodle_course_{ID}` with subfolders for each course section.

## Dependencies

- `requests==2.31.0` - HTTP requests
- `beautifulsoup4==4.12.3` - HTML parsing

## Disclaimer

This tool is for educational purposes only. Make sure you have permission to download course materials. Respect copyright and your institution's terms of service.

## License

MIT License - see LICENSE file for details