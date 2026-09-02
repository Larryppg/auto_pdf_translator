[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\setup.ps1 first."
}

Set-Location -LiteralPath $ProjectRoot
& $Python -m pdf_translation_workflow --config (Join-Path $ProjectRoot "config.toml") watch
exit $LASTEXITCODE
