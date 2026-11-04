param([string]$ToolRoot='D:/FPGA/Xilix/2026.1')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$taskBsp=Join-Path $taskRoot 'build/work/baremetal/software/ocm_platform/ps7_cortexa9_0/baremetal/bsp'
$taskGcc=Join-Path $ToolRoot 'gnu/aarch32/nt/gcc-arm-none-eabi/bin'
$taskOut=Join-Path $taskRoot 'build/work/baremetal'
$taskBuildInputs=@("$taskRoot/src/baremetal/main.c","$taskRoot/src/baremetal/adda.c","$taskRoot/src/baremetal/adda.h","$taskRoot/src/baremetal/timebase.h","$taskBsp/include/xparameters.h","$taskRoot/board/config/ocm.ld",$PSCommandPath)
$taskHashText=($taskBuildInputs | ForEach-Object {(Get-FileHash -LiteralPath $_).Hash.ToLowerInvariant()}) -join ''
$taskSha=[System.Security.Cryptography.SHA256]::Create()
try {$taskIdentity=([BitConverter]::ToString($taskSha.ComputeHash([Text.Encoding]::ASCII.GetBytes($taskHashText)))).Replace('-','').ToLowerInvariant()} finally {$taskSha.Dispose()}
$taskBuildId=$taskIdentity.Substring(0,8)
$taskBuildId | Set-Content -LiteralPath "$taskOut/build_id.txt"
foreach($taskMode in @('probe','adda')) {
  $taskEnabled=if($taskMode -eq 'adda'){1}else{0}
  & "$taskGcc/arm-none-eabi-gcc.exe" -DSDT "-DADDA_ENABLED=$taskEnabled" "-DBJT_BUILD_ID=0x${taskBuildId}U" -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -Os -g -Wall -Wextra -Werror -std=c11 -ffunction-sections -fdata-sections `
    "-I$taskBsp/include" "-I$taskRoot/src/baremetal" "-L$taskBsp/lib" "-specs=$taskBsp/Xilinx.spec" `
    '-Wl,--gc-sections,--defsym=_HEAP_SIZE=0,--defsym=_STACK_SIZE=0x3000' "-Wl,-T,$taskRoot/board/config/ocm.ld" "-Wl,-Map,$taskOut/$taskMode.map" `
    "$taskRoot/src/baremetal/main.c" "$taskRoot/src/baremetal/adda.c" '-Wl,--start-group' -lxiltimer -lxil -lxilstandalone -lgcc -lc '-Wl,--end-group' -o "$taskOut/$taskMode.elf"
  if($LASTEXITCODE -ne 0){throw "Baremetal $taskMode compile/link failed"}
  & "$taskGcc/arm-none-eabi-nm.exe" -n "$taskOut/$taskMode.elf" | Set-Content -LiteralPath "$taskOut/${taskMode}_symbols.txt"
  if($LASTEXITCODE -ne 0){throw 'ELF symbol inspection failed'}
  & "$taskGcc/arm-none-eabi-size.exe" "$taskOut/$taskMode.elf"
}
python "$PSScriptRoot/audit.py"
if($LASTEXITCODE -ne 0){throw 'OCM image audit failed'}
