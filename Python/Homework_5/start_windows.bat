@echo off
chcp 65001 >nul
py -m pip install -e .
if errorlevel 1 pause & exit /b 1
py -m host.main
pause
