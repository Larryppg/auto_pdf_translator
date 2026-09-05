@echo off
setlocal
cd /d "%~dp0"
title PDF Translator GUI Launcher

set "PDF_GUI_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
set "PDF_GUI_CONFIG=%~dp0config.toml"

if not exist "%PDF_GUI_PYTHON%" (
    echo [ERROR] Python environment not found.
    echo Run scripts\setup.ps1 first, then try again.
    pause
    exit /b 1
)

if not exist "%PDF_GUI_CONFIG%" (
    echo [ERROR] config.toml not found next to this launcher.
    pause
    exit /b 1
)

start "" /D "%~dp0" "%PDF_GUI_PYTHON%" -m pdf_translation_workflow.gui --config "%PDF_GUI_CONFIG%"
if errorlevel 1 (
    echo [ERROR] Windows could not launch the PDF Translator GUI.
    echo Check .state\gui-startup.log for details.
    pause
    exit /b 1
)
exit /b 0
