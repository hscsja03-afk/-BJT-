"""发行版真实输出路径复测，含RAW/屏幕幅度交叉检查。"""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse,json,sys,time
from pathlib import Path
from board.calibration.tx.calibrate_tx3_multi import SlowScope
from board.instruments.tx2_scope_zero import ROOT, SerialAgent
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration
from zynq_bjt.desktop_output import prepare

ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--bitfile')
args=ap.parse_args();out=args.out.resolve();out.mkdir(exist_ok=False,parents=True)
r=dict(events=[],points=[],passed=False);s=None;a=SerialAgent('COM7','xilinx',r['events'],base=args.base,bitfile=args.bitfile)
def save():(out/'result.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8')
try:
 cal=Calibration(args.base/'data')
 if not cal.tx3_waveforms:raise RuntimeError('Missing multi-point table')
 s=SlowScope();r['scope_idn']=s.idn;r['connected']=a.connect();r['initialize']=a.call('initialize',timeout=120)
 s.setup(3,sine=True,scale=.1);s.write(':CHANnel3:BWLimit 20M')
 for shape in ('sine','square','triangle'):
  for amp in (.05,.07,.1,.2,.5):
   plan=prepare(2,shape,'voltage',dict(offset=0,peak=amp/2,frequency_hz=100000,phase_degrees=0,duty_percent=50),cal,confirmed=True,action='start')
   r['state']=a.call('output',plan['request'])
   assert r['state']['output_settings']['2']['sine_amplitude_basis']=='scope_verified_grid'
   assert r['state']['outputs'][2]['enabled'] and not any(v['enabled'] for v in r['state']['outputs'][:2])
   scale=next(v for v in (.01,.02,.05,.1,.2,.5) if v>=amp/5)
   s.write(f':CHANnel3:SCALe {scale}');s.scale=scale;s.point(100000);time.sleep(3)
   for attempt in range(3):
    try:
     m=s.sample(out/f'{shape}_{amp}_{attempt}.npz',100000,shape);break
    except ValueError as error:
     r.setdefault('rejected',[]).append(str(error));save()
     if attempt==2:raise
     time.sleep(3)
   passed=abs(m['vpp_v']-amp)<=max(.0015,amp*.02) and abs(m['dc_v'])<=.005
   r['points'].append(dict(shape=shape,target_vpp_v=amp,measurement=m,passed=passed))
   print('RELEASE',shape,amp,round(m['vpp_v'],6),round(m['dc_v'],6),passed,flush=True);save()
 r['passed']=all(p['passed'] for p in r['points'])
except BaseException as error:r['error']=repr(error);print('STOP',repr(error),flush=True)
finally:
 try:r['close']=a.close()
 except Exception as error:r['close_error']=repr(error)
 if s:
  try:s.write(':RUN');s.s.close()
  except Exception as error:r['scope_close_error']=repr(error)
 save();print('DONE',r['passed'],r.get('close'),flush=True)
raise SystemExit(0 if r['passed'] and r.get('close',{}).get('cleanup_confirmed') else 1)
