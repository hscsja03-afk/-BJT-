"""Isolated TX1 peripheral reset, bounded code-2000 hold, and final power-down."""
import subprocess, shlex
program='''
import fcntl,json,sys,time
from pathlib import Path
paths=sorted(Path('/home/xilinx/.zynq_bjt_desktop').glob('*/agent.pyz'),key=lambda p:p.stat().st_mtime)
sys.path.insert(0,str(paths[-1]))
from pynq import MMIO
from zynq_bjt.tx1 import Tx1
lock=open('/tmp/zynq_bjt_desktop.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
tx=Tx1(MMIO(0x43c00000,0x10000))
registers=lambda: {str(r):tx.transfer(r) for r in (1,2,3,4,7,8)}
try:
 print('BEFORE_RESET',json.dumps(registers()),flush=True)
 tx.transfer(5,0x000a);time.sleep(.01)
 print('RESET_DEFAULTS',json.dumps(registers()),flush=True)
 tx.initialize_muted();tx.code(2000);tx.enable(True)
 print('TX1_SOFT_RESET_HOLD',json.dumps(registers()),flush=True)
 time.sleep(40)
finally:
 tx.verified(3,1)
 print('TX1_OUTPUT_DISABLED',json.dumps(registers()),flush=True)
'''
subprocess.run(['/bin/bash','-c','source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; exec python -u -c '+shlex.quote(program)],check=True)
