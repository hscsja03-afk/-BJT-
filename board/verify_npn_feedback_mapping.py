"""One bounded NPN input point through the updated engine; retain failure evidence."""
from pathlib import Path
import json, os, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.desktop_transport import SshTransport,agent_archive
out=ROOT/'report/npn_mapping_fix_20261031/vb_div4'
out.mkdir(exist_ok=True)
r=dict(events=[],complete=False)
t=SshTransport(lambda k,v:r['events'].append(dict(kind=k,value=v)))
try:
    r['connected']=t.connect('192.168.0.4','xilinx',os.environ['PYNQ_SSH_PASSWORD'],
        ROOT/'measurements/known_hosts',ROOT/'data',agent_archive(ROOT/'src/python/zynq_bjt'))
    r['initialized']=t.call('initialize')
    result=t.call('scan',dict(measurement='input',profile='npn_small',fixture_confirmed=True,
        allow_reference=True,config=dict(tx1_start_v=.02,tx1_stop_v=.02,uce_values_v=[.5])),timeout=120)
    r['result']=result;r['local_directory']=str(t.fetch(result,out/'runs'))
    r['status']=t.call('status');assert not any(x['enabled'] for x in r['status']['outputs'])
    r['complete']=True
    print(json.dumps({k:result['state'].get(k) for k in ('status','points','error','rejected_point','bias_adjustments')},ensure_ascii=False),flush=True)
except BaseException as e:r['error']=repr(e);raise
finally:
    try:r['closed']=t.close()
    except Exception as e:r['cleanup_error']=repr(e)
    (out/'hardware_verification.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
