"""UART root payload: update only the existing startup Python script.

The host prepends DEPLOYMENT (verified package manifest) and STARTUP_SOURCE
(the startup string from install_persistent_startup.py). No boot image writes.
"""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

root = Path(DEPLOYMENT['remote'])
assert root.parent == Path('/home/xilinx/.zynq_bjt_desktop')
assert root.name == DEPLOYMENT['digest']
for name, expected in DEPLOYMENT['files'].items():
    path = root / name
    path.resolve().relative_to(root.resolve())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
assert str(root / 'agent.pyz') in STARTUP_SOURCE
assert DEPLOYMENT['files']['agent.pyz'] in STARTUP_SOURCE
compile(STARTUP_SOURCE, 'zynq_bjt_autostart.py', 'exec')
dest = Path('/usr/local/lib/zynq_bjt_autostart.py')
assert dest.is_file(), 'Existing startup script required'
assert subprocess.run(['systemctl', 'is-enabled', 'zynq-bjt-startup.service'],
                      check=True).returncode == 0
backup = Path('/home/xilinx/persistence_backup_tx1_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
backup.mkdir(exist_ok=False)
shutil.copy2(dest, backup / dest.name)
shutil.copy2('/etc/systemd/system/zynq-bjt-startup.service', backup / 'zynq-bjt-startup.service')
temporary = dest.with_suffix('.py.new')
temporary.write_text(STARTUP_SOURCE)
temporary.chmod(dest.stat().st_mode)
temporary.replace(dest)
subprocess.run(['sync'], check=True)
subprocess.run(['systemctl', 'restart', 'zynq-bjt-startup.service'], check=True, timeout=180)
ready = json.loads(Path('/run/zynq_bjt_ready.json').read_text())
assert ready['ready'] is True and ready['outputs_enabled'] is False, ready
assert ready['agent'] == str(root / 'agent.pyz'), ready
assert ready['agent_sha256'] == DEPLOYMENT['files']['agent.pyz'], ready
print('STARTUP_AGENT_UPDATED', json.dumps(dict(backup=str(backup), ready=ready)), flush=True)
