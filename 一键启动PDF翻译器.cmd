@echo off
setlocal
cd /d "%~dp0"
title PDF Translation Watcher

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python environment not found.
    echo Run scripts\setup.ps1 first, then try again.
    pause
    exit /b 1
)

if not exist "config.toml" (
    echo [ERROR] config.toml not found next to this launcher.
    pause
    exit /b 1
)

echo PDF translation watcher is starting...
echo Keep this window open and add PDF files to: %CD%\source
echo Progress appears here. Press Ctrl+C to stop watching.
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_watcher.ps1"
set "PDF_TRANSLATOR_EXIT=%ERRORLEVEL%"
if not "%PDF_TRANSLATOR_EXIT%"=="0" (
    echo.
    echo [ERROR] The watcher exited with code %PDF_TRANSLATOR_EXIT%.
    pause
)
exit /b %PDF_TRANSLATOR_EXIT%
