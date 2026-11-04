param([string]$Vivado='', [string]$Python='')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskPython=if ($Python) { $Python } else { Join-Path $taskRoot '.venv/Scripts/python.exe' }
$env:PYTHONPATH=Join-Path $taskRoot 'src/python'
Push-Location $taskRoot
try {
 & $taskPython -X utf8 -m unittest discover -s sim/python -p 'test_*.py' -v
 if ($LASTEXITCODE -ne 0) { throw 'Software regression failed' }
 & $taskPython -X utf8 -m unittest discover -s src/python/tests -p 'test_*.py' -v
 if ($LASTEXITCODE -ne 0) { throw 'Analysis regression failed' }
 if ($Vivado) {
  New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'logs') | Out-Null
  foreach ($taskName in @('axi','adc_depth','lcd_ddr')) {
   & $Vivado -mode batch -nojournal -log (Join-Path $PSScriptRoot "logs/sim_$taskName.log") -source (Join-Path $taskRoot "sim/rtl/run_$taskName.tcl")
   if ($LASTEXITCODE -ne 0) { throw "RTL regression failed: $taskName" }
  }
 }
} finally { Pop-Location }
