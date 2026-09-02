[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VirtualEnv = Join-Path $ProjectRoot ".venv"
$Python = Join-Path $VirtualEnv "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    py -3 -m venv $VirtualEnv
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -e "$ProjectRoot[dev]"

$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot ".env.example") -Destination $EnvFile
    Write-Host "Created $EnvFile. Add your API key before starting the watcher." -ForegroundColor Yellow
}

& $Python -m pdf_translation_workflow --config (Join-Path $ProjectRoot "config.toml") doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Setup finished, but configuration is incomplete. Add the API key and run doctor again."
}
exit 0
