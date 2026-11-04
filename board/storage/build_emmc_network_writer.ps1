param([string]$ToolRoot='D:\FPGA\Xilix\2026.1')
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$taskBsp=Join-Path $taskRoot 'build/work/boot_software/core_2v5/ps7_cortexa9_0/diagnostic/bsp'
$taskGcc=Join-Path $ToolRoot 'gnu/aarch32/nt/gcc-arm-none-eabi/bin'
$taskOut=Join-Path $taskRoot 'build/work/emmc_network_writer'
$taskImage='D:\FPGA\WSL\PYNQ-work\ZYNQ-7020-2.7.0-emmc-fit.img'
$taskExistingManifest=Get-Content -LiteralPath (Join-Path $taskRoot 'build/work/emmc_writer/manifest.json') -Raw | ConvertFrom-Json
$taskImageInfo=Get-Item -LiteralPath $taskImage
if($taskImageInfo.Length -ne [long]$taskExistingManifest.image_bytes){throw 'Candidate image size differs from the audited image'}
$taskImageHash=(Get-FileHash -LiteralPath $taskImage -Algorithm SHA256).Hash.ToLowerInvariant()
if($taskImageHash -ne $taskExistingManifest.image_sha256){throw 'Candidate image hash differs from the audited image'}
New-Item -ItemType Directory -Force -Path $taskOut | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../config/ocm.ld') -Destination (Join-Path $taskOut 'ocm.ld')
$taskSources=@(
  (Join-Path $PSScriptRoot 'emmc_image_writer.c'),
  (Join-Path $taskRoot 'reference/embedded/sw/ethernet.c'),
  (Join-Path $taskRoot 'reference/embedded/sw/net_packet.c')
)
$taskDefines=@(
  '-DEMMC_NETWORK_WRITER=1',
  '-DEMMC_HOST_IP0=192','-DEMMC_HOST_IP1=168','-DEMMC_HOST_IP2=0','-DEMMC_HOST_IP3=3',
  '-DADDA_ETHERNET_IP0=192','-DADDA_ETHERNET_IP1=168','-DADDA_ETHERNET_IP2=0','-DADDA_ETHERNET_IP3=2',
  '-DADDA_ETHERNET_MAC0=0','-DADDA_ETHERNET_MAC1=10','-DADDA_ETHERNET_MAC2=53',
  '-DADDA_ETHERNET_MAC3=1','-DADDA_ETHERNET_MAC4=254','-DADDA_ETHERNET_MAC5=192'
)
& "$taskGcc/arm-none-eabi-gcc.exe" @taskDefines -DSDT -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -O2 -g -Wall -Wextra -Werror -std=c11 `
  "-I$taskBsp/include" "-I$(Join-Path $taskRoot 'reference/embedded/sw')" "-L$taskBsp/lib" "-specs=$taskBsp/Xilinx.spec" `
  "-Wl,-T,$taskOut/ocm.ld" "-Wl,-Map,$taskOut/emmc_network_writer.map" `
  '-Wl,--wrap=XSdPs_EmmcModeInit,--wrap=XSdPs_MmcModeInit,--wrap=XSdPs_Set_Mmc_ExtCsd' `
  @taskSources '-Wl,--start-group' -lxiltimer -lxil -lxilstandalone -lgcc -lc '-Wl,--end-group' `
  -o (Join-Path $taskOut 'emmc_network_writer.elf')
if($LASTEXITCODE -ne 0){throw 'Network eMMC writer compile/link failed'}
$taskSize=& "$taskGcc/arm-none-eabi-size.exe" (Join-Path $taskOut 'emmc_network_writer.elf')
if($LASTEXITCODE -ne 0){throw 'Network eMMC writer size inspection failed'}
$taskSize | Tee-Object -FilePath (Join-Path $taskOut 'size.txt')
& "$taskGcc/arm-none-eabi-nm.exe" -n (Join-Path $taskOut 'emmc_network_writer.elf') | Set-Content -LiteralPath (Join-Path $taskOut 'symbols.txt')
if($LASTEXITCODE -ne 0){throw 'Network eMMC writer symbol inspection failed'}
$taskSourceNames=@('emmc_image_writer.c','ethernet.c','net_packet.c')
$taskSourceHashes=@{}
for($taskIndex=0;$taskIndex -lt $taskSources.Count;$taskIndex++){
  $taskSourceHashes[$taskSourceNames[$taskIndex]]=(Get-FileHash -LiteralPath $taskSources[$taskIndex] -Algorithm SHA256).Hash.ToLowerInvariant()
}
$taskManifest=@{
  source_sha256=$taskSourceHashes
  elf_sha256=(Get-FileHash -LiteralPath (Join-Path $taskOut 'emmc_network_writer.elf') -Algorithm SHA256).Hash.ToLowerInvariant()
  symbols_sha256=(Get-FileHash -LiteralPath (Join-Path $taskOut 'symbols.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
  image_sha256=$taskImageHash
  image_bytes=$taskImageInfo.Length
  image_sectors=[long]($taskImageInfo.Length/512)
  target_emmc_cid=$taskExistingManifest.target_emmc_cid
  storage_write_capability=$true
  per_chunk_readback=$true
  network_protocol='UDP5001 with packet echo, sequence tracking, chunk CRC32, and retries'
  network_board_ip='192.168.0.2'
  network_host_ip='192.168.0.3'
  network_mac='00:0a:35:01:fe:c0'
  chunk_bytes=33554432
  udp_payload_bytes=1472
}
$taskManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskOut 'manifest.json')
Write-Output (Join-Path $taskOut 'emmc_network_writer.elf')
