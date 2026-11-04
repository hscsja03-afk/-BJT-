"""Check real DAC60501 writes/readbacks while keeping TX1 powered down."""
import shlex
import subprocess

program = '''
import fcntl, hashlib, json, sys, zipfile
from pathlib import Path
paths=sorted(Path('/home/xilinx/.zynq_bjt_desktop').glob('*/agent.pyz'),key=lambda p:p.stat().st_mtime)
archive=paths[-1]
sys.path.insert(0,str(archive))
from pynq import MMIO
from zynq_bjt.tx1 import Tx1
lock=open('/tmp/zynq_bjt_desktop.lock','a')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
with zipfile.ZipFile(archive) as z:
 print('TX1_DRIVER_SHA256',hashlib.sha256(z.read('zynq_bjt/tx1.py')).hexdigest(),flush=True)
tx=Tx1(MMIO(0x43c00000,0x10000))
try:
 tx.initialize_muted()
 for code in (0,1000,1638,2000,4095,0):
  tx.code(code)
  regs={str(r):tx.transfer(r) for r in (1,2,3,4,7,8)}
  assert regs['1']==0x2195
  assert regs['2']&1==0
  assert regs['3']&0x0101==1
  assert regs['4']&0x0101==0x0101
  assert regs['7']&1==0
  assert regs['8']==code<<4
  print('TX1_MUTED_WRITE',json.dumps(dict(code=code,registers=regs)),flush=True)
finally:
 tx.verified(3,1)
 print('TX1_POWERDOWN_CONFIRMED',hex(tx.transfer(3)),flush=True)
'''
subprocess.run(['/bin/bash','-c',
    'source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; exec python -u -c '+shlex.quote(program)],check=True)
