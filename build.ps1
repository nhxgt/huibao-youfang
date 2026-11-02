param([string]$OutputDirectory = (Join-Path $PSScriptRoot 'dist'))
$ErrorActionPreference = 'Stop'
$buildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    throw 'Create the virtual environment and install requirements.lock.txt first.'
}
& $buildPython -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'Install PyInstaller in .venv first: .\.venv\Scripts\python.exe -m pip install pyinstaller'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $buildPython -m PyInstaller --noconfirm --distpath $OutputDirectory --workpath (Join-Path $PSScriptRoot 'build') (Join-Path $PSScriptRoot 'work-report.spec')
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
    & $buildPython -m release_tools.package --dist $OutputDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Release content validation failed.' }
}
finally { Pop-Location }
