@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title PDF 翻译器 GUI 启动入口

set "PDF_GUI_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PDF_GUI_PYTHON%" (
    echo [错误] 尚未完成环境安装，请先运行 scripts\setup.ps1。
    pause
    exit /b 1
)

start "" /D "%~dp0" "%PDF_GUI_PYTHON%" -m pdf_translation_workflow.gui --config "%~dp0config.toml"
if errorlevel 1 (
    echo [错误] GUI 启动失败。
    pause
    exit /b 1
)
exit /b 0
