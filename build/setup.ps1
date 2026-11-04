param([string]$Python='python')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskVenv=Join-Path $taskRoot '.venv'
$taskPython=Join-Path $taskVenv 'Scripts/python.exe'
& $Python -c "import sys; assert sys.version_info[:2]==(3,13), 'Use Python 3.13 x64'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 is required' }
if (!(Test-Path -LiteralPath $taskPython)) {
 & $Python -m venv $taskVenv
 if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'environment/desktop_requirements.lock.txt') -r (Join-Path $PSScriptRoot 'environment/instrument_requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $taskPython -m pip install --no-build-isolation --no-deps -e $taskRoot
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed' }
Write-Output 'Environment ready: .venv'
