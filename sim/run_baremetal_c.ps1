param([string]$Gcc='gcc')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskOut=Join-Path $taskRoot 'build/work/baremetal'
New-Item -ItemType Directory -Force -Path $taskOut | Out-Null
$taskExe=Join-Path $taskRoot 'build/work/baremetal/host_faults.exe'
& $Gcc -std=c11 -O2 -Wall -Wextra -Werror -static "-I$taskRoot/src/baremetal" "$taskRoot/src/baremetal/adda.c" "$PSScriptRoot/baremetal_faults.c" -o $taskExe
if($LASTEXITCODE -ne 0){throw 'Host C-driver fault harness build failed'}
foreach($taskCase in @('identity','rate','gpio','dac','clock_timeout','adc_id','adc_pattern','adc_timeout')){
  & $taskExe $taskCase
  if($LASTEXITCODE -ne 0){throw "C-driver fault case failed: $taskCase"}
}
& $Gcc -std=c11 -O2 -Wall -Wextra -Werror -static "-I$taskRoot/src/baremetal" "$PSScriptRoot/baremetal_timebase.c" -o "$taskRoot/build/work/baremetal/host_timebase.exe"
if($LASTEXITCODE -ne 0){throw 'Host timebase test build failed'}
& "$taskRoot/build/work/baremetal/host_timebase.exe"
if($LASTEXITCODE -ne 0){throw 'Timebase regression failed'}
