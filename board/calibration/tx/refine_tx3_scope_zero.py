"""Refine DC zero after the long amplitude sweep; keep both evidence sets.

Adding an integer zero correction translates every AWG sample equally. The
78-knot amplitude sweep remains recorded at its actual zero code; the final
zero is independently measured across 13 frequencies, with amplitude checks.
"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import numpy as np
from board.calibration.tx.calibrate_tx23_scope import Scope
from board.instruments.tx2_scope_zero import SerialAgent


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    original=json.loads(args.source.read_text())
    assert original['status']=='completed' and original['close']['cleanup_confirmed']
    assert original['max_vpp_error_v']<.00075
    assert len(original['verification'])==78 and len(original['midpoints'])==12
    r=dict(original)
    r.update(started=datetime.now(timezone(timedelta(hours=8))).isoformat(),events=[],status='running',verified=False,
             amplitude_calibration_source=str(args.source),amplitude_verification_zero_code=original['zero_code'],
             amplitude_sweep_max_dc_error_v=original['max_dc_error_v'],zero_adjustments=[],final_zero_verification=[])
    r.pop('close',None);r.pop('ended',None)
    agent=SerialAgent('COM7',os.environ['PYNQ_SSH_PASSWORD'],r['events']);s=None
    def save():(args.out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
    def measure(f,z,label):
        peak=float(np.interp(f,r['frequency_hz'],r['candidate_peaks']))
        state=agent.call('output',dict(channel=2,action='start',wiring_confirmed=True,mode='sine_code',frequency_hz=f,offset=z,peak=peak))
        s.point(f);rows=[]
        for j in range(3):
            for attempt in range(3):
                path=args.out/f'{label}_{j}_try{attempt}.npz'
                try:rows.append(s.capture(path,f));break
                except AssertionError as e:
                    r.setdefault('rejected_acquisitions',[]).append(dict(path=str(path),reason=str(e)));save()
                    if attempt==2:raise
                    s.write(':CHANnel4:SCALe .02');s.write(':CHANnel4:SCALe .01');s.point(f)
        p=dict(requested_hz=f,zero_code=z,peak_code=peak,state=state,individual=rows)
        p.update({k:float(np.mean([x[k] for x in rows])) for k in ('vpp_v','dc_v','frequency_hz','thd_2_3')})
        p['error_v']=p['vpp_v']-.05
        return p
    try:
        s=Scope();r['final_scope_before']=s.prior;r['connected']=agent.connect();r['initialized']=agent.call('initialize',timeout=120)
        s.setup(4,sine=True)
        s.write(':CHANnel4:COUPling GND')
        r['scope_internal_ground']=s.dc(0,repeats=7)
        assert abs(r['scope_internal_ground']['mean_v'])<.002,'Scope zero reference is abnormal'
        s.write(':CHANnel4:COUPling DC')
        z=original['zero_code'];slope=original['zero_slope_v_per_code']
        for i in range(3):
            p=measure(100000,z,'adjust'+str(i));r['zero_adjustments'].append(p);save()
            print(f'zero adjustment {i} code {z}: {p["dc_v"]*1000:.4f}mV',flush=True)
            if abs(p['dc_v'])<.0004:break
            if i<2:z=round(z-p['dc_v']/slope)
        r['zero_code']=z
        for f in (10000,55000,100000,200000,450000,950000,1550000,2550000,3550000,4550000,5550000,6000000,100000):
            p=measure(f,z,'zero_verify'+str(len(r['final_zero_verification'])))
            r['final_zero_verification'].append(p);save()
            print(f'final zero {f}Hz: {p["dc_v"]*1000:.4f}mV, Vpp error {p["error_v"]*1000:.4f}mV',flush=True)
        r['max_dc_error_v']=max(abs(p['dc_v']) for p in r['final_zero_verification'])
        r['max_vpp_error_v']=max(original['max_vpp_error_v'],max(abs(p['error_v']) for p in r['final_zero_verification']))
        r['verified']=r['max_dc_error_v']<.002 and r['max_vpp_error_v']<.00075
        r['status']='completed'
    except BaseException as e:r['error']=repr(e);r['status']='failed';raise
    finally:
        try:r['close']=agent.close()
        except Exception as e:r['cleanup_error']=repr(e)
        if s:
            try:s.restore()
            except Exception as e:r['scope_restore_error']=repr(e)
            try:s.s.close()
            except Exception as e:r['scope_close_error']=repr(e)
        r['ended']=datetime.now(timezone(timedelta(hours=8))).isoformat();save()
        print(json.dumps({k:r.get(k) for k in ('status','verified','max_dc_error_v','max_vpp_error_v','close','error')}),flush=True)


if __name__=='__main__':main()
