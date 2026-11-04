param([string]$ToolRoot='D:\FPGA\B\new\Vivado\Vivado2020_2\Vitis\2020.2')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$taskBsp=Join-Path $taskRoot 'build/work/boot_software2020/core_2v5_2020/ps7_cortexa9_0/standalone_domain/bsp/ps7_cortexa9_0'
$taskSpec=Join-Path $taskRoot 'build/work/boot_software2020/core_2v5_2020/zynq_fsbl/Xilinx.spec'
$taskGcc=Join-Path $ToolRoot 'gnu/aarch32/nt/gcc-arm-none-eabi/bin'
$taskOut=Join-Path $taskRoot 'build/work/ddr_lane_probe2020'
New-Item -ItemType Directory -Force -Path $taskOut | Out-Null
Copy-Item -LiteralPath "$PSScriptRoot/../../config/ocm.ld" -Destination "$taskOut/ocm.ld"
& "$taskGcc/arm-none-eabi-gcc.exe" -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -O2 -g -Wall -Wextra -Werror -std=c11 `
  "-I$taskBsp/include" "-L$taskBsp/lib" "-specs=$taskSpec" `
  "-Wl,-T,$taskOut/ocm.ld" "-Wl,-Map,$taskOut/ddr_lane_probe.map" `
  "$PSScriptRoot/ddr_lane_probe.c" '-Wl,--start-group' -lxil -lgcc -lc '-Wl,--end-group' -o "$taskOut/ddr_lane_probe.elf"
if($LASTEXITCODE -ne 0){throw '2020 DDR diagnostic build failed'}
& "$taskGcc/arm-none-eabi-size.exe" "$taskOut/ddr_lane_probe.elf"
& "$taskGcc/arm-none-eabi-nm.exe" -n "$taskOut/ddr_lane_probe.elf" | Set-Content -LiteralPath "$taskOut/symbols.txt"
if($LASTEXITCODE -ne 0){throw 'ELF symbols inspection failed'}
$taskManifest=@{
  toolchain='Vitis 2020.2 / GCC 9.2.0 / standalone 7.3'
  source_sha256=(Get-FileHash -LiteralPath "$PSScriptRoot/ddr_lane_probe.c" -Algorithm SHA256).Hash.ToLowerInvariant()
  elf_sha256=(Get-FileHash -LiteralPath "$taskOut/ddr_lane_probe.elf" -Algorithm SHA256).Hash.ToLowerInvariant()
  symbols_sha256=(Get-FileHash -LiteralPath "$taskOut/symbols.txt" -Algorithm SHA256).Hash.ToLowerInvariant()
  bsp_lib_sha256=(Get-FileHash -LiteralPath "$taskBsp/lib/libxil.a" -Algorithm SHA256).Hash.ToLowerInvariant()
  storage_access=$false
}
$taskManifest | ConvertTo-Json | Set-Content -LiteralPath "$taskOut/manifest.json"
