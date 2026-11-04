"""DAC125 TX3 sine grid, bounded correction and independent reverse check."""
import argparse,copy,json,math,sys,time,hashlib,shutil
from datetime import datetime
from pathlib import Path
import numpy as np
from calibrate_tx3_multi import SlowScope
from tx2_scope_zero import ROOT,SerialAgent
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration

ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--resume',type=Path)
ap.add_argument('--other-waves',action='store_true');ap.add_argument('--seed',type=Path)
ap.add_argument('--stable-warm',action='store_true')
ap.add_argument('--unstable-reference',type=Path,help='Characterize other waveforms after a documented failed warm-up; does not qualify stability')
ap.add_argument('--standalone-confirmed',action='store_true')
args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
if not args.standalone_confirmed:ap.error('Standalone calibration requires confirmed TX3-to-scope-only wiring')
unstable_reference=None
if args.unstable_reference:
 assert args.other_waves and not args.resume
 unstable_reference=json.loads(args.unstable_reference.read_text(encoding='utf8'))
 assert unstable_reference.get('standalone_tx3_calibration_eligible') is True and unstable_reference['close']['cleanup_confirmed']
 assert 'Fixed-code warm-up did not stabilize' in unstable_reference.get('error','')
 assert not unstable_reference['warm_stability']['amplitude_stable']
 assert 0 <= time.time()-datetime.fromisoformat(unstable_reference['finished']).timestamp() < 1800
base=ROOT/'build/dist/desktop_adc625_20261102/ZynqBjtDesktop/_internal'
freqs=[10000,100000,500000,1000000,2000000,3000000,3500000,4000000,4500000,5000000]
amps=[.05,.07,.1,.2,.5]
shapes=['square','triangle'] if args.other_waves else ['sine']
if args.other_waves:freqs=[10000,100000,1000000]
r=dict(started=datetime.now().astimezone().isoformat(),status='starting',passed=False,events=[],points=[],verification=[],
 frequencies_hz=freqs,amplitudes_vpp=amps,shapes=shapes,connection='User confirmed TX3 direct to DS1104Z CH3, high impedance, DC x1',
 scope_relative=True,scope_bandwidth='OFF',instrument_command_gap_s=.4,
 criteria=dict(amplitude_error_v_floor=.0015,amplitude_relative_error=.02,dc_abs_v=.005,dc_reference_bound_v=.02,
 warm_minimum_s=120,warm_window_s=90,warm_vpp_spread_v=.0007,warm_dc_spread_v=.002))
r['standalone_tx3_calibration_eligible']=True
if unstable_reference:
 r['qualification']='reference_only_unstable_warmup'
 r['unstable_warm_reference']=dict(source=str(args.unstable_reference),sha256=hashlib.sha256(args.unstable_reference.read_bytes()).hexdigest(),
  warm_stability=unstable_reference['warm_stability'],criteria=unstable_reference['criteria'])
if args.resume:
 prior=json.loads(args.resume.read_text(encoding='utf8'))
 assert prior.get('close',{}).get('cleanup_confirmed')
 assert prior.get('standalone_tx3_calibration_eligible') is True
 bad={(v['shape'],v['frequency_hz'],v['target_vpp_v']) for v in prior['verification'] if not v.get('amplitude_passed') or abs(v['measurement']['dc_v'])>.02}
 r['points']=[copy.deepcopy(p) for p in prior['points'] if p.get('adjusted') and
  (p['shape'],p['frequency_hz'],p['target_vpp_v']) not in bad]
 r['resume_source']=str(args.resume.resolve())
