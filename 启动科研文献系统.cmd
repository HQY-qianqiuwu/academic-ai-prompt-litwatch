@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-stack.ps1"
exit /b %ERRORLEVEL%
