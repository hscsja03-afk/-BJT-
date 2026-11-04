$ErrorActionPreference='Stop'
$taskBsp='D:/FPGA/AMD_2026/build/work/baremetal/software/ocm_platform/ps7_cortexa9_0/baremetal/bsp'
& 'D:/FPGA/Xilix/2026.1/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe' -DSDT -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -Os -g -Wall -Wextra -Werror -std=c11 -ffunction-sections -fdata-sections '-Iboard/tx1_isolation' '-Ireference/embedded/sw' "-I$taskBsp/include" "-L$taskBsp/lib" "-specs=$taskBsp/Xilinx.spec" '-Wl,--gc-sections,--defsym=_HEAP_SIZE=0,--defsym=_STACK_SIZE=0x3000' '-Wl,-T,board/config/ocm.ld' board/tx1_isolation/main.c '-Wl,--start-group' -lxiltimer -lxil -lxilstandalone -lgcc -lc '-Wl,--end-group' -o build/work/tx1_reference_baremetal_20261030/isolation.elf
if($LASTEXITCODE -ne 0){throw 'Isolation compile failed'}