backup=out/'data_before';backup.mkdir()
for name in ('dac_calibration.json','tx3_waveform_calibration.json'):shutil.copy2(ROOT/'data'/name,backup/name)
cal=Calibration(ROOT/'data');a=SerialAgent('COM7','xilinx',r['events'],base=base);s=None;serial_no=0
def seed_plan(f,amp):
 if args.resume:
  match=[x for x in prior['points'] if x['shape']=='sine' and x['frequency_hz']==f and x['target_vpp_v']==amp and x.get('adjusted')]
  if match:return dict(zero_code=match[0]['zero_code'],peak_codes=match[0]['peak_codes'])
 if not args.seed:return cal.sine_parameters(f,amp)
 from zynq_bjt.waveform_reference import resolve
 seed=json.loads(args.seed.read_text(encoding='utf8'));assert seed['amplitude_passed'] and seed['close']['cleanup_confirmed'] and seed.get('standalone_tx3_calibration_eligible') is True
 return resolve(dict(points=seed['verification'],dac_sample_rate_hz=125000000,calibration_id='seed',
  shape_validation={'sine':{'amplitude_only':True}}),'sine',f,amp)
class Scope(SlowScope):
 def call(self,method,value):
  time.sleep(max(0,.4-(time.monotonic()-self.last)))
  try:
   answer=getattr(self.s,method)(value)
   with (out/'scope_commands.jsonl').open('a',encoding='utf8') as log:
    log.write(json.dumps(dict(at=time.time(),method=method,command=value.decode() if isinstance(value,bytes) else value,
     response=('binary '+str(len(answer))+' bytes') if isinstance(answer,bytes) else answer))+'\n')
   return answer
  finally:self.last=time.monotonic()
def save():(out/'result.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf8')
def pause(seconds):
 until=time.monotonic()+seconds
 while time.monotonic()<until:
  if (out/'stop.request').exists():raise InterruptedError('Stop requested')
  time.sleep(min(.5,max(0,until-time.monotonic())))
def output(f,z,p,shape='sine'):
 assert 6000<=z<=38000 and 80<=p<=6000 and 0<=z-p<z+p<=65535
 status=a.call('output',dict(channel=2,action='start',mode=shape+'_code',frequency_hz=f,offset=z,peak=p,
  phase_degrees=0,wiring_confirmed=True),timeout=60)
 assert status['outputs'][2]['enabled'] and not any(x['enabled'] for x in status['outputs'][:2])
 return status
def setup(f,amp):
 scale=next(v for v in (.01,.02,.05,.1,.2) if v>=amp/5)
 s.write(f':CHANnel3:SCALe {scale}');s.scale=scale;s.point(f);pause(2)
def measure(f,label,shape='sine'):
 global serial_no
 for attempt in range(3):
  serial_no+=1;path=out/f'{serial_no:04d}_{label}.npz'
  try:
   m=s.sample(path,f,shape)
   assert .005<m['vpp_v']<1 and abs(m['dc_v'])<.25,'Unexpected amplitude or DC center'
   m.update(raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),scope_bandwidth='OFF',scope_scale_v=s.scale)
   return m
  except (ValueError,AssertionError) as exc:
   r.setdefault('rejected',[]).append(dict(file=str(path),reason=str(exc)));save()
   if attempt==2:raise
   s.write(f':CHANnel3:SCALe {s.scale*2}');s.write(f':CHANnel3:SCALe {s.scale}');s.point(f);pause(3)
def amplitude_passes(m,amp):return abs(m['vpp_v']-amp)<=max(.0015,.02*amp)
def passes(m,amp):return amplitude_passes(m,amp) and abs(m['dc_v'])<=.005
def measure_dc(label):
 global serial_no
 # Instrument auto VMAX occasionally returns its invalid sentinel for DC.
 # Use a frozen waveform and its scale metadata instead of that reading.
 s.write(':RUN');pause(3);s.write(':STOP');assert s.ask(':TRIGger:STATus?')=='STOP'
 s.write(':WAVeform:MODE RAW');s.write(':WAVeform:STARt 1');s.write(':WAVeform:STOP 12000')
 pre=[float(v) for v in s.ask(':WAVeform:PREamble?').split(',')]
 block=s.ask_raw(b':WAVeform:DATA?');assert block[:1]==b'#'
 digits=int(block[1:2]);count=int(block[2:2+digits]);raw=np.frombuffer(block[2+digits:2+digits+count],dtype=np.uint8).copy()
 rate=float(s.ask(':ACQuire:SRATe?'));serial_no+=1;path=out/f'{serial_no:04d}_{label}.npz'
 np.savez_compressed(path,raw=raw,preamble=pre,sample_rate_hz=rate)
 assert len(raw)==12000 and abs(pre[4]*rate-1)<1e-5 and raw.min()>2 and raw.max()<253
 assert s.scale*.005<pre[7]<s.scale*.2
 values=(raw.astype(float)-pre[8]-pre[9])*pre[7]
 return dict(mean_v=float(values.mean()),std_v=float(values.std()),min_v=float(values.min()),max_v=float(values.max()),
  raw_file=str(path.relative_to(ROOT)),raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),scale_v=s.scale)
