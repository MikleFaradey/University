@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo ERROR: Python 3 was not found.
    echo Install Python 3 and enable "Add Python to PATH".
    pause
    exit /b 1
)

%PYTHON_CMD% client_gui.py
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Client exited with code %RC%.
    pause
)

exit /b %RC%
