"""Run with Vitis 2026.1: vitis -s board/boot/create_boot_platform.py.

Generates an offline standalone domain/FSBL from the board-specific XSA.
No debug connection, deployment or persistent-storage operation is performed.
"""
from pathlib import Path
import vitis

root = Path(__file__).resolve().parents[2]
workspace = root / "build/work/boot_software"
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(
        name="core_2v5", hw_design=str(root / "build/work/linux_platform/core_2v5.xsa"),
        os="standalone", cpu="ps7_cortexa9_0", domain_name="diagnostic")
    domain = platform.get_domain(name="diagnostic")
    domain.set_config(option="os", param="standalone_stdout", value="ps7_uart_0")
    domain.set_config(option="os", param="standalone_stdin", value="ps7_uart_0")
    platform.build()
    print("BOOT_PLATFORM_GENERATED", workspace)
finally:
    vitis.dispose()
