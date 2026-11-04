"""Bounded TX1-only DC response check via existing UART agent and Rigol CH4."""
import argparse
import json
import os
from pathlib import Path
import time
from tx2_scope_zero import SerialAgent
from calibrate_tx23_scope import Scope
from read_scope import read_scope

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--report',type=Path,default=Path('report/tx1_scope_response_20261030.json'))
args=parser.parse_args()
path=args.report
path.parent.mkdir(parents=True,exist_ok=True)
r={'events':[], 'points':[], 'connection':'User moved scope CH4 to TX1 connector',
   'completed':False, 'analog_calibration_qualified':False}
agent=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events'])
scope=None
try:
    r['connected']=agent.connect()
    print('TX1_UART_CONNECTED',flush=True)
    r['initialize']=agent.call('initialize',timeout=120)
    assert all(not o['enabled'] for o in r['initialize']['outputs'])
    scope=Scope(); scope.setup(4,scale=.5)
    for code in (0,1000,2000,1000,0):
        status=agent.call('output',dict(channel=0,action='start',mode='dc_code',offset=code,wiring_confirmed=True))
        assert status['outputs'][0]['enabled'] and status['outputs'][0]['code']==code
        assert all(not o['enabled'] for o in status['outputs'][1:])
        time.sleep(.7)
        measured=scope.dc(0,repeats=5)
        item={'code':code,'nominal_v':code*2.5/4096,'status':status,'scope':measured}
        r['points'].append(item)
        print('TX1_POINT',code,measured['mean_v'],flush=True)
        if code==2000:
            r['screenshot']=read_scope('169.254.1.5',4,path.with_name(path.stem+'_code2000'),r['connection'],scope=scope.s)
    r['completed']=True
finally:
    try:
        r['cleanup']=agent.close()
    except Exception as exc:
        r['cleanup_error']=repr(exc)
    if scope is not None:
        try: scope.s.close()
        except Exception as exc: r['scope_close_error']=repr(exc)
    path.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TX1_EVIDENCE',str(path),flush=True)
