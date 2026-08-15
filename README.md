# Moodle Course Downloader

A simple Python script to download all resources, presentations, documents, and folders from a Moodle course and organize them neatly into folders grouped by course sections.

## Features

- Downloads all downloadable resources and folders from a Moodle course
- **Nested Files Support**: Downloads attached homework PDFs, solution sheets, and page documents from inside Moodle Assignments (`mod/assign`) and Pages (`mod/page`)
- Organizes files neatly by course sections/topics
- Handles individual files, embedded attachments, and folder ZIP archives
- Supports UTF-8 / Hebrew / international filenames
- Automatic course ID extraction from URLs
- Interactive prompts with CLI argument support (`--url`, `--cookie`, `--nested`, `--output`)

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