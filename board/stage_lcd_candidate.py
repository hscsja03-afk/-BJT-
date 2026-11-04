"""生成串口传输载荷；候选文件独立存放，不改启动位流。"""
import base64,hashlib,json,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
files={name:(ROOT/'build/work/lcd_candidate_20261101'/name).read_bytes() for name in ('bjt.bit','bjt.hwh')}
payload={name:base64.b64encode(zlib.compress(data)).decode() for name,data in files.items()}
hashes={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
out=ROOT/'report/lcd_offline_20261101'
program='''import base64,zlib,hashlib,json
from pathlib import Path
root=Path('/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/lcd_candidate_20261101')
root.mkdir(exist_ok=True)
for name,value in PAYLOAD.items():
 data=zlib.decompress(base64.b64decode(value))
 assert hashlib.sha256(data).hexdigest()==HASHES[name]
 (root/name).write_bytes(data)
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==HASHES[name]
print('LCD_CANDIDATE_STAGED',json.dumps(HASHES),flush=True)
'''
(out/'stage_payload.py').write_text('PAYLOAD='+repr(payload)+'\nHASHES='+repr(hashes)+'\n'+program,encoding='utf-8')
(out/'candidate_hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print(out/'stage_payload.py')
