"""Bounded NPN input-route bias checks; preserve every ADC frame and mute on exit."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json, os, statistics, sys, time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.desktop_transport import SshTransport
from zynq_bjt.frontend import Calibration

out=ROOT/'report'/('npn_input_bias_'+datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S'))
out.mkdir(exist_ok=False)
base=ROOT/'build/dist/desktop/ZynqBjtDesktop/_internal'
cal=Calibration(base/'data')
r=dict(started=datetime.now(timezone(timedelta(hours=8))).isoformat(),points=[],events=[],complete=False)
t=SshTransport(lambda kind,value:r['events'].append(dict(kind=kind,value=value)))
def save():(out/'diagnostic.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
def output(ch,v):
    return t.call('output',dict(channel=ch,mode='dc_voltage',offset=v,action='start',wiring_confirmed=True))
try:
    r['connected']=t.connect('192.168.0.4','xilinx',os.environ['PYNQ_SSH_PASSWORD'],
        ROOT/'measurements/known_hosts',base/'data',(base/'agent.pyz').read_bytes())
    r['initialized']=t.call('initialize');assert not any(o['enabled'] for o in r['initialized']['outputs'])
    r['route']=t.call('gpio',dict(mask=127,value=64))
    assert r['route']['gpio']['output']==64 and r['route']['gpio']['sense']&127==64
    # Fixed small stimulation bounds, independent of suspect VC feedback.
    for index,(v1,v2) in enumerate(((.02,0),(.02,.04),(.02,0),(.05,0),(.1,0),(.02,0))):
        output(1,v2);output(0,v1);time.sleep(.7)
        p=dict(index=index,tx1_v=v1,tx2_v=v2,at=time.time(),frames=[]);r['points'].append(p)
        for repeat in range(4):
            f=t.call('capture');assert not f['simulated']
            name='point{}_frame{}.json'.format(index,repeat)
            (out/name).write_text(json.dumps(f),encoding='utf-8')
            means=[]
            for ch in (0,1):
                words=f['words'][ch];codes=[w&65535 for w in words]
                assert all(w>>16==0 for w in words) and min(codes)>0 and max(codes)<65535
                means.append(cal.port_v(statistics.fmean(codes),ch))
            p['frames'].append(dict(file=name,rx1_v=means[0],rx2_v=means[1],discarded=repeat==0))
            time.sleep(.15)
        p['rx1_v']=statistics.fmean(f['rx1_v'] for f in p['frames'][1:])
        p['vb_v']=statistics.fmean(f['rx1_v'] for f in p['frames'][1:])
        p['rx2_v']=statistics.fmean(f['rx2_v'] for f in p['frames'][1:])
        p['vc_v']=p['rx2_v']/.206
        save();print(json.dumps({k:v for k,v in p.items() if k!='frames'}),flush=True)
        assert abs(p['rx1_v'])<1.5 and abs(p['rx2_v'])<1.5,'Unexpected connector levels; bounded diagnostic stopped'
    r['complete']=True
except BaseException as e:r['error']=repr(e);raise
finally:
    try:r['closed']=t.close()
    except Exception as e:r['cleanup_error']=repr(e)
    save();print(str(out),flush=True)
