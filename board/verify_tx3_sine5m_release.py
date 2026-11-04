"""Verify installed output conversion at grid and independent interpolation points."""
import argparse,json,sys,time,hashlib
from pathlib import Path
from calibrate_tx3_multi import SlowScope
from tx2_scope_zero import ROOT,SerialAgent
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration
from zynq_bjt.desktop_output import prepare
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
r=dict(events=[],points=[],amplitude_passed=False,dc_passed=False,passed=False)
a=SerialAgent('COM7','xilinx',r['events'],base=args.base);s=None
class Scope(SlowScope):
 def call(self,method,value):
  time.sleep(max(0,.4-(time.monotonic()-self.last)))
  return super().call(method,value)
def save():(out/'result.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf8')
try:
 cal=Calibration(args.base/'data');s=Scope();r['scope_idn']=s.idn
 r['connected']=a.connect();r['initialized']=a.call('initialize',timeout=120)
 assert r['initialized']['identity']['dac_divider']==8
 s.setup(3,sine=True,scale=.1);assert s.ask(':CHANnel3:BWLimit?')=='OFF'
 plan=[('sine',f,amp) for f in (10000,1000000,5000000) for amp in (.07,.5)]
 plan += [('sine',f,.1) for f in (3250000,3750000,4250000,4750000)]
 plan += [(shape,100000,.07) for shape in ('square','triangle')]
 for i,(shape,f,amp) in enumerate(plan):
  request=prepare(2,shape,'voltage',dict(offset=0,peak=amp/2,frequency_hz=f,phase_degrees=0,duty_percent=50),cal,confirmed=True,action='start')['request']
  state=a.call('output',request,timeout=60)
  assert state['outputs'][2]['enabled'] and not any(x['enabled'] for x in state['outputs'][:2])
  expected=cal.waveform_parameters(shape,f,amp)['amplitude_basis']
  assert state['output_settings']['2']['sine_amplitude_basis']==expected
  scale=next(v for v in (.01,.02,.05,.1,.2) if v>=amp/5)
  s.write(f':CHANnel3:SCALe {scale}');s.scale=scale;s.point(f);time.sleep(3)
  repeats=[]
  for rep in range(3):
   for retry in range(3):
    path=out/f'{i:02d}_{rep}_{retry}.npz'
    try:m=s.sample(path,f,shape);break
    except (ValueError,AssertionError) as exc:
     r.setdefault('rejected',[]).append(dict(file=path.name,error=str(exc)));save()
     if retry==2:raise
     s.write(f':CHANnel3:SCALe {scale*2}');s.write(f':CHANnel3:SCALe {scale}');s.point(f);time.sleep(3)
   m['raw_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();repeats.append(m);time.sleep(1)
  m=dict(vpp_v=sum(x['vpp_v'] for x in repeats)/3,dc_v=sum(x['dc_v'] for x in repeats)/3,
   vpp_spread_v=max(x['vpp_v'] for x in repeats)-min(x['vpp_v'] for x in repeats))
  limit=max(.0015,.02*amp)
  amp_ok=all(abs(x['vpp_v']-amp)<=limit for x in repeats) and m['vpp_spread_v']<=limit
  dc_ok=all(abs(x['dc_v'])<=.005 for x in repeats)
  r['points'].append(dict(shape=shape,frequency_hz=f,target_vpp_v=amp,measurement=m,request=request,state=state,
   repeats=repeats,amplitude_passed=amp_ok,dc_passed=dc_ok,passed=amp_ok and dc_ok))
  print('RELEASE',shape,f,amp,round(m['vpp_v'],6),round(m['dc_v'],6),amp_ok,dc_ok,flush=True);save()
 r['amplitude_passed']=all(x['amplitude_passed'] and abs(x['measurement']['dc_v'])<=.02 for x in r['points'])
 r['dc_passed']=all(x['dc_passed'] for x in r['points']);r['passed']=r['amplitude_passed'] and r['dc_passed']
except BaseException as exc:r['error']=repr(exc);print('STOP',repr(exc),flush=True)
finally:
 try:r['close']=a.close()
 except Exception as exc:r['close_error']=repr(exc)
 if s:
  try:s.write(':RUN');s.s.close()
  except Exception as exc:r['scope_close_error']=repr(exc)
 save()
raise SystemExit(0 if r['amplitude_passed'] and r.get('close',{}).get('cleanup_confirmed') else 1)
