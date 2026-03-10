# Set Powershell colors (White text on Blue background)
$Host.UI.RawUI.ForegroundColor = "White"
$Host.UI.RawUI.BackgroundColor = "LightBlue"
Clear-Host

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "             MOODLE COURSE DOWNLOADER                 " -ForegroundColor White -BackgroundColor DarkBlue
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "WARNING: This tool requires Python to be installed on your computer." -ForegroundColor Yellow
Write-Host "If Python is not installed, please download it from https://www.python.org/" -ForegroundColor Yellow
Write-Host ""
Write-Host "Installing dependencies..." -ForegroundColor Gray

# Get the directory of the script
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Install dependencies
python -m pip install -r "$scriptDir\requirements.txt" --quiet

Write-Host ""
Write-Host "Starting downloader..." -ForegroundColor Gray
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Run the python script
python "$scriptDir\moodle_downloader.py"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  ALL DONE! Press any key to exit..." -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan

# Wait for key press
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
