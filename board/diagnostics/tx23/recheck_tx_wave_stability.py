"""Recheck unstable shapes at useful scope resolution, then revisit their grid.

Original failures remain in the report. Codes stay fixed during stability
windows and every independent revisit; this never edits calibration tables.
"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import time
from board.calibration.tx.calibrate_tx_waves_lan import LanScope, ROOT, stability
from zynq_bjt.desktop_transport import SshTransport, agent_archive


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();source=args.source.resolve();base=json.loads(source.read_text(encoding='utf8'))
    if base['status']!='complete' or not base.get('cleanup_confirmed'):
        raise ValueError('Source acquisition must have finished and confirmed cleanup')
    failed=[(ch,shape) for ch in (2,3) for shape in base['frequencies_hz']
            if not base['warmup'][f'TX{ch}_{shape}']['stability']['amplitude_stable']]
    if not failed:raise ValueError('No unstable shapes need rechecking')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    shutil.copytree(source.parent/'data_before',out/'data_before')
    for p in (out/'data_before').glob('*.json'):
        if p.read_bytes()!=(ROOT/'data'/p.name).read_bytes():raise ValueError('Calibration changed since source acquisition')
    r=copy.deepcopy(base)
    r.update(status='rechecking',cleanup_confirmed=False,scope_restored=False,
        started=datetime.now().astimezone().isoformat(),
        parent_acquisition=dict(path=str(source.relative_to(ROOT)),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                initialized=base['initialized'],finished=base['finished']),
        stability_rechecks={},prior_verification=[])
    for key in ('error','cleanup_error','scope_restore_error','finished','stopped','closed'):r.pop(key,None)
    agent=SshTransport();scope=None;sequence=0
    def save():(out/'result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
    def pause(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if (out/'stop.request').exists():raise InterruptedError('Stop requested')
            time.sleep(min(.5,max(0,end-time.monotonic())))
    def output(ch,row):
        state=agent.call('output',dict(channel=ch-1,action='start',mode=row['shape']+'_code',
            offset=row['zero_code'],peak=row['peak_codes'],frequency_hz=row['frequency_hz'],
            phase_degrees=0,duty_percent=50,wiring_confirmed=True))
        assert state['outputs'][ch-1]['enabled'] and sum(bool(o['enabled']) for o in state['outputs'])==1
    def setup(f,amp,center):
        scale=next(v for v in (.01,.02,.05,.1,.2,.5,1.) if v>=amp/5)
        scope.write(f':CHANnel{scope.channel}:SCALe {scale}');scope.scale=float(scope.ask(f':CHANnel{scope.channel}:SCALe?'))
        scope.point(f,center);pause(1)
    def measure(shape,f,label):
        nonlocal sequence
        sequence+=1;path=out/f'{sequence:04d}_{label}.npz'
        m=scope.sample(path,f,shape);m['raw_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();return m
    try:
        scope=LanScope('169.254.1.5','169.254.3.254',1);r['scope_before']=scope.prior
        assert scope.idn==base['scope_idn']
        r['connected']=agent.connect('192.168.0.4','xilinx','xilinx',ROOT/'measurements/known_hosts',
            ROOT/'data',agent_archive(ROOT/'src/python/zynq_bjt'),bitfile=base['connected']['bitfile'])
        r['initialized']=agent.call('initialize');agent.call('stop')
        assert all(r['initialized']['identity'][k]==base['initialized']['identity'][k]
                   for k in ('bit_sha256','hwh_sha256','dac_divider'))
        save()
        for ch,shape in failed:
            agent.call('stop');scope.setup(base['connection'][f'TX{ch}'],scale=.05)
            center=.9 if ch==2 else 0.
            rows=[p for p in base['verification'] if p['channel']==ch and p['shape']==shape]
            warm_point=next(p for p in rows if p['frequency_hz']==100000 and p['target_vpp_v']==.2)
            if not warm_point['amplitude_passed']:raise ValueError('Warm-up reference node failed amplitude verification')
            view_center=warm_point['measurement']['dc_v']
            setup(100000,.2,view_center);output(ch,warm_point);pause(3)
            key=f'TX{ch}_{shape}';samples=[]
            entry=dict(original_warmup=base['warmup'][key],zero_code=warm_point['zero_code'],
                peak_codes=warm_point['peak_codes'],frequency_hz=100000,target_vpp_v=.2,
                reason='original amplitude stability failed',
                scope_scale_v=scope.scale,scope_center_v=view_center,rows=samples,windows=[])
            r['stability_rechecks'][key]=entry;start=time.monotonic()
            # At most three consecutive six-reading windows. Retain all reads
            # and all failed windows rather than selecting arbitrary samples.
            for window in range(3):
                segment=[]
                while len(segment)<6 or segment[-1]['elapsed_s']-segment[0]['elapsed_s']<90:
                    pause(12);m=measure(shape,100000,key+'_warm')
                    item=dict(m,elapsed_s=time.monotonic()-start);segment.append(item);samples.append(item);save()
                    print('WARM_RECHECK',key,len(samples),m['vpp_v'],m['dc_v'],flush=True)
                check=stability(segment,.2);entry['windows'].append(dict(first=len(samples)-len(segment),count=len(segment),stability=check));save()
                if check['amplitude_stable']:break
            if not check['amplitude_stable']:raise ValueError(key+' amplitude remains unstable')
            r['warmup'][key]=dict(entry,stability=check,qualified_window=entry['windows'][-1])
            r['prior_verification'].extend(rows)
            r['verification']=[p for p in r['verification'] if not(p['channel']==ch and p['shape']==shape)]
            for row in reversed(rows):
                f,amp=row['frequency_hz'],row['target_vpp_v'];setup(f,amp,row['measurement']['dc_v']);output(ch,row);pause(3)
                m=measure(shape,f,key+'_verify');amplitude_passed=abs(m['vpp_v']-amp)<=max(.0015,.02*amp)
                dc_passed=abs(m['dc_v']-center)<=.005
                updated=dict(row,measurement=m,amplitude_error_v=m['vpp_v']-amp,amplitude_passed=amplitude_passed,
                    dc_passed=dc_passed,passed=amplitude_passed and (not base.get('center_is_acceptance_criterion',True) or dc_passed))
                r['verification'].append(updated);save();print('VERIFY_RECHECK',key,f,amp,m['vpp_v'],amplitude_passed,flush=True)
        r['status']='complete'
    except BaseException as e:r.update(status='incomplete',error=repr(e));print('STOP',repr(e),flush=True)
    finally:
        if agent.alive:
            try:
                r['stopped']=agent.call('stop');r['closed']=agent.close()
                r['cleanup_confirmed']=not any(o['enabled'] for o in r['stopped']['outputs']) and r['closed']['cleanup_confirmed']
            except Exception as e:r['cleanup_error']=repr(e);agent.abort()
        if scope:
            try:scope.restore();r['scope_restored']=True
            except Exception as e:r['scope_restore_error']=repr(e)
            finally:scope.s.close()
        r['finished']=datetime.now().astimezone().isoformat();save()
        print('DONE',r['status'],r.get('cleanup_confirmed'),flush=True)
    return 0 if r['status']=='complete' and r.get('cleanup_confirmed') else 1


if __name__=='__main__':raise SystemExit(main())
