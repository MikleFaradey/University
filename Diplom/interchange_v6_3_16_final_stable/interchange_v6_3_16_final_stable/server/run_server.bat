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

echo Python command: %PYTHON_CMD%
echo Server process: normal Windows user
echo.

%PYTHON_CMD% configure_server.py
if errorlevel 1 (
    echo Server setup was cancelled or failed.
    pause
    exit /b 1
)

echo.
echo Starting Interchange Server...
echo If Windows Firewall asks, allow access on Private networks.
echo.

%PYTHON_CMD% server.py --no-gui
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo Server exited with code %RC%.
    pause
)

exit /b %RC%
