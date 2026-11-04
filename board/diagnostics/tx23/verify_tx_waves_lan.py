"""Independent physical check of the same voltage plans used by the desktop."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

from board.calibration.tx.calibrate_tx_waves_lan import LanScope, ROOT
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.desktop_output import prepare
from zynq_bjt.desktop_transport import SshTransport,agent_archive
from zynq_bjt.frontend import Calibration


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--probe',type=int,choices=(1,10),required=True)
    ap.add_argument('--amplitude-only',action='store_true')
    ap.add_argument('--tx2-scope-channel',type=int,choices=(1,2,3,4),default=3)
    ap.add_argument('--tx3-scope-channel',type=int,choices=(1,2,3,4),default=4)
    ap.add_argument('--bitfile',default='/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit')
    args=ap.parse_args()
    if args.tx2_scope_channel==args.tx3_scope_channel:ap.error('Select distinct scope channels')
    scope_channels={1:args.tx2_scope_channel,2:args.tx3_scope_channel}
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    r=dict(started=datetime.now().astimezone().isoformat(),status='starting',checks=[],scope_relative=True)
    r['connection']={f'TX{k+1}':v for k,v in scope_channels.items()}
    r['center_is_acceptance_criterion']=not args.amplitude_only
    cal=Calibration(ROOT/'data');agent=SshTransport();scope=None
    def save():(out/'result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
    try:
        scope=LanScope('169.254.1.5','169.254.3.254',args.probe)
        r['scope_idn']=scope.idn;r['scope_before']=scope.prior
        r['connected']=agent.connect('192.168.0.4','xilinx','xilinx',ROOT/'measurements/known_hosts',
            ROOT/'data',agent_archive(ROOT/'src/python/zynq_bjt'),
            bitfile=args.bitfile)
        r['initialized']=agent.call('initialize')
        r['data_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in cal.paths}
        for channel in (1,2):
            agent.call('stop');scope.setup(scope_channels[channel],scale=.05)
            for shape in ('sine','square','triangle'):
                center=.9 if channel==1 else 0.
                plan=prepare(channel,shape,'voltage',dict(offset=center,peak=.1,frequency_hz=100000,
                    phase_degrees=0,duty_percent=50),cal,confirmed=True,action='start')
                view_center=center
                if args.amplitude_only:
                    profile=cal.tx2_waveforms if channel==1 else cal.tx3_waveforms
                    reference=next(p for p in profile['points'] if p['shape']==shape and p['frequency_hz']==100000 and p['target_vpp_v']==.2)
                    view_center=reference['measurement']['dc_v']
                scope.point(100000,view_center)
                status=agent.call('output',plan['request'])
                time.sleep(3)
                path=out/f'tx{channel+1}_{shape}.npz'
                m=scope.sample(path,100000,shape)
                m['raw_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                ok=abs(m['vpp_v']-.2)<=.004 and (args.amplitude_only or abs(m['dc_v']-center)<=.02)
                r['checks'].append(dict(channel=channel+1,shape=shape,request=plan['request'],
                    status=status,measurement=m,amplitude_passed=abs(m['vpp_v']-.2)<=.004,
                    dc_passed=abs(m['dc_v']-center)<=.005,passed=ok))
                save();print('RELEASE_CHECK',channel+1,shape,m['vpp_v'],m['dc_v'],ok,flush=True)
        r['status']='complete';r['passed']=len(r['checks'])==6 and all(x['passed'] for x in r['checks'])
    except BaseException as error:
        r.update(status='incomplete',error=repr(error),passed=False)
    finally:
        if agent.alive:
            try:
                r['stopped']=agent.call('stop');r['closed']=agent.close()
                r['cleanup_confirmed']=not any(x['enabled'] for x in r['stopped']['outputs'])
            except Exception as error:r['cleanup_error']=repr(error);agent.abort()
        if scope:
            try:scope.restore();r['scope_restored']=True
            except Exception as error:r['scope_restore_error']=repr(error)
            finally:scope.s.close()
        r['finished']=datetime.now().astimezone().isoformat();save()
        print('DONE',r['status'],r.get('passed'),r.get('cleanup_confirmed'),flush=True)
    return 0 if r.get('passed') and r.get('cleanup_confirmed') else 1


if __name__=='__main__':raise SystemExit(main())
