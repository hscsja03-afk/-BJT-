param([switch]$Run)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskTool='D:/FPGA/Xilix/2026.1/Vitis/bin/xsdb.bat'
$taskFolder=Join-Path $taskRoot 'build/work/ddr_lane_probe'
$taskInit=Join-Path $taskRoot 'build/work/linux_platform_nanya533/vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl'
$taskManifest=Get-Content -LiteralPath "$taskFolder/manifest.json" -Raw | ConvertFrom-Json
foreach($taskItem in @(
    @{Path="$PSScriptRoot/ddr_lane_probe.c";Hash=$taskManifest.source_sha256},
    @{Path="$taskFolder/ddr_lane_probe.elf";Hash=$taskManifest.elf_sha256},
    @{Path="$taskFolder/symbols.txt";Hash=$taskManifest.symbols_sha256},
    @{Path=$taskInit;Hash='d8046cd896dce96fa2e7b31f596f07962c4dd702ab4e3f29ef482eb6ece84035'}
)) {
    if((Get-FileHash -LiteralPath $taskItem.Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskItem.Hash){throw 'Input hash mismatch'}
}
$taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$taskPrefix=Join-Path $taskRoot "build/logs/ddr_training_${taskStamp}"
$taskMode=if($Run){'--run'}else{'--validate-only'}
@{
    hardware_requested=[bool]$Run; tool_version='2026.1'; baseboard='official'
    ps_init_sha256=(Get-FileHash -LiteralPath $taskInit -Algorithm SHA256).Hash.ToLowerInvariant()
    tcl_sha256=(Get-FileHash -LiteralPath "$PSScriptRoot/run_ddr_training_probe.tcl" -Algorithm SHA256).Hash.ToLowerInvariant()
    wrapper_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    probe_manifest=$taskManifest; altered_register='0xF800612C'
    cases=@(@(164,0),@(164,64),@(164,128),@(100,0),@(100,64),@(100,128),@(228,0),@(228,64),@(228,128))
    restore_baseline=@(164,0); storage_access=$false; pl_download=$false
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "${taskPrefix}_inputs.json"
& $taskTool "$PSScriptRoot/run_ddr_training_probe.tcl" $taskMode 2>&1 | Tee-Object -FilePath "${taskPrefix}.log"
$taskExit=$LASTEXITCODE
$taskText=Get-Content -LiteralPath "${taskPrefix}.log" -Raw
if(-not $Run){
    if($taskExit -ne 0 -or $taskText -notmatch 'TRAINING_VALIDATION_DONE cases=9 hardware_connected=0'){throw 'Offline validation did not complete'}
    Write-Output 'Offline validation passed; no hardware connection.'
    return
}
$taskRows=@([regex]::Matches($taskText,'TRAINING_CASE_RESULT id=(\w+) values=([^\r\n]+)') | ForEach-Object {
    $taskValues=@($_.Groups[2].Value.Trim() -split '\s+' | ForEach-Object {[uint32]$_})
    if($taskValues.Count -ne 69 -or $taskValues[0] -ne 0x44445231 -or $taskValues[2] -ne 1){throw 'Malformed result'}
    $taskErrors=($taskValues[3..10] | Measure-Object -Sum).Sum
    [pscustomobject]@{id=$_.Groups[1].Value; mismatches=$taskErrors; comparisons=65536
        ddr_passed=($taskErrors -eq 0); pattern_errors=$taskValues[3..10]
        byte_errors_low_to_high=$taskValues[11..14]; xor_mask=('{0:X8}' -f $taskValues[15])}
})
$taskComplete=($taskExit -eq 0 -and $taskText -match 'TRAINING_EXPERIMENT_DONE cases=9 restored=1' -and $taskRows.Count -eq 10)
@{complete=$taskComplete; rows=$taskRows; baseline_restored=($taskText -match 'TRAINING_BASELINE_RESTORED')
    limit='Only nine lane0 initialization starting points; not a full margin scan or board qualification.'
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "${taskPrefix}_result.json"
$taskRows | Format-Table id,mismatches,ddr_passed,xor_mask
if(-not $taskComplete){throw 'Experiment incomplete; see log and partial result'}
