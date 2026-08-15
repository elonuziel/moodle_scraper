@echo off
setlocal

:: Check if python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [!] ERROR: Python is not installed or not found on your PATH.
    echo Please install Python 3.8+ from https://www.python.org/
    echo Make sure to check "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Install dependencies quietly
python -m pip install -r "%~dp0requirements.txt" --quiet

:: Run the downloader
python "%~dp0moodle_downloader.py"

echo.
pause
