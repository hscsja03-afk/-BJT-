param([string]$Xsdb='D:\FPGA\Xilix\2026.1\Vitis\bin\xsdb.bat')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$taskOut=Join-Path $taskRoot 'build/work/pynq_custom50'
$taskBit=Join-Path $taskOut 'bjt.bit'
$taskHwh=Join-Path $taskOut 'bjt.hwh'
if(!(Test-Path -LiteralPath $taskBit) -or !(Test-Path -LiteralPath $taskHwh)){
  throw 'Matching PYNQ custom50 bit/HWH files are required'
}
$taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$taskLog=Join-Path $taskRoot "build/logs/pynq_custom50_jtag_$taskStamp.log"
$taskArgs=@((Join-Path $PSScriptRoot 'verify_pynq_custom50.tcl'),$taskBit)
& $Xsdb @taskArgs 2>&1 | Tee-Object -FilePath $taskLog
if($LASTEXITCODE -ne 0 -or (Get-Content -LiteralPath $taskLog -Raw) -notmatch 'PYNQ_CUSTOM50_PL_PASS'){
  throw "JTAG PL verification failed; see $taskLog"
}
$taskEvidence=@{
  tested_at=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')
  profile='pynq_custom50'
  vivado='2026.1'
  bit_sha256=(Get-FileHash -LiteralPath $taskBit -Algorithm SHA256).Hash.ToLowerInvariant()
  hwh_sha256=(Get-FileHash -LiteralPath $taskHwh -Algorithm SHA256).Hash.ToLowerInvariant()
  board_test='JTAG PL download and AXI identity/50 MHz divider readback'
  analog_output_enable_commands=0
  storage_written=$false
  log=(Resolve-Path -LiteralPath $taskLog).Path
  limit='No ADC capture, TFT visual inspection, Linux/PYNQ boot or analog fixture test'
}
$taskReport=Join-Path $taskRoot "report/pynq_custom50_jtag_$taskStamp.json"
$taskEvidence | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskReport -Encoding utf8
Write-Output "PYNQ_CUSTOM50_EVIDENCE=$taskReport"
