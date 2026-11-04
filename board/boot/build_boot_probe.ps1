param([string]$ToolRoot='D:\FPGA\Xilix\2026.1')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$taskBsp=Join-Path $taskRoot 'build/work/boot_software/core_2v5/ps7_cortexa9_0/diagnostic/bsp'
$taskGcc=Join-Path $ToolRoot 'gnu/aarch32/nt/gcc-arm-none-eabi/bin'
$taskOut=Join-Path $taskRoot 'build/work/boot_probe'
New-Item -ItemType Directory -Force -Path $taskOut | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../config/ocm.ld') -Destination (Join-Path $taskOut 'ocm.ld')
& "$taskGcc/arm-none-eabi-gcc.exe" -DSDT -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -O2 -g -Wall -Wextra -Werror -std=c11 `
  "-I$taskBsp/include" "-L$taskBsp/lib" "-specs=$taskBsp/Xilinx.spec" `
  "-Wl,-T,$taskOut/ocm.ld" "-Wl,-Map,$taskOut/boot_probe.map" `
  '-Wl,--wrap=XSdPs_EmmcModeInit,--wrap=XSdPs_MmcModeInit,--wrap=XSdPs_Set_Mmc_ExtCsd' `
  "$PSScriptRoot/boot_probe.c" '-Wl,--start-group' -lxiltimer -lxil -lxilstandalone -lgcc -lc '-Wl,--end-group' -o "$taskOut/boot_probe.elf"
if($LASTEXITCODE -ne 0){throw 'Boot probe compile/link failed'}
& "$taskGcc/arm-none-eabi-size.exe" "$taskOut/boot_probe.elf"
& "$taskGcc/arm-none-eabi-nm.exe" -n "$taskOut/boot_probe.elf" | Set-Content -LiteralPath "$taskOut/symbols.txt"
if($LASTEXITCODE -ne 0){throw 'ELF symbols inspection failed'}
$taskManifest=@{
  source_sha256=(Get-FileHash -LiteralPath "$PSScriptRoot/boot_probe.c" -Algorithm SHA256).Hash.ToLowerInvariant()
  elf_sha256=(Get-FileHash -LiteralPath "$taskOut/boot_probe.elf" -Algorithm SHA256).Hash.ToLowerInvariant()
  symbols_sha256=(Get-FileHash -LiteralPath "$taskOut/symbols.txt" -Algorithm SHA256).Hash.ToLowerInvariant()
  storage_content_writes=$false
  permanent_emmc_switches_blocked=$true
}
$taskManifest | ConvertTo-Json | Set-Content -LiteralPath "$taskOut/manifest.json"
