@echo off
call "%~dp0..\build_role_installer.bat" admin
exit /b %errorlevel%
