"""Generate a standalone BSP from the DDR-disabled baseline XSA; no board access."""
from pathlib import Path
import vitis

root = Path(__file__).resolve().parents[2]
client = vitis.create_client()
try:
    client.set_workspace(str(root / 'build/work/baremetal/software'))
    platform = client.create_platform_component(
        name='ocm_platform', hw_design=str(root / 'build/work/baremetal/ocm_platform.xsa'),
        os='standalone', cpu='ps7_cortexa9_0', domain_name='baremetal')
    domain = platform.get_domain(name='baremetal')
    domain.set_config(option='os', param='standalone_stdout', value='ps7_uart_0')
    domain.set_config(option='os', param='standalone_stdin', value='ps7_uart_0')
    platform.build()
    print('BAREMETAL_BSP_GENERATED DDR=0')
finally:
    vitis.dispose()