try:
 s=Scope();r['scope_idn']=s.idn;r['scope_before']=s.prior
 r['connected']=a.connect();r['initialized']=a.call('initialize',timeout=120)
 assert r['initialized']['identity']['dac_divider']==8 and not any(x['enabled'] for x in r['initialized']['outputs'])
 if unstable_reference:
  assert r['scope_idn']==unstable_reference['scope_idn']
  assert r['initialized']['identity']['bit_sha256']==unstable_reference['initialized']['identity']['bit_sha256']
 s.setup(3,sine=True,scale=1.0);assert s.ask(':CHANnel3:BWLimit?')=='OFF'
 warm_amp=.5 if args.stable_warm else .07
 minimum,maximum,span_required,window_s=(240,900,180,240) if args.stable_warm else (120,360,90,120)
 amp_spread,amp_slope=(.001,.000125) if args.stable_warm else (.0007,.0003)
 r['criteria'].update(warm_minimum_s=minimum,warm_maximum_s=maximum,warm_window_s=span_required,
  warm_vpp_spread_v=amp_spread,warm_vpp_slope_v_per_minute=amp_slope,warm_target_vpp=warm_amp)
 plan=seed_plan(100000,warm_amp);z=round(plan['zero_code']);p=round(plan['peak_codes'])
 r['zero_probe']=[]
 for code in (z-1000,z+1000,z):
  a.call('output',dict(channel=2,action='start',mode='dc_code',offset=code,wiring_confirmed=True));pause(3)
  m=measure_dc('zero_probe');assert abs(m['mean_v'])<2
  r['zero_probe'].append(dict(code=code,measurement=m));save()
 slope=(r['zero_probe'][1]['measurement']['mean_v']-r['zero_probe'][0]['measurement']['mean_v'])/2000
 assert .00003<slope<.0003
 z=round(z-r['zero_probe'][-1]['measurement']['mean_v']/slope)
 r['zero_slope_v_per_code']=slope
 a.call('output',dict(channel=2,action='start',mode='dc_code',offset=z,wiring_confirmed=True));pause(4)
 s.write(':CHANnel3:SCALe 0.1');s.scale=.1
 center=measure_dc('zero_center');r['zero_center_check']=dict(code=z,measurement=center);save()
 z=round(z-center['mean_v']/slope)
 setup(100000,warm_amp);output(100000,z,p);r['warmup']=[];r['status']='warming';save();begin=time.monotonic()
 while True:
  m=measure(100000,'warm');elapsed=time.monotonic()-begin;r['warmup'].append(dict(elapsed_s=elapsed,measurement=m,zero_code=z,peak_codes=p))
  window=[x for x in r['warmup'] if x['elapsed_s']>=elapsed-window_s]
  span=window[-1]['elapsed_s']-window[0]['elapsed_s']
  t=np.array([x['elapsed_s'] for x in window]);t-=t.mean()
  stats={key:dict(spread=float(np.ptp([x['measurement'][key] for x in window])),
   slope_per_minute=float(np.polyfit(t,[x['measurement'][key] for x in window],1)[0]*60) if len(window)>1 else None) for key in ('vpp_v','dc_v')}
  stable=len(window)>=5 and span>=span_required and stats['vpp_v']['spread']<=amp_spread and stats['dc_v']['spread']<=.002
  stable=stable and abs(stats['vpp_v']['slope_per_minute'])<=amp_slope and abs(stats['dc_v']['slope_per_minute'])<=.001
  amplitude_stable=len(window)>=5 and span>=span_required and stats['vpp_v']['spread']<=amp_spread and abs(stats['vpp_v']['slope_per_minute'])<=amp_slope
  r['warm_stability']=dict(stable=stable,amplitude_stable=amplitude_stable,span_s=span,samples=len(window),**stats);save()
  print('WARM',round(elapsed),round(m['vpp_v'],6),round(m['dc_v'],6),stable,flush=True)
  if unstable_reference:
   r['warm_stability']['qualification']='not_qualified; previous bounded warm-up failed; this is only a pre-sweep probe'
   save();break
  if elapsed>=minimum and amplitude_stable:break
  if elapsed>=maximum:raise RuntimeError('Fixed-code warm-up did not stabilize within bounded time')
  pause(12)
 warm_zero=z-m['dc_v']/slope;r['status']='calibrating';save()
 for shape in shapes:
  for f,amp in [(f,amp) for f in freqs for amp in amps]:
   if any(x['shape']==shape and x['frequency_hz']==f and x['target_vpp_v']==amp and x.get('adjusted') for x in r['points']):continue
   seed=seed_plan(f,amp);z=round(warm_zero);p=round(seed['peak_codes']);setup(f,amp)
   row=dict(shape=shape,frequency_hz=f,target_vpp_v=amp,attempts=[],adjusted=False);r['points'].append(row)
   for attempt in range(4):
    output(f,z,p,shape);pause(3);m=measure(f,'adjust',shape)
    row['attempts'].append(dict(zero_code=z,peak_codes=p,measurement=m));save()
    if abs(m['vpp_v']-amp)<=max(.0008,.008*amp) and abs(m['dc_v'])<=(.002 if attempt==0 else .02):break
    if attempt<3:z=round(z-m['dc_v']/slope);p=round(p*amp/m['vpp_v'])
   row.update(zero_code=z,peak_codes=p,adjusted=amplitude_passes(m,amp) and abs(m['dc_v'])<=.02)
   print('CAL',shape,f,amp,round(m['vpp_v'],6),round(m['dc_v'],6),row['adjusted'],flush=True);save()
   if not row['adjusted']:raise RuntimeError('Bounded calibration did not converge')
 r['status']='verifying';save()
 for row in reversed(r['points']):
  f,amp,shape=row['frequency_hz'],row['target_vpp_v'],row['shape'];setup(f,amp);output(f,row['zero_code'],row['peak_codes'],shape);pause(4)
  m=measure(f,'verify',shape);ok=passes(m,amp)
  r['verification'].append(dict(shape=shape,frequency_hz=f,target_vpp_v=amp,zero_code=row['zero_code'],peak_codes=row['peak_codes'],
   measurement=m,amplitude_error_v=m['vpp_v']-amp,passed=ok,amplitude_passed=amplitude_passes(m,amp),dc_passed=abs(m['dc_v'])<=.005))
  print('VERIFY',f,amp,round(m['vpp_v'],6),round(m['dc_v'],6),ok,flush=True);save()
 r['amplitude_passed']=len(r['verification'])==len(shapes)*len(freqs)*len(amps) and all(x['amplitude_passed'] and abs(x['measurement']['dc_v'])<=.02 for x in r['verification'])
 r['dc_passed']=r['warm_stability']['stable'] and all(x['dc_passed'] for x in r['verification'])
 r['passed']=r['amplitude_passed'] and r['dc_passed'];r['status']='complete'
except BaseException as exc:r['error']=repr(exc);r['status']='incomplete';print('STOP',repr(exc),flush=True)
finally:
 try:r['close']=a.close()
 except Exception as exc:r['close_error']=repr(exc)
 if s:
  try:s.write(':RUN');s.s.close()
  except Exception as exc:r['scope_close_error']=repr(exc)
 r['finished']=datetime.now().astimezone().isoformat();save();print('DONE',r['status'],r['passed'],r.get('close'),flush=True)
raise SystemExit(0 if r.get('amplitude_passed') and r.get('close',{}).get('cleanup_confirmed') else 1)
