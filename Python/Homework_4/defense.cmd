@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:menu
cls
echo ==================================================
echo   HOMEWORK 4 - DEFENSE MENU
echo ==================================================
echo   1 - Check environment
echo   2 - Build and start Docker
echo   3 - Automatic bank demo
echo   4 - Interactive bank client
echo   5 - Run security tests
echo   6 - Run Semgrep scan
echo   7 - Show and save Docker logs
echo   8 - Stop Docker container
echo   0 - Exit
echo.
set "stage="
set "script="
set /p "stage=Choose stage [0-8]: "
if "%stage%"=="0" goto finish
if "%stage%"=="1" set "script=01-check.ps1"
if "%stage%"=="2" set "script=02-start.ps1"
if "%stage%"=="3" set "script=03-demo.ps1"
if "%stage%"=="4" set "script=04-client.ps1"
if "%stage%"=="5" set "script=05-tests.ps1"
if "%stage%"=="6" set "script=06-semgrep.ps1"
if "%stage%"=="7" set "script=07-logs.ps1"
if "%stage%"=="8" set "script=08-stop.ps1"

if not defined script (
    echo Unknown stage.
    pause
    goto menu
)

echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0defense\%script%"
if errorlevel 1 echo [ERROR] Stage failed. Read the message above.
echo.
pause
goto menu

:finish
endlocal
exit /b 0
