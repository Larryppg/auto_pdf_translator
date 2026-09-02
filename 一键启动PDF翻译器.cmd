@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title PDF 自动翻译与归档

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 尚未完成环境安装，请先运行 scripts\setup.ps1。
    pause
    exit /b 1
)

echo PDF 自动翻译与归档正在启动……
echo 请保持此窗口开启，然后把 PDF 放入：%CD%\source
echo 翻译进度会显示在本窗口，按 Ctrl+C 可停止监听。
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_watcher.ps1"
set "PDF_TRANSLATOR_EXIT=%ERRORLEVEL%"
if not "%PDF_TRANSLATOR_EXIT%"=="0" (
    echo.
    echo [错误] 翻译器退出，错误码：%PDF_TRANSLATOR_EXIT%
    pause
)
exit /b %PDF_TRANSLATOR_EXIT%
