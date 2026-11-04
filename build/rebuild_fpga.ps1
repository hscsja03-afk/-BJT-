param([Parameter(Mandatory=$true)][string]$Vivado)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskOutput=Join-Path $PSScriptRoot 'work/adc625_dac125'
$taskLogs=Join-Path $PSScriptRoot 'logs'
$taskRelease=Join-Path $PSScriptRoot 'dist/overlay'
New-Item -ItemType Directory -Force -Path $taskLogs,$taskRelease | Out-Null
Push-Location $taskRoot
try {
 & $Vivado -mode batch -nojournal -log (Join-Path $taskLogs 'fpga_build.log') -source (Join-Path $PSScriptRoot 'fpga/create_overlay.tcl') -tclargs pynq_adc50_dac125 (Join-Path $taskRoot 'board/config/ps_pynq_custom.tcl') $taskOutput 16
 if ($LASTEXITCODE -ne 0) { throw 'FPGA build failed: build/logs/fpga_build.log' }
 foreach ($taskName in @('bjt.bit','bjt.hwh')) { Copy-Item -LiteralPath (Join-Path $taskOutput $taskName) -Destination (Join-Path $taskRelease $taskName) -Force }
 $taskManifest=@{bit=@{path='bjt.bit';sha256=(Get-FileHash -LiteralPath (Join-Path $taskRelease 'bjt.bit') -Algorithm SHA256).Hash.ToLower()};hwh=@{path='bjt.hwh';sha256=(Get-FileHash -LiteralPath (Join-Path $taskRelease 'bjt.hwh') -Algorithm SHA256).Hash.ToLower()};peripheral=@{instance='adda_core_0';base='0x43c00000';size='0x10000'}}
 [IO.File]::WriteAllText((Join-Path $taskRelease 'manifest.json'),($taskManifest | ConvertTo-Json -Depth 4),(New-Object Text.UTF8Encoding($false)))
 Write-Output 'Overlay ready: build/dist/overlay'
} finally { Pop-Location }
