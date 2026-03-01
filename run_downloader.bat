@echo off

:: Set console colors (bright whight on blue background))
color 9F

echo ================================================================
echo              MOODLE COURSE DOWNLOADER                 
echo ================================================================
echo.
echo WARNING: This tool requires Python to be installed on your computer.
echo If Python is not installed, please download it from https://www.python.org/
echo.
echo Installing dependencies...
python -m pip install -r "%~dp0requirements.txt" --quiet

echo.
echo Starting downloader...
echo ================================================================
echo.

:: Run the python script
python "%~dp0moodle_downloader.py"

echo.
echo ================================================================
echo   ALL DONE! Press any key to exit...
echo ================================================================
pause >nul
