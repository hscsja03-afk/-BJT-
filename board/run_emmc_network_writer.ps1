param(
  [string]$ToolRoot='D:\FPGA\Xilix\2026.1',
  [switch]$ConfirmOverwrite
)
$ErrorActionPreference='Stop'
if(-not $ConfirmOverwrite){throw 'Use -ConfirmOverwrite after the user has authorized replacing eMMC contents'}
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskOut=Join-Path $taskRoot 'build/work/emmc_network_writer'
$taskImage='D:\FPGA\WSL\PYNQ-work\ZYNQ-7020-2.7.0-emmc-fit.img'
$taskManifest=Get-Content -LiteralPath (Join-Path $taskOut 'manifest.json') -Raw | ConvertFrom-Json
$taskExpectedSources=@{
  'emmc_image_writer.c'=(Join-Path $PSScriptRoot 'emmc_image_writer.c')
  'ethernet.c'=(Join-Path $taskRoot 'reference/embedded/sw/ethernet.c')
  'net_packet.c'=(Join-Path $taskRoot 'reference/embedded/sw/net_packet.c')
}
foreach($taskName in $taskExpectedSources.Keys){
  if((Get-FileHash -LiteralPath $taskExpectedSources[$taskName] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.source_sha256.$taskName){
    throw "Network writer source changed after build: $taskName"
  }
}
if((Get-FileHash -LiteralPath (Join-Path $taskOut 'emmc_network_writer.elf') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.elf_sha256){throw 'Network writer ELF changed after build'}
if((Get-FileHash -LiteralPath (Join-Path $taskOut 'symbols.txt') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.symbols_sha256){throw 'Network writer symbols changed after build'}
$taskImageInfo=Get-Item -LiteralPath $taskImage
if($taskImageInfo.Length -ne [long]$taskManifest.image_bytes){throw 'Candidate image size changed; refusing eMMC deployment'}
if((Get-FileHash -LiteralPath $taskImage -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.image_sha256){throw 'Candidate image hash changed; refusing eMMC deployment'}
$taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$taskLog=Join-Path $taskRoot "build/logs/emmc_network_writer_$taskStamp.log"
"mode=network_write image_bytes=$($taskManifest.image_bytes) image_sha256=$($taskManifest.image_sha256) target_cid=$($taskManifest.target_emmc_cid) board_ip=$($taskManifest.network_board_ip)" | Set-Content -LiteralPath "$taskLog.inputs.txt"
& "$ToolRoot/Vitis/bin/xsdb.bat" "$PSScriptRoot/run_emmc_network_writer.tcl" 2>&1 | Tee-Object -FilePath $taskLog
if($LASTEXITCODE -ne 0){throw "Network writer XSDB failed; inspect $taskLog"}
$taskLogText=Get-Content -LiteralPath $taskLog -Raw
if($taskLogText -notmatch 'EMMC_IMAGE_WRITE_COMPLETE'){throw "Network writer did not report completion; inspect $taskLog"}
$taskLog
