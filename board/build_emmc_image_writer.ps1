param([string]$ToolRoot='D:\FPGA\Xilix\2026.1')
$ErrorActionPreference='Stop'
$taskRoot=Split-Path $PSScriptRoot -Parent
$taskBsp=Join-Path $taskRoot 'build/work/boot_software/core_2v5/ps7_cortexa9_0/diagnostic/bsp'
$taskGcc=Join-Path $ToolRoot 'gnu/aarch32/nt/gcc-arm-none-eabi/bin'
$taskOut=Join-Path $taskRoot 'build/work/emmc_writer'
New-Item -ItemType Directory -Force -Path $taskOut | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ocm.ld') -Destination (Join-Path $taskOut 'ocm.ld')
& "$taskGcc/arm-none-eabi-gcc.exe" -DSDT -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -O2 -g -Wall -Wextra -Werror -std=c11 `
  "-I$taskBsp/include" "-L$taskBsp/lib" "-specs=$taskBsp/Xilinx.spec" `
  "-Wl,-T,$taskOut/ocm.ld" "-Wl,-Map,$taskOut/emmc_image_writer.map" `
  '-Wl,--wrap=XSdPs_EmmcModeInit,--wrap=XSdPs_MmcModeInit,--wrap=XSdPs_Set_Mmc_ExtCsd' `
  "$PSScriptRoot/emmc_image_writer.c" '-Wl,--start-group' -lxiltimer -lxil -lxilstandalone -lgcc -lc '-Wl,--end-group' `
  -o "$taskOut/emmc_image_writer.elf"
if($LASTEXITCODE -ne 0){throw 'eMMC writer compile/link failed'}
& "$taskGcc/arm-none-eabi-size.exe" "$taskOut/emmc_image_writer.elf"
& "$taskGcc/arm-none-eabi-nm.exe" -n "$taskOut/emmc_image_writer.elf" | Set-Content -LiteralPath "$taskOut/symbols.txt"
if($LASTEXITCODE -ne 0){throw 'eMMC writer symbol inspection failed'}
$taskManifest=@{
  source_sha256=(Get-FileHash -LiteralPath "$PSScriptRoot/emmc_image_writer.c" -Algorithm SHA256).Hash.ToLowerInvariant()
  elf_sha256=(Get-FileHash -LiteralPath "$taskOut/emmc_image_writer.elf" -Algorithm SHA256).Hash.ToLowerInvariant()
  symbols_sha256=(Get-FileHash -LiteralPath "$taskOut/symbols.txt" -Algorithm SHA256).Hash.ToLowerInvariant()
  image_sha256='d762165b6a0fb2f7bcf2132ebb46c765bfa9f0069fed4c93ced69ac2e7722fdc'
  image_bytes=7653556224
  image_sectors=14948352
  target_emmc_cid='4dbea069 39381114 35384133 00d60103'
  storage_write_capability=$true
  permanent_extcsd_writes_blocked=$true
  per_transfer_readback=$true
}
$taskManifest | ConvertTo-Json | Set-Content -LiteralPath "$taskOut/manifest.json"
