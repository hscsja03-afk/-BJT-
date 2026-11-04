$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskBin='D:/FPGA/Xilix/2026.1/Vitis/tps/mingw/10.0.0/win64.o/nt/bin'
$taskExe=Join-Path $taskRoot 'build/work/baremetal/host_faults.exe'
& "$taskBin/gcc.exe" -std=c11 -O2 -Wall -Wextra -Werror -static "-I$taskRoot/src/baremetal" "$taskRoot/src/baremetal/adda.c" "$PSScriptRoot/baremetal_faults.c" -o $taskExe
if($LASTEXITCODE -ne 0){throw 'Host C-driver fault harness build failed'}
foreach($taskCase in @('identity','rate','gpio','dac','clock_timeout','adc_id','adc_pattern','adc_timeout')){
  & $taskExe $taskCase
  if($LASTEXITCODE -ne 0){throw "C-driver fault case failed: $taskCase"}
}
& "$taskBin/gcc.exe" -std=c11 -O2 -Wall -Wextra -Werror -static "-I$taskRoot/src/baremetal" "$PSScriptRoot/baremetal_timebase.c" -o "$taskRoot/build/work/baremetal/host_timebase.exe"
if($LASTEXITCODE -ne 0){throw 'Host timebase test build failed'}
& "$taskRoot/build/work/baremetal/host_timebase.exe"
if($LASTEXITCODE -ne 0){throw 'Timebase regression failed'}
