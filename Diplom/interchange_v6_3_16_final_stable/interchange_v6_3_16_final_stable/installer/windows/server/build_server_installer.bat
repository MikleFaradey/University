@echo off
call "%~dp0..\build_role_installer.bat" server
exit /b %errorlevel%
