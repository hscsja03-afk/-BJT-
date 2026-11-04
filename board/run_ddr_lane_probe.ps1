param(
  [ValidateSet('2026.1','2020.2')][string]$Version='2026.1',
  [ValidateSet('default','nanya533')][string]$PsProfile='default'
)
# Call only after the user has confirmed original baseboard, JTAG boot and power.
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
if($Version -eq '2020.2' -and $PsProfile -ne 'default'){throw 'Nanya profile is generated with 2026.1 only'}
if($Version -eq '2020.2') {
  $taskTool='D:/FPGA/B/new/Vivado/Vivado2020_2/Vitis/2020.2'
  $taskFolder='ddr_lane_probe2020'; $taskProfile='linux_platform2020'
} else {
  $taskTool='D:/FPGA/Xilix/2026.1/Vitis'
  $taskFolder='ddr_lane_probe'; $taskProfile='linux_platform'
}
if($PsProfile -eq 'nanya533'){$taskProfile='linux_platform_nanya533'}
$taskOut=Join-Path $taskRoot "build/work/$taskFolder"
$taskManifest=Get-Content -LiteralPath "$taskOut/manifest.json" -Raw | ConvertFrom-Json
foreach($taskItem in @(
  @{Path="$PSScriptRoot/ddr_lane_probe.c";Hash=$taskManifest.source_sha256},
  @{Path="$taskOut/ddr_lane_probe.elf";Hash=$taskManifest.elf_sha256},
  @{Path="$taskOut/symbols.txt";Hash=$taskManifest.symbols_sha256}
)) {
  if((Get-FileHash -LiteralPath $taskItem.Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskItem.Hash){throw 'DDR diagnostic changed; rebuild first'}
}
$taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$taskPrefix=Join-Path $taskRoot "build/logs/ddr_lane_official_${Version}_${taskStamp}"
if($PsProfile -ne 'default'){$taskPrefix=Join-Path $taskRoot "build/logs/ddr_lane_official_${Version}_${PsProfile}_${taskStamp}"}
$taskInit=Join-Path $taskRoot "build/work/$taskProfile/vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl"
@{
  tool_version=$Version; ps_profile=$taskProfile; build_manifest=$taskManifest
  ps_init_sha256=(Get-FileHash -LiteralPath $taskInit -Algorithm SHA256).Hash.ToLowerInvariant()
  storage_access=$false; pl_download=$false
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "${taskPrefix}_inputs.json"
& "$taskTool/bin/xsdb.bat" "$PSScriptRoot/run_ddr_lane_probe.tcl" $taskProfile $taskFolder 2>&1 | Tee-Object -FilePath "${taskPrefix}.log"
if($LASTEXITCODE -ne 0){throw 'XSDB execution failed'}
$taskText=Get-Content -LiteralPath "${taskPrefix}.log" -Raw
if($taskText -notmatch 'DDR_LANE_DONE' -or $taskText -notmatch 'DDR_LANE_RESULT=([^\r\n]+)'){throw 'XSDB did not return a complete diagnostic; exit code alone is insufficient'}
$taskValues=@($Matches[1].Trim() -split '\s+' | ForEach-Object {[uint32]$_})
if($taskValues.Count -ne 69 -or $taskValues[0] -ne 0x44445231 -or $taskValues[2] -ne 1){throw 'Invalid DDR diagnostic result structure'}
$taskErrors=($taskValues[3..10] | Measure-Object -Sum).Sum
@{ tool_version=$Version; ps_profile=$taskProfile; complete=$true; ddr_passed=($taskErrors -eq 0)
  mismatches=$taskErrors; read_comparisons=65536
  pattern_errors=$taskValues[3..10]; byte_errors_low_to_high=$taskValues[11..14]
  xor_error_mask=('{0:X8}' -f $taskValues[15])
} | ConvertTo-Json | Set-Content -LiteralPath "${taskPrefix}_result.json"
if($taskErrors){Write-Warning "DDR check completed with $taskErrors mismatches; it did not pass"}
