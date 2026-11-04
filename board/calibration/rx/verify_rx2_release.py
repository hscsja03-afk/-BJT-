"""Read RX2 using the released agent/table against three nominal DG1032Z points."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import statistics
import sys
import time
from board.calibration.rx.calibrate_rx1_generator import Generator
from board.instruments.tx2_scope_zero import SerialAgent, ROOT
sys.path.insert(0, str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration
from zynq_bjt.scope_display import reference_channels

out=ROOT/'report/rx2_generator_nominal_20261031/release'
out.mkdir(parents=True,exist_ok=False)
base=ROOT/'build/dist/desktop/ZynqBjtDesktop/_internal'
cal=Calibration(base/'data')
r=dict(at=datetime.now().astimezone().isoformat(),events=[],points=[],passed=False,
       reference_basis='Generator nominal DC offset, High-Z; not absolute accuracy',
       absolute_accuracy_verified=False,calibration=cal.manifest())
a=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events'],base=base)
g=None
try:
    g=Generator(out/'generator.jsonl');r['generator']=g.idn;g.off()
    r['connected']=a.connect();r['initialized']=a.call('initialize',timeout=120)
    assert not any(v['enabled'] for v in r['initialized']['outputs'])
    seen=set()
    for index,volts in enumerate((0.0,.75,-.75,0.0)):
        g.dc(volts);time.sleep(.3)
        point=dict(nominal_v=volts,frames=[],reference_v=[])
        r['points'].append(point)
        for repeat in range(4):
            frame=a.call('capture',timeout=20)
            file=out/('point{}_frame{}.json'.format(index,repeat))
            file.write_text(json.dumps(frame),encoding='utf-8')
            assert not frame['simulated'] and frame['sequence'] not in seen
            seen.add(frame['sequence'])
            assert all(49e6<v<51e6 for v in frame['sample_rates_hz'])
            ch=reference_channels(frame,cal)[1]
            assert ch['nominal_dc_calibrated'] and ch['invalid_samples']==0
            assert ch['overrange']==0 and ch['mean_v'] is not None
            point['frames'].append(dict(file=file.name,sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                                        mean_v=ch['mean_v'],discarded=repeat==0))
            if repeat:point['reference_v'].append(ch['mean_v'])
        point['mean_v']=statistics.fmean(point['reference_v'])
        point['error_v']=point['mean_v']-volts
        assert abs(point['error_v'])<.005,point
        print(json.dumps({k:point[k] for k in ('nominal_v','mean_v','error_v')}),flush=True)
    r['final_status']=a.call('status')
    assert not any(v['enabled'] for v in r['final_status']['outputs'])
    assert r['final_status']['gpio']==r['initialized']['gpio']
    r['passed']=True
except BaseException as error:
    r['error']=repr(error)
    raise
finally:
    errors=[]
    if g:
        try:g.off();r['generator_output_off']=True
        except Exception as error:errors.append('Generator: '+repr(error))
        finally:g.s.close()
    try:r['closed']=a.close()
    except Exception as error:errors.append('Board: '+repr(error))
    r['cleanup_errors']=errors
    if errors:r['passed']=False
    (out/'verification.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=r['passed'],generator_off=r.get('generator_output_off'),cleanup_errors=errors)),flush=True)
