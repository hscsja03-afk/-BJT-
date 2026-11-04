param([Parameter(Mandatory=$true)][ValidateSet('original','custom')][string]$Board)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskOut=Join-Path $taskRoot 'build/work/baremetal'
$taskManifest=Get-Content -LiteralPath "$taskOut/manifest.json" -Raw | ConvertFrom-Json
foreach($taskProperty in $taskManifest.inputs.PSObject.Properties){
  if((Get-FileHash -LiteralPath (Join-Path $taskRoot $taskProperty.Name)).Hash.ToLowerInvariant() -ne $taskProperty.Value){throw 'Firmware source changed; rebuild first'}
}
$taskInit=Join-Path $taskRoot 'build/work/baseline50/vivado/bjt.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl'
if((Get-FileHash -LiteralPath $taskInit).Hash.ToLowerInvariant() -ne $taskManifest.ps_init_sha256){throw 'PS initializer changed'}
$taskMode=if($Board -eq 'custom'){'adda'}else{'probe'}
if((Get-FileHash -LiteralPath "$taskOut/$taskMode.elf").Hash.ToLowerInvariant() -ne $taskManifest.images.$taskMode.sha256){throw 'ELF changed'}
if((Get-FileHash -LiteralPath "$taskOut/${taskMode}_symbols.txt").Hash.ToLowerInvariant() -ne $taskManifest.images.$taskMode.symbols_sha256){throw 'Symbols changed'}
$taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$taskPrefix=Join-Path $taskRoot "build/logs/baremetal_${Board}_${taskStamp}"
$taskEvidence=@{board=$Board;firmware=$taskManifest;mode=$taskMode;storage_written=$false
  run_tcl_sha256=(Get-FileHash -LiteralPath "$PSScriptRoot/run.tcl").Hash.ToLowerInvariant()}
if($Board -eq 'custom'){
  foreach($taskSuffix in @('bit','hwh')){
    $taskEvidence["${taskSuffix}_sha256"]=(Get-FileHash -LiteralPath "$taskRoot/build/work/baseline50/bjt.$taskSuffix").Hash.ToLowerInvariant()
  }
}
$taskEvidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath "${taskPrefix}_inputs.json"
& 'D:/FPGA/Xilix/2026.1/Vitis/bin/xsdb.bat' "$PSScriptRoot/run.tcl" $Board 2>&1 | Tee-Object -FilePath "${taskPrefix}.log"
if($LASTEXITCODE -ne 0 -or (Get-Content -LiteralPath "${taskPrefix}.log" -Raw) -notmatch "BAREMETAL_READY board=$Board ddr_initialized=0 analog_initialized=0"){throw 'Baremetal startup did not complete'}
python "$PSScriptRoot/verify_run.py" "${taskPrefix}.log"
if($LASTEXITCODE -ne 0){throw 'Baremetal evidence verification failed'}
