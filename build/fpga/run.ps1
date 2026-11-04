param(
  [ValidateSet('baseline50','pynq_custom50','pynq_adc50_dac125','target125_250')][string]$Profile='baseline50',
  [string]$Vivado='D:\FPGA\Xilix\2026.1\Vivado\bin\vivado.bat',
  [string]$PsPreset=''
)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$taskLog=Join-Path $PSScriptRoot '../logs'
New-Item -ItemType Directory -Force -Path $taskLog | Out-Null
$taskArgs=@('-mode','batch','-nojournal','-log',(Join-Path $taskLog "$Profile.log"),'-source',(Join-Path $PSScriptRoot 'create_overlay.tcl'),'-tclargs',$Profile)
if($PsPreset){$taskArgs += (Resolve-Path -LiteralPath $PsPreset).Path}
Push-Location $taskRoot
try { & $Vivado @taskArgs; if($LASTEXITCODE -ne 0){throw "Vivado failed; see build/logs/$Profile.log"} }
finally { Pop-Location }
