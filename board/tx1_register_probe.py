"""Read TX1 DAC registers under the instrument lock, without changing DAC configuration."""
import subprocess
import shlex

program = '''
import fcntl, json, sys, time
from pathlib import Path
paths=sorted(Path('/home/xilinx/.zynq_bjt_desktop').glob('*/agent.pyz'),key=lambda p:p.stat().st_mtime)
assert paths
sys.path.insert(0,str(paths[-1]))
from pynq import MMIO
from zynq_bjt.tx1 import Tx1
lock=open('/tmp/zynq_bjt_desktop.lock','a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
io=MMIO(0x43c00000,0x10000)
assert io.read(0x44)==0x54583101
dac=Tx1(io)
rows=[]
for _ in range(3):
 start=time.monotonic()
 registers={str(r):dac.transfer(r) for r in (1,2,3,4,7,8)}
 rows.append(dict(registers=registers,seconds=time.monotonic()-start))
print('TX1_REGISTER_PROBE',json.dumps(rows),flush=True)
'''
subprocess.run(['/bin/bash', '-c', 'source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; exec python -u -c ' + shlex.quote(program)], check=True)
