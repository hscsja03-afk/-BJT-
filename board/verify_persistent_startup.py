"""Read-only checks after Linux boot; does not load PL or initialize outputs."""
from pathlib import Path
import hashlib
import json
import mmap
import os
import struct
import subprocess
import time

fd = os.open('/dev/mem', os.O_RDONLY | os.O_SYNC)
try:
    with mmap.mmap(fd, 4096, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ, offset=0xf8000000) as registers:
        boot_mode = struct.unpack_from('<I', registers, 0x25c)[0]
finally:
    os.close(fd)
print('BOOT_MODE_RAW', hex(boot_mode), 'BOOT_MODE_DEVICE', boot_mode & 7, flush=True)
if globals().get('EXPECTED_BOOT_MODE') is not None:
    assert boot_mode & 7 == EXPECTED_BOOT_MODE, boot_mode

def command(*args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print('COMMAND', list(args), result.returncode, result.stdout, flush=True)
    return result

deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    state = subprocess.run(['systemctl', 'is-active', 'zynq-bjt-startup.service'],
                           stdout=subprocess.PIPE, text=True).stdout.strip()
    if state in ('active', 'failed'):
        break
    time.sleep(5)
command('systemctl', 'show', 'zynq-bjt-startup.service', '--property=ActiveState,SubState,Result,ExecMainStatus,UnitFileState')
command('journalctl', '-b', '-u', 'zynq-bjt-startup.service', '--no-pager', '-n', '35')
assert state == 'active', state
ready = json.loads(Path('/run/zynq_bjt_ready.json').read_text())
assert ready['ready'] is True and ready['outputs_enabled'] is False, ready
assert ready['agent'] == '/home/xilinx/.zynq_bjt_desktop/1fec68fce6f25b9007bb/agent.pyz', ready
assert ready['agent_sha256'] == '0c332428861cb7a16754a3f4aa8b4cf09f895e256aa8dd1c2a637d329b68582c', ready
print('READY_RECORD', json.dumps(ready), flush=True)
assert command('systemctl', 'is-enabled', 'zynq-bjt-startup.service').returncode == 0
assert command('systemctl', 'is-active', 'pl_server.service', 'ssh.service', 'jupyter.service').returncode == 0
assert command('findmnt', '/').returncode == 0
assert command('findmnt', '/boot').returncode == 0
command('ip', '-4', 'addr', 'show', 'eth0')
checks = {
    '/boot/boot.scr': '2314b8381a221f8f65907316c7068a609a83e9225dd0c9d03937ab596bc9c37a',
    '/home/xilinx/.zynq_bjt_desktop/1fec68fce6f25b9007bb/data/dac_calibration.json': 'd0c755811c6317452f2e955ce57bc23970bf98df3baaee3f4ab332736ccf1df5',
}
for filename, expected in checks.items():
    actual = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
    print('FILE_SHA256', filename, actual, flush=True)
    assert actual == expected, filename
print('PERSISTENT_STARTUP_VERIFIED', flush=True)
