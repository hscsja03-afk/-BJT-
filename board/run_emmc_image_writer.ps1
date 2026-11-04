param(
  [string]$ToolRoot='D:\FPGA\Xilix\2026.1',
  [ValidateSet('dry_run','write')][string]$Mode='dry_run',
  [switch]$ConfirmOverwrite
)
$ErrorActionPreference='Stop'
if($Mode -eq 'write' -and -not $ConfirmOverwrite){throw 'Use -ConfirmOverwrite after the user has authorized replacing eMMC contents'}
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskOut=Join-Path $taskRoot 'build/work/emmc_writer'
$taskImage='D:\FPGA\WSL\PYNQ-work\ZYNQ-7020-2.7.0-emmc-fit.img'
$taskManifest=Get-Content -LiteralPath "$taskOut/manifest.json" -Raw | ConvertFrom-Json
if((Get-FileHash -LiteralPath "$PSScriptRoot/emmc_image_writer.c" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.source_sha256){throw 'Writer source changed; rebuild before deployment'}
if((Get-FileHash -LiteralPath "$taskOut/emmc_image_writer.elf" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.elf_sha256){throw 'Writer ELF changed; rebuild before deployment'}
if((Get-FileHash -LiteralPath "$taskOut/symbols.txt" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.symbols_sha256){throw 'Writer symbols changed; rebuild before deployment'}
$taskInfo=Get-Item -LiteralPath $taskImage
if($taskInfo.Length -ne [long]$taskManifest.image_bytes){throw 'Candidate image size changed; refusing eMMC deployment'}
$taskHash=(Get-FileHash -LiteralPath $taskImage -Algorithm SHA256).Hash.ToLowerInvariant()
if($taskHash -ne $taskManifest.image_sha256){throw 'Candidate image hash changed; refusing eMMC deployment'}
$taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$taskLog=Join-Path $taskRoot "build/logs/emmc_image_${Mode}_${taskStamp}.log"
$taskDryRun=if($Mode -eq 'dry_run'){'1'}else{'0'}
"mode=$Mode image_bytes=$($taskInfo.Length) image_sha256=$taskHash target_cid=$($taskManifest.target_emmc_cid)" | Set-Content -LiteralPath "${taskLog}.inputs.txt"
& "$ToolRoot/Vitis/bin/xsdb.bat" "$PSScriptRoot/run_emmc_image_writer.tcl" $taskImage $taskDryRun 2>&1 | Tee-Object -FilePath $taskLog
if($LASTEXITCODE -ne 0){throw "eMMC writer XSDB failed; inspect $taskLog"}
$taskLogText=Get-Content -LiteralPath $taskLog -Raw
$taskExpectedMarker=if($Mode -eq 'dry_run'){'EMMC_DRY_RUN_PASS'}else{'EMMC_IMAGE_WRITE_COMPLETE'}
if($taskLogText -notmatch [regex]::Escape($taskExpectedMarker)){throw "XSDB did not report $taskExpectedMarker; inspect $taskLog"}
$taskLog
