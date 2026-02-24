@echo off
REM Progressive Agent — start script (Windows)

REM cd to project root (parent of scripts\)
cd /d "%~dp0\.."

echo === Progressive Agent ===
echo Project root: %CD%

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ and add it to PATH.
    pause
    exit /b 1
)

REM Show Python version
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo %%v

REM Check Python version is 3.11+
python -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.11+ required. Current version is too old.
    pause
    exit /b 1
)

REM Check .env
if not exist ".env" (
    echo ERROR: .env file not found.
    echo Run: copy .env.example .env and fill in your API keys.
    pause
    exit /b 1
)

echo Starting bot...
python -m src.main
if errorlevel 1 (
    echo.
    echo Bot exited with error.
    pause
)
