"""Independently validate mailbox lengths, sequence, CRC and OCM result."""
from pathlib import Path
import hashlib
import json
import re
import struct
import sys
import zlib

def verify(path):
    text=path.read_text(encoding='utf-8-sig')
    rows=[]
    for seq,op,status,count,crc,values in re.findall(
            r'BAREMETAL_RESPONSE seq=(\d+) op=(\d+) status=(\d+) count=(\d+) crc=(\d+) values=([^\r\n]*)',text):
        seq,op,status,count,crc=map(int,(seq,op,status,count,crc))
        values=list(map(int,values.split()))
        if len(values)!=count:raise ValueError('Incorrect response count')
        data=[seq,status,count]+values
        if zlib.crc32(struct.pack('<'+'I'*len(data),*data))&0xffffffff != crc:raise ValueError('Response CRC mismatch')
        rows.append(dict(sequence=seq,op=op,status=status,values=values))
    match=re.search(r'BAREMETAL_READY board=(original|custom) ddr_initialized=0 analog_initialized=0',text)
    if not match:raise ValueError('Missing completion marker')
    original=match[1]=='original'
    inputs=json.loads(path.with_name(path.stem+'_inputs.json').read_text(encoding='utf-8-sig'))
    if [r['sequence'] for r in rows] != ([1,2,3] if original else [1,2]):raise ValueError('Missing/duplicate responses')
    if rows[0]['op']!=1 or rows[0]['status'] or rows[0]['values'][:3]!=[1,int(not original),0]:raise ValueError('Invalid identity')
    if len(rows[0]['values'])!=7 or rows[0]['values'][6]!=inputs['firmware']['build_id']:
        raise ValueError('Firmware build identity differs from recorded input')
    if rows[1]['op']!=9 or rows[1]['status'] or rows[1]['values'][:2]!=[4096,0]:raise ValueError('OCM scratch check failed')
    if original and (rows[2]['op']!=2 or rows[2]['status']!=7):raise ValueError('Probe allowed analog initialization')
    result={'board':match[1],'ocm_startup_passed':True,'ddr_initialized':False,
            'analog_initialized':False,'uart_verified':False,'responses':rows,
            'runtime_inputs_sha256':hashlib.sha256(path.with_name(path.stem+'_inputs.json').read_bytes()).hexdigest(),
            'log_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'limits':'4 KiB scratch test and mailbox protocol only; no ADC/DAC or whole-OCM qualification.'}
    path.with_name(path.stem+'_result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':verify(Path(sys.argv[1]))
