"""Deploy the desktop's content-addressed agent/data through the Linux UART.

Requires an idle logged-in shell; no root, PL reload, service or output changes.
"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[2]))

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import sys
import time
import zlib
from board.instruments.tx2_scope_zero import ROOT, serial


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--base',type=Path,default=ROOT/'build/dist/desktop/ZynqBjtDesktop/_internal')
    ap.add_argument('--report',type=Path,required=True)
    args=ap.parse_args()
    files={'agent.pyz':(args.base/'agent.pyz').read_bytes()}
    files.update({'data/'+p.name:p.read_bytes() for p in (args.base/'data').glob('*.json')})
    digest=hashlib.sha256(files['agent.pyz']+b''.join(files[n] for n in sorted(files) if n.startswith('data/'))).hexdigest()[:20]
    remote='/home/xilinx/.zynq_bjt_desktop/'+digest
    payload=base64.b64encode(zlib.compress(json.dumps({n:base64.b64encode(b).decode() for n,b in files.items()}).encode())).decode()
    chunks=[payload[i:i+1024] for i in range(0,len(payload),1024)]
    program=('import base64,zlib,json,sys,hashlib;from pathlib import Path;'
             'print("UART_DEPLOY_READY",flush=True);'
             'n=int(input());d=json.loads(zlib.decompress(base64.b64decode("".join(input() for _ in range(n)))));'
             'd={k:base64.b64decode(v) for k,v in d.items()};'
             'assert all(k=="agent.pyz" or (k.startswith("data/") and k.endswith(".json") and k.count("/")==1) for k in d);'
             'h=hashlib.sha256(d["agent.pyz"]+b"".join(d[k] for k in sorted(d) if k.startswith("data/"))).hexdigest()[:20];'
             'assert h=='+repr(digest)+';'
             'root=Path('+repr(remote)+');(root/"data").mkdir(parents=True,exist_ok=True);'
             '[(root/k).write_bytes(v) for k,v in d.items()];'
             'assert all((root/k).read_bytes()==v for k,v in d.items());'
             'print("UART_DEPLOY_OK "+h,flush=True)')
    uart=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=5)
    uart.dtr=uart.rts=False;uart.port='COM7'
    received=bytearray()
    def until(marker,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            received.extend(uart.read(uart.in_waiting or 1))
            if marker in received:return
        raise TimeoutError('Missing UART deployment marker: '+marker.decode())
    r={'remote':remote,'digest':digest,'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()},'verified':False}
    try:
        uart.open();uart.write(b'stty -echo -onlcr\n');uart.flush();time.sleep(.3)
        uart.read(uart.in_waiting)
        cmd='python3 -u -c '+shlex.quote(program)+"; stty echo onlcr; printf '\\nUART_DEPLOY_DONE\\n'\n"
        uart.write(cmd.encode());uart.flush();until(b'UART_DEPLOY_READY',10)
        for line in [str(len(chunks))]+chunks:
            uart.write((line+'\n').encode());uart.flush();time.sleep(.02)
        until(('UART_DEPLOY_OK '+digest).encode(),30)
        until(b'UART_DEPLOY_DONE',10);r['verified']=True
    except BaseException as e:r['error']=repr(e);raise
    finally:
        uart.close();r['received']=received.decode(errors='replace')
        args.report.write_text(json.dumps(r,indent=2),encoding='utf-8')
        print(json.dumps({k:r[k] for k in ('remote','verified')}))


if __name__=='__main__':main()
