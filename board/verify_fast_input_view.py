"""Verify the default segmented input sweep on the unchanged NPN small fixture."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.desktop_transport import SshTransport,agent_archive
from zynq_bjt.scan import ScanConfig

out=ROOT/'report/desktop_fast_fixed_axes_20261031'
out.mkdir(parents=True,exist_ok=True)
r=dict(passed=False,events=[])
started=time.monotonic()
def emit(kind,value):
    r['events'].append(dict(kind=kind,elapsed_s=time.monotonic()-started,value=value))
    if kind=='point' and value['index']%5==0:
        print('POINT {}: UBE={:.5f} V, IB={:.3f} uA'.format(value['index']+1,value['ube_v'],value['ib_estimated_a']*1e6),flush=True)
t=SshTransport(emit)
try:
    r['connected']=t.connect('192.168.0.4','xilinx',os.environ['PYNQ_SSH_PASSWORD'],
        ROOT/'measurements/known_hosts',ROOT/'data',agent_archive(ROOT/'src/python/zynq_bjt'))
    r['initialized']=t.call('initialize')
    config=asdict(ScanConfig())
    request=dict(measurement='input',config=config,profile='npn_small',fixture_confirmed=True,allow_reference=True)
    started=time.monotonic()
    result=t.call('scan',request,timeout=180)
    r['result']=result;r['local_directory']=str(t.fetch(result,ROOT/'measurements/results'))
    r['status']=t.call('status')
    assert not any(x['enabled'] for x in r['status']['outputs'])
    state=result['state']
    times=[e['elapsed_s'] for e in r['events'] if e['kind']=='point']
    r['timing']=dict(duration_s=state['finished_at']-state['started_at'],
        median_point_gap_s=statistics.median(b-a for a,b in zip(times,times[1:])) if len(times)>1 else None,
        first_point_s=times[0] if times else None)
    assert state['status']=='complete' and state['points']==25,(state['status'],state.get('error'))
    r['passed']=True
finally:
    try:r['closed']=t.close()
    except Exception as exc:r['cleanup_error']=repr(exc)
    (out/'hardware_verification.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(passed=r['passed'],timing=r.get('timing'),closed=r.get('closed')),ensure_ascii=False))
