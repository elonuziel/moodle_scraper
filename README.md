# Moodle Course Downloader

A simple Python script to download all resources, presentations, documents, and folders from a Moodle course and organize them neatly into folders grouped by course sections.

## Features

- Downloads all downloadable resources from a Moodle course
- Organizes files by course sections/lessons
- Handles both individual files and folder archives
- Supports UTF-8 filenames
- Automatic course ID extraction from URLs
- Interactive prompts for user input

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
```bash
python moodle_downloader.py
```

### What the script does:

1. **Course URL**: Enter the full URL of your Moodle course page
   - Example: `https://moodle.ruppin.ac.il/course/view.php?id=1234`

2. **Course ID Confirmation**: The script extracts the course ID automatically
   - Press ENTER to confirm or enter a different ID if needed

3. **Login Cookie**: You need to provide your MoodleSession cookie
   - Log into Moodle in your browser
   - Press F12 → Application/Storage tab → Cookies → MoodleSession → Copy the Value

4. **Download**: The script will download all files and organize them into folders

## Output

Files are saved in a folder named `moodle_course_{ID}` with subfolders for each course section.

## Dependencies

- `requests==2.31.0` - HTTP requests
- `beautifulsoup4==4.12.3` - HTML parsing

## Disclaimer

This tool is for educational purposes only. Make sure you have permission to download course materials. Respect copyright and your institution's terms of service.

## License

MIT License - see LICENSE file for details