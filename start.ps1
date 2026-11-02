param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Please create .venv and install requirements.lock.txt first. See README.md.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    $env:WORK_REPORT_PORT = [string]$Port
    & $pythonPath run.py
}
finally {
    Pop-Location
}
