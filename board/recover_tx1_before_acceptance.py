"""One-time DAC recovery for the disconnected TX1-to-CH3 test fixture.

NOT a boot hook. A DAC reset may briefly restore its power-on midpoint.
Run only after the corrected startup agent is installed and no desktop agent
is holding the hardware lock. The finally block verifies power-down.
"""
import shlex
import subprocess

program = '''from pathlib import Path
import fcntl,hashlib,json,sys,time
agent=Path('/home/xilinx/.zynq_bjt_desktop/4591e228270b7977c0d5/agent.pyz')
assert hashlib.sha256(agent.read_bytes()).hexdigest()=='a3c98b0769da6b704b365bd4851263426af49bd0f062ac78a1f1e259b1802790'
lock=open('/tmp/zynq_bjt_desktop.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
sys.path.insert(0,str(agent))
from pynq import MMIO
from zynq_bjt.tx1 import Tx1
tx=Tx1(MMIO(0x43c00000,0x10000))
assert tx.io.read(0x44)==0x54583101
assert tx.transfer(1)==0x2195
print('TX1_BEFORE_RECOVERY',json.dumps({r:tx.transfer(r) for r in (1,2,3,4,7,8)}),flush=True)
try:
 tx.transfer(5,0x000a)
 time.sleep(.01)
 tx.initialize_muted()
finally:
 tx.verified(3,1)
print('TX1_RECOVERED_MUTED',json.dumps(tx.state()),flush=True)
assert tx.state()['enabled'] is False
'''
command = 'source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; exec python -u -c ' + shlex.quote(program)
subprocess.run(['bash', '-c', command], check=True, timeout=30)
