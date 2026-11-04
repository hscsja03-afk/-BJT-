"""Stage a timing-passed ADC candidate, retaining the production overlay."""
import argparse,base64,hashlib,json,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
p=argparse.ArgumentParser();p.add_argument('build',type=Path);p.add_argument('--name',required=True);a=p.parse_args()
assert a.name.replace('_','').isalnum()
assert 'sta=passed' in (a.build/'build_status.txt').read_text()
out=ROOT/'report/adc_rate_raise_20261102';remote='/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/'+a.name
files={name:(a.build/name).read_bytes() for name in ('bjt.bit','bjt.hwh')}
hashes={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
payload={name:base64.b64encode(zlib.compress(data)).decode() for name,data in files.items()}
stage='''import base64,zlib,hashlib,json
from pathlib import Path
root=Path(REMOTE);root.mkdir(exist_ok=True)
for name,value in PAYLOAD.items():
 data=zlib.decompress(base64.b64decode(value));assert hashlib.sha256(data).hexdigest()==HASHES[name]
 (root/name).write_bytes(data);assert hashlib.sha256((root/name).read_bytes()).hexdigest()==HASHES[name]
print('STAGED',json.dumps(HASHES),flush=True)
'''
(out/'stage_payload.py').write_text('REMOTE='+repr(remote)+'\nPAYLOAD='+repr(payload)+'\nHASHES='+repr(hashes)+'\n'+stage,encoding='utf8')
for kind,path in [('load',remote+'/bjt.bit'),('restore','/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit')]:
 code="from pynq import Overlay; import fcntl; lock=open('/tmp/zynq_bjt_desktop.lock','a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); o=Overlay("+repr(path)+"); io=o.adda_core_0.mmio; assert io.read(0)==0x41444441; print('OVERLAY_LOADED',"+repr(path)+",flush=True)"
 (out/(kind+'_payload.py')).write_text('import subprocess,shlex\ncode='+repr(code)+"\nsubprocess.run(['/bin/bash','-c','source /etc/profile.d/xrt_setup.sh; source /etc/profile.d/pynq_venv.sh; python -c '+shlex.quote(code)],check=True)\n",encoding='utf8')
(out/'candidate.json').write_text(json.dumps(dict(remote=remote,hashes=hashes,build=str(a.build.resolve())),indent=2),encoding='utf8')
print(remote)
