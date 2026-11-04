param([Parameter(Mandatory=$true)][string]$Vivado)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskOutput = Join-Path $taskRoot 'build/work/rebuild_adc625'
$taskLogs = Join-Path $taskRoot 'build/logs'
New-Item -ItemType Directory -Force -Path $taskLogs | Out-Null
Push-Location $taskRoot
try {
  & $Vivado -mode batch -nojournal -log (Join-Path $taskLogs 'rebuild_adc625.log') -source (Join-Path $taskRoot 'build/create_overlay.tcl') -tclargs pynq_adc50_dac125 (Join-Path $taskRoot 'board/ps_pynq_custom.tcl') $taskOutput 16
  if ($LASTEXITCODE -ne 0) { throw 'Vivado build failed; inspect build/logs/rebuild_adc625.log' }
} finally { Pop-Location }
