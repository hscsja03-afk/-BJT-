param([string]$Port='COM9',[string]$ToolRoot='D:\FPGA\Xilix\2026.1',
  [ValidateSet('linux_platform','linux_platform333','linux_platform333_nowl','linux_platform_nanya533')][string]$PsProfile='linux_platform',
  [ValidateSet('custom','custom_jtag','official')][string]$Baseboard='custom')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskOut=Join-Path $taskRoot 'build/work/boot_probe'
$taskManifest=Get-Content -LiteralPath "$taskOut/manifest.json" -Raw | ConvertFrom-Json
foreach($taskItem in @(
  @{Path="$PSScriptRoot/boot_probe.c";Hash=$taskManifest.source_sha256},
  @{Path="$taskOut/boot_probe.elf";Hash=$taskManifest.elf_sha256},
  @{Path="$taskOut/symbols.txt";Hash=$taskManifest.symbols_sha256}
)) {
  if((Get-FileHash -LiteralPath $taskItem.Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskItem.Hash){throw 'Probe source/ELF/symbols changed; rebuild before deployment'}
}
$taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$taskLogPrefix=Join-Path $taskRoot "build/logs/probe_${Baseboard}_${PsProfile}_${taskStamp}"
$taskInit=Join-Path $taskRoot "build/work/$PsProfile/vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl"
if(-not (Test-Path -LiteralPath $taskInit)){throw 'Selected PS initialization file is missing'}
@{
  baseboard=$Baseboard; profile=$PsProfile; source_sha256=$taskManifest.source_sha256
  elf_sha256=$taskManifest.elf_sha256; symbols_sha256=$taskManifest.symbols_sha256
  ps_init_sha256=(Get-FileHash -LiteralPath $taskInit -Algorithm SHA256).Hash.ToLowerInvariant()
  storage_content_written=$false; pl_downloaded=$false
} | ConvertTo-Json | Set-Content -LiteralPath "${taskLogPrefix}_inputs.json"
$taskSerial=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
$taskSerial.DtrEnable=$false
$taskSerial.RtsEnable=$false
try {
  $taskSerial.Open()
  & "$ToolRoot/Vitis/bin/xsdb.bat" "$PSScriptRoot/run_boot_probe.tcl" $PsProfile $Baseboard 2>&1 | Tee-Object -FilePath "${taskLogPrefix}_jtag.log"
  if($LASTEXITCODE -ne 0){throw 'Boot probe JTAG operation failed; inspect logs before retrying'}
  $taskText=$taskSerial.ReadExisting()
  $taskText | Set-Content -LiteralPath "${taskLogPrefix}_uart.txt"
  $taskText
} finally {
  if($taskSerial.IsOpen){$taskSerial.Close()}
  $taskSerial.Dispose()
}
