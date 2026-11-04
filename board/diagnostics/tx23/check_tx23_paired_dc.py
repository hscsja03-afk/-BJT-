"""Hold scope/TX2 settings fixed and alternate TX3 off/on to isolate interaction."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import os,json
from board.calibration.tx.calibrate_tx23_scope import Scope
from board.instruments.tx2_scope_zero import ROOT, SerialAgent

out=ROOT/'report/tx23_calibration_20261030/paired_dc';out.mkdir(exist_ok=False)
r={'events':[],'points':[]};s=None;agent=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events'])
def save():(out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
try:
    s=Scope();r['connected']=agent.connect();r['initialized']=agent.call('initialize',timeout=120)
    agent.call('output',dict(channel=1,action='start',mode='dc_voltage',offset=.5,wiring_confirmed=True))
    s.setup(3)
    for f in (None,100000,None,6000000,None,100000,None):
        req=dict(channel=2,action='stop') if f is None else dict(channel=2,action='start',mode='sine_voltage',offset=0,frequency_hz=f,vpp=.05,wiring_confirmed=True)
        state=agent.call('output',req)
        p=dict(tx3_hz=f,state=state,measurement=s.dc(.5,repeats=21))
        r['points'].append(p);save()
        print(json.dumps(dict(tx3_hz=f,mean=p['measurement']['mean_v'],std=p['measurement']['std_v'])),flush=True)
    r['paired_differences_v']=[r['points'][i]['measurement']['mean_v']-(r['points'][i-1]['measurement']['mean_v']+r['points'][i+1]['measurement']['mean_v'])/2 for i in (1,3,5)]
    r['max_paired_difference_v']=max(abs(x) for x in r['paired_differences_v'])
    r['within_1p5mv']=r['max_paired_difference_v']<.0015
except BaseException as e:r['error']=repr(e);raise
finally:
    try:r['close']=agent.close()
    except Exception as e:r['cleanup_error']=repr(e)
    if s:
        try:s.restore()
        except Exception as e:r['scope_restore_error']=repr(e)
        try:s.s.close()
        except Exception as e:r['scope_close_error']=repr(e)
    save();print(json.dumps({k:r.get(k) for k in ('paired_differences_v','max_paired_difference_v','within_1p5mv','close','error')}),flush=True)
