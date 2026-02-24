@echo off
REM Progressive Agent — Setup (Windows)
REM Installs dependencies and configures .env

cd /d "%~dp0"

echo.
echo  Progressive Agent — Setup
echo  ========================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  Python not found. Install Python 3.11+ from:
    echo  https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH"!
    pause
    exit /b 1
)

REM Install dependencies
echo  Installing dependencies...
python -m pip install -r requirements.txt --disable-pip-version-check
echo.

REM Run interactive setup
python scripts/setup.py

pause
