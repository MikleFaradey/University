@echo off
setlocal

taskkill /IM Interchange.exe /F >nul 2>nul

if exist "%USERPROFILE%\.config\interchange" rmdir /s /q "%USERPROFILE%\.config\interchange"
if exist "%USERPROFILE%\.interchange" rmdir /s /q "%USERPROFILE%\.interchange"
if exist "%USERPROFILE%\InterchangeReceived" rmdir /s /q "%USERPROFILE%\InterchangeReceived"
if exist "%USERPROFILE%\InterchangeServerReceived" rmdir /s /q "%USERPROFILE%\InterchangeServerReceived"
if exist "%APPDATA%\Interchange" rmdir /s /q "%APPDATA%\Interchange"
if exist "%LOCALAPPDATA%\Interchange" rmdir /s /q "%LOCALAPPDATA%\Interchange"

echo Interchange local state removed.
pause
