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
    pause
    exit /b 1
)

%PYTHON_CMD% -m pip install --upgrade pip
if errorlevel 1 exit /b 1

%PYTHON_CMD% -m pip install pyinstaller requests PySide6
if errorlevel 1 exit /b 1

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist output rmdir /s /q output

%PYTHON_CMD% -m PyInstaller --clean --noconfirm InterchangeClient.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

rem Validate the actual frozen executable, including packaged UI resources.
"%CD%\dist\Interchange\Interchange.exe" --self-test
if errorlevel 1 (
    echo ERROR: Frozen client self-test failed.
    echo The build is missing a runtime dependency or UI resource.
    pause
    exit /b 1
)

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
)

if not defined ISCC (
    echo ERROR: Inno Setup 6 was not found.
    echo Install Inno Setup 6 and run this script again.
    pause
    exit /b 1
)

"%ISCC%" InterchangeClient.iss
if errorlevel 1 (
    echo ERROR: Inno Setup build failed.
    pause
    exit /b 1
)

echo.
echo READY:
echo %CD%\output\InterchangeClientSetup.exe
echo.
pause
