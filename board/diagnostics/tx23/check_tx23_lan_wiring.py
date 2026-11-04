"""Bounded wide-range routing check before AC fitting; no calibration writes."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
import json
from pathlib import Path
import time
import numpy as np
from board.calibration.tx.calibrate_tx_waves_lan import LanScope, ROOT
from zynq_bjt.desktop_transport import SshTransport, agent_archive
from zynq_bjt.frontend import Calibration

ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
r={'checks':[]};scope=None;agent=SshTransport();cal=Calibration(ROOT/'data')
def save():(out/'result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
try:
    scope=LanScope('169.254.1.5','169.254.3.254',1);r['scope_idn']=scope.idn
    r['connected']=agent.connect('192.168.0.4','xilinx','xilinx',ROOT/'measurements/known_hosts',
        ROOT/'data',agent_archive(ROOT/'src/python/zynq_bjt'),
        bitfile='/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit')
    r['initialized']=agent.call('initialize');agent.call('stop');save()
    for channel in (2,3):
        agent.call('stop');scope.setup(channel+1,scale=.5)
        for ch in (2,3,4):
            for k,v in [('DISPlay','ON'),('PROBe','1'),('COUPling','DC'),('SCALe','.5'),('OFFSet','0')]:
                scope.write(f':CHANnel{ch}:{k} {v}')
        scope.point(100000,0)
        if channel==2:
            zero=cal.dac_code(1,.9)[0];peak=abs(cal.dac_code(1,1)[0]-cal.dac_code(1,.8)[0])//2
        else:
            p=cal.waveform_parameters('sine',100000,.2);zero=round(p['zero_code']);peak=round(p['peak_codes'])
        state=agent.call('output',dict(channel=channel-1,action='start',mode='sine_code',frequency_hz=100000,
            offset=zero,peak=peak,phase_degrees=0,wiring_confirmed=True))
        assert sum(bool(x['enabled']) for x in state['outputs'])==1
        time.sleep(3)
        row=dict(tx=channel,zero_code=zero,peak_codes=peak,measurements={})
        for ch in (2,3,4):
            row['measurements'][str(ch)]={k:scope.ask(f':MEASure:ITEM? {k},CHANnel{ch}') for k in ('VAVG','VPP','FREQ')}
        scope.write(':STOP');scope.write(f':WAVeform:SOURce CHANnel{channel+1}');scope.write(':WAVeform:MODE RAW')
        scope.write(':WAVeform:STARt 1');scope.write(':WAVeform:STOP 12000')
        pre=[float(v) for v in scope.ask(':WAVeform:PREamble?').split(',')]
        block=scope.ask_raw(b':WAVeform:DATA?');assert block[:1]==b'#'
        digits=int(block[1:2]);size=int(block[2:2+digits]);raw=np.frombuffer(block[2+digits:2+digits+size],dtype=np.uint8)
        np.savez_compressed(out/f'tx{channel}_wide.npz',raw=raw,preamble=pre)
        values=(raw.astype(float)-pre[8]-pre[9])*pre[7]
        row['wide_raw']=dict(samples=len(raw),min_v=float(values.min()),max_v=float(values.max()),mean_v=float(values.mean()))
        r['checks'].append(row);save();print(json.dumps(row),flush=True)
    r['complete']=True
except BaseException as e:r['error']=repr(e);print('ERROR',repr(e),flush=True)
finally:
    if agent.alive:
        try:r['stopped']=agent.call('stop');r['closed']=agent.close()
        except Exception as e:r['cleanup_error']=repr(e);agent.abort()
    if scope:
        try:scope.restore();r['scope_restored']=True
        except Exception as e:r['scope_restore_error']=repr(e)
        finally:scope.s.close()
    save()
