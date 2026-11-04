"""Compare immediate/LDAC/exact configuration without changing the nominal test code."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import json, os, time
from pathlib import Path
from board.instruments.tx2_scope_zero import SerialAgent
from board.calibration.tx.calibrate_tx23_scope import Scope

r={'events':[], 'points':[], 'completed':False, 'temporary_diagnostics_only':True}
a=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events'],base=Path('build/work/tx1_diagnostic_agent'))
s=None
try:
    r['connected']=a.connect()
    r['initialized']=a.call('initialize',timeout=120)
    s=Scope();s.setup(4,scale=.5)
    r['output']=a.call('output',dict(channel=0,action='start',mode='dc_code',offset=2000,wiring_confirmed=True))
    for mode in ('read','ldac','exact_config','sync_load','busywait_2us','sleep_100us'):
        diagnostic=a.call('tx1_diagnostics',{'mode':mode})
        time.sleep(.8)
        measured=s.dc(0,repeats=5)
        r['points'].append(dict(diagnostic=diagnostic,scope=measured))
        print('TX1_DIAGNOSTIC',mode,json.dumps(diagnostic),measured['mean_v'],flush=True)
    r['completed']=True
finally:
    try:
        # Restores ordinary asynchronous configuration, then closes all outputs.
        if r.get('initialized'):
            r['restore']=a.call('tx1_diagnostics',{'mode':'exact_config'})
    except Exception as exc:r['restore_error']=repr(exc)
    try:r['cleanup']=a.close()
    except Exception as exc:r['cleanup_error']=repr(exc)
    if s is not None:s.s.close()
    Path('report/tx1_timing_scope_20261030.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
