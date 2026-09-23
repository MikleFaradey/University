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

%PYTHON_CMD% -m pip install --upgrade pip
if errorlevel 1 exit /b 1

%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

%PYTHON_CMD% -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    %PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 and sys.version_info.minor == 7 else 1)"
    if not errorlevel 1 (
        echo Installing Python 3.7 compatible PySide6 6.5.3...
        %PYTHON_CMD% -m pip install PySide6==6.5.3
    ) else (
        echo Installing PySide6...
        %PYTHON_CMD% -m pip install PySide6
    )
    if errorlevel 1 exit /b 1
)

echo.
echo Dependencies installed.
pause
