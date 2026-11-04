"""Prepare independently named, hash-checked UART overlay payloads."""
import base64
import hashlib
import json
from pathlib import Path
import zlib

ROOT=Path(__file__).resolve().parents[3]
out=ROOT/'report/datasheet_fft_acquisition_20261102'
build=ROOT/'build/work/adc4096_20261102'
assert 'sta=passed' in (build/'build_status.txt').read_text()
files={name:(build/name).read_bytes() for name in ('bjt.bit','bjt.hwh')}
payload={name:base64.b64encode(zlib.compress(data)).decode() for name,data in files.items()}
hashes={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
remote='/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/adc4096_20261102'
program='''import base64,zlib,hashlib,json
from pathlib import Path
root=Path(REMOTE)
root.mkdir(exist_ok=True)
for name,value in PAYLOAD.items():
 data=zlib.decompress(base64.b64decode(value))
 assert hashlib.sha256(data).hexdigest()==HASHES[name]
 (root/name).write_bytes(data)
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==HASHES[name]
print('ADC4096_STAGED',json.dumps(HASHES),flush=True)
'''
(out/'stage_payload.py').write_text('PAYLOAD='+repr(payload)+'\nHASHES='+repr(hashes)+'\nREMOTE='+repr(remote)+'\n'+program,encoding='utf-8')
load="from pynq import Overlay; import fcntl; lock=open('/tmp/zynq_bjt_desktop.lock','a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); o=Overlay("+repr(remote+'/bjt.bit')+"); io=o.adda_core_0.mmio; assert io.read(0)==0x41444441; assert io.read(0x30)==125000000; assert io.read(0xc)&0x20000000; assert io.read(0xcc)==4096; print('ADC4096_LOADED',flush=True)"
(out/'load_payload.py').write_text('import subprocess,shlex\nprogram='+repr(load)+"\nsubprocess.run(['/bin/bash','-c','source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; python -c '+shlex.quote(program)],check=True)\n",encoding='utf-8')
(out/'candidate_hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print({name:len(value) for name,value in payload.items()})
