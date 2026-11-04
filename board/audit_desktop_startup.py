"""UART maintenance payload: inspect installed startup/data without I/O writes."""
from pathlib import Path
import fcntl
import hashlib
import json
import subprocess

lock = open('/tmp/zynq_bjt_desktop.lock', 'a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
startup = Path('/usr/local/lib/zynq_bjt_autostart.py')
overlay = Path('/home/xilinx/jupyter_notebooks/zynq_bjt/overlay')
result = dict(startup_source=startup.read_text(),
              startup_sha256=hashlib.sha256(startup.read_bytes()).hexdigest(),
              overlay={name: hashlib.sha256((overlay/name).read_bytes()).hexdigest()
                       for name in ('bjt.bit', 'bjt.hwh')})
result['service'] = subprocess.run(
    ['systemctl', 'show', 'zynq-bjt-startup.service',
     '--property=ActiveState,SubState,Result,ExecMainStatus,UnitFileState'],
    check=True, stdout=subprocess.PIPE, universal_newlines=True).stdout
ready = Path('/run/zynq_bjt_ready.json')
result['ready_record'] = json.loads(ready.read_text()) if ready.exists() else None
result['notebook_data'] = {}
for path in Path('/home/xilinx/jupyter_notebooks/zynq_bjt/data').glob('*.json'):
    result['notebook_data'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
print('DESKTOP_STARTUP_AUDIT ' + json.dumps(result), flush=True)
