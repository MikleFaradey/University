@echo off
setlocal EnableExtensions
set "ROLE=%~1"
if /i "%ROLE%"=="server" (
  set "APP=InterchangeServer"
) else if /i "%ROLE%"=="admin" (
  set "APP=InterchangeAdmin"
) else (
  echo Usage: build_role_installer.bat server^|admin
  exit /b 2
)
set "ROOT=%~dp0"
set "PROJECT=%ROOT%..\.."
cd /d "%ROOT%%ROLE%"
py -3 --version >nul 2>nul
if not errorlevel 1 (
  py -3 -m venv .venv-build
) else (
  python -m venv .venv-build
)
if errorlevel 1 exit /b 1
set "PY=.venv-build\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip pyinstaller PySide6
if errorlevel 1 exit /b 1
if /i "%ROLE%"=="server" (
  "%PY%" -m pip install -r "%PROJECT%\server\requirements.txt"
) else (
  "%PY%" -m pip install requests
)
if errorlevel 1 exit /b 1
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist output rmdir /s /q output
"%PY%" -m PyInstaller --clean --noconfirm "%APP%.spec"
if errorlevel 1 exit /b 1
start "" /wait "dist\%APP%\%APP%.exe" --self-test
if errorlevel 1 (
  echo ERROR: Frozen executable self-test failed.
  exit /b 1
)
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
if not defined ISCC (
  echo ERROR: Inno Setup 6 required. Install it then retry.
  exit /b 1
)
"%ISCC%" "%APP%.iss"
if errorlevel 1 exit /b 1
echo READY: %CD%\output\%APP%Setup.exe
