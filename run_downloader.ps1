$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Check if Python is installed
try {
    $null = python --version
} catch {
    Write-Host ""
    Write-Host "[!] ERROR: Python is not installed or not found in PATH." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/ and check 'Add Python to PATH'." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Install dependencies quietly
python -m pip install -r "$scriptDir\requirements.txt" --quiet

# Run the python script
python "$scriptDir\moodle_downloader.py"

Write-Host ""
Read-Host "Press Enter to exit"
