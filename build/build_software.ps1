$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskPython=Join-Path $taskRoot '.venv/Scripts/python.exe'
Push-Location $taskRoot
try {
 & $taskPython -m pip wheel . --no-deps --no-build-isolation --wheel-dir build/dist/python
 if ($LASTEXITCODE -ne 0) { throw 'Python package build failed' }
 & $taskPython build/software/build_desktop.py
 if ($LASTEXITCODE -ne 0) { throw 'Windows package build failed' }
} finally { Pop-Location }
