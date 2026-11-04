param([string]$Port='COM7')
# Use only immediately after power-on in JTAG mode, or after Linux has shut down.
# Custom ADDA carrier only. No QSPI programming or whole-eMMC rewrite.
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
Push-Location $taskRoot
try {
    python board/boot/extract_zynq_uboot.py
    if($LASTEXITCODE -ne 0){throw 'U-Boot extraction failed'}
    $taskStamp=Get-Date -Format 'yyyyMMdd_HHmmss'
    $taskInputs=@{}
    foreach($taskFile in @(
        'build/work/pynq_jtag_boot/u-boot-verified.bin',
        'build/work/pynq_custom50/vivado/bjt.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl',
        'D:/FPGA/WSL/PYNQ-work/u-boot-system-custom.dtb'
    )) {
        $taskInputs[$taskFile]=(Get-FileHash -LiteralPath $taskFile -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $taskInputs | ConvertTo-Json | Set-Content -LiteralPath "build/logs/pynq_jtag_inputs_$taskStamp.json" -Encoding utf8
    python board/connection/pynq_uart.py --port $Port --seconds 25 --xsdb-script board/boot/run_pynq_uboot_jtag.tcl --abort-autoboot --expect 'Zynq>'
    if($LASTEXITCODE -ne 0){throw 'U-Boot startup failed; inspect UART and XSDB logs'}
    python board/connection/pynq_uart.py --port $Port --seconds 3 --command 'mmc dev 0' --command 'fatload mmc 0:1 0x10000000 image.ub' --command 'iminfo 0x10000000' --expect 'Hash(es) for Image 1 (fdt@0): sha1+'
    if($LASTEXITCODE -ne 0){throw 'eMMC FIT load or inspection failed'}
    python board/connection/pynq_uart.py --port $Port --seconds 1 --command 'setenv bootargs console=ttyPS0,115200 root=PARTUUID=d347d9ef-02 rw rootfstype=ext4 rootwait devtmpfs.mount=1 uio_pdrv_genirq.of_id=generic-uio clk_ignore_unused' --expect 'Zynq>'
    if($LASTEXITCODE -ne 0){throw 'U-Boot arguments were not acknowledged'}
    python board/connection/pynq_uart.py --port $Port --seconds 75 --command 'bootm 0x10000000' --expect 'xilinx@pynq:'
    if($LASTEXITCODE -ne 0){throw 'Linux login was not observed; inspect logs before any retry'}
    Write-Output 'PYNQ_JTAG_LINUX_LOGIN_VERIFIED'
} finally { Pop-Location }
