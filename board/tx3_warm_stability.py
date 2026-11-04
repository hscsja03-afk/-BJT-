"""Bounded warm-up and 100 kHz / 70 mVpp recheck, raw evidence preserved."""
import argparse,json,math,sys,time
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'board'),str(ROOT/'src/python')]
from calibrate_tx23_scope import Scope
from tx2_scope_zero import SerialAgent
import numpy as np

ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--warm-resume',type=Path);args=ap.parse_args()
OUT=args.out.resolve();OUT.mkdir(parents=True,exist_ok=False)
assert OUT.is_relative_to(ROOT/'report')
PKG=ROOT/'build/dist/desktop_dac125_20261101/ZynqBjtDesktop/_internal'
profile=json.loads((PKG/'data/dac_calibration.json').read_text())['channels'][2]['sine_50mv']
zero=int(profile['zero_code']);peak=int(profile['peak_codes'][profile['frequency_hz'].index(100000)])
seed=None
if args.warm_resume:
 seed=json.loads(args.warm_resume.read_text(encoding='utf-8'))
 assert seed['close']['cleanup_confirmed'] and seed['final_hold_stability']['stable']
 last=seed['points'][-1];slope=seed['zero_slope_v_per_code']
 zero=round(last['zero_code']-last['measurement']['dc_v']/slope)
 peak=round(last['peak_codes']*.07/last['measurement']['vpp_v'])
r=dict(started=datetime.now(timezone(timedelta(hours=8))).isoformat(),events=[],points=[],rejected=[],
 frequency_hz=100000,target_vpp_v=.07,connection='User confirmed BJT disconnected; TX3 direct to scope CH3; USB COM7',
 bandwidth_limit='20M',scope_relative=True,passed=False,status='starting',
 criteria=dict(minimum_warm_seconds=120,window_seconds=90,vpp_spread_v=.0007,dc_spread_v=.002,
 vpp_slope_v_per_minute=.0003,dc_slope_v_per_minute=.001,final_target_error_v=.001,final_dc_abs_v=.003))
if seed:r['warm_resume_source']=str(args.warm_resume.resolve());r['zero_slope_v_per_code']=slope
a=SerialAgent('COM7','xilinx',r['events'],base=PKG);s=None;begin=time.monotonic();center=None
def save():
 (OUT/'result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
def pause(seconds):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  if (OUT/'stop.request').exists():raise InterruptedError('Stop requested')
  time.sleep(min(1,max(0,end-time.monotonic())))
def output(z,p):
 assert 16000<=z<=40000 and 100<=p<=1200
 state=a.call('output',dict(channel=2,action='start',mode='sine_code',offset=z,peak=p,
  frequency_hz=100000,phase_degrees=0,wiring_confirmed=True))
 assert state['outputs'][2]['enabled'] and all(not v['enabled'] for v in state['outputs'][:2])
 return state
def measure(stage):
 global center
 for attempt in range(3):
  try:
   if center is None:
    s.write(':CHANnel3:SCALe 0.5');s.scale=.5;s.point(100000)
    dc=s.dc(0,3)['mean_v'];assert abs(dc)<1,'DC exceeds 1 V bound'
    center=round(dc,5);s.write(':CHANnel3:SCALe 0.02');s.scale=.02;s.point(100000,center);pause(.7)
   else:
    s.write(':RUN');pause(.4)
    dc=float(s.ask(':MEASure:ITEM? VAVG,CHANnel3'))
    if not math.isfinite(dc) or abs(dc-center)>.035:
     center=None;continue
   m=s.capture(OUT/('p{:04d}_a{}.npz'.format(len(r['points']),attempt)),100000)
   assert .015<m['vpp_v']<.25 and abs(m['dc_v'])<1,'Waveform outside experiment bounds'
   m['scope_offset_v']=float(s.ask(':CHANnel3:OFFSet?'));m['scope_scale_v']=s.scale
   row=dict(elapsed_s=time.monotonic()-begin,stage=stage,zero_code=zero,peak_codes=peak,measurement=m)
   r['points'].append(row);s.write(':RUN');save()
   print(json.dumps(dict(stage=stage,t=round(row['elapsed_s'],1),zero=zero,peak=peak,
    vpp_mV=round(m['vpp_v']*1000,4),dc_mV=round(m['dc_v']*1000,4))),flush=True)
   return row
  except AssertionError as e:
   r['rejected'].append(dict(stage=stage,error=str(e)));save();center=None
   if attempt==2:raise
 raise RuntimeError('Could not acquire unclipped waveform')
def stability(rows):
 window=[p for p in rows if p['elapsed_s']>=rows[-1]['elapsed_s']-110]
 if len(window)<5 or window[-1]['elapsed_s']-window[0]['elapsed_s']<90:return dict(stable=False,samples=len(window))
 t=np.array([p['elapsed_s'] for p in window]);t-=t.mean()
 values={key:np.array([p['measurement'][key] for p in window]) for key in ('vpp_v','dc_v')}
 stats={key:dict(mean=float(v.mean()),spread=float(np.ptp(v)),slope_per_minute=float(np.polyfit(t,v,1)[0]*60)) for key,v in values.items()}
 stable=stats['vpp_v']['spread']<=.0007 and stats['dc_v']['spread']<=.002 and abs(stats['vpp_v']['slope_per_minute'])<=.0003 and abs(stats['dc_v']['slope_per_minute'])<=.001
 return dict(stable=bool(stable),samples=len(window),span_s=float(np.ptp(t)),**stats)
def hold(stage,minimum,maximum,target=False):
 start=time.monotonic();rows=[]
 while time.monotonic()-start<maximum:
  rows.append(measure(stage));stats=stability(rows);r[stage+'_stability']=stats;save()
  if time.monotonic()-start>=minimum and stats['stable']:
   if not target or all(abs(p['measurement']['vpp_v']-.07)<=.001 and abs(p['measurement']['dc_v'])<=.003 for p in rows[-5:]):return rows
  pause(15)
 raise RuntimeError(stage+' did not meet stability/target criteria within '+str(maximum)+' seconds')
def trim_hot():
 global zero,peak
 r['status']='final_hold';save()
 for cycle in range(3):
  stage='final_hold' if cycle==0 else 'final_hold_'+str(cycle)
  rows=[];start=time.monotonic()
  while time.monotonic()-start<300:
   row=measure(stage);rows.append(row);stats=stability(rows);r[stage+'_stability']=stats;save()
   if time.monotonic()-start>=180 and stats['stable']:
    if all(abs(p['measurement']['vpp_v']-.07)<=.001 and abs(p['measurement']['dc_v'])<=.003 for p in rows[-5:]):
     r['final_hold_stability']=stats;return rows
    break
   pause(15)
  assert stats['stable'],'Warm resume did not stabilize'
  zero=round(zero-stats['dc_v']['mean']/slope);peak=round(peak*.07/stats['vpp_v']['mean'])
  output(zero,peak);pause(20)
 raise RuntimeError('Residual zero did not meet target after three bounded holds')
try:
 s=Scope();r.update(scope_idn=s.idn,scope_before=s.prior)
 r['connected']=a.connect();r['initialized']=a.call('initialize',timeout=120)
 assert r['initialized']['identity']['dac_divider']==8 and r['initialized']['identity']['adc_divider']==20
 assert all(not v['enabled'] for v in r['initialized']['outputs'])
 s.setup(3,sine=True,scale=.5);s.write(':CHANnel3:BWLimit 20M')
 assert s.ask(':CHANnel3:BWLimit?')=='20M'
 r['initial_output']=output(zero,peak);r['status']='warming';save()
 if seed:
  assert seed['initialized']['identity']['bit_sha256']==r['initialized']['identity']['bit_sha256']
  checks=trim_hot()
 else:
  warm=hold('warm',120,600)
  r['status']='adjusting';save()
  base=warm[-1]['measurement']['dc_v'];original_zero=zero
  zero+=256;output(zero,peak);pause(15);shift=measure('zero_probe')['measurement']['dc_v']
  zero=original_zero;output(zero,peak);pause(15);back=measure('zero_return')['measurement']['dc_v']
  assert abs(back-base)<.003,'Baseline moved during zero slope measurement'
  slope=(shift-(base+back)/2)/256;assert .00002<slope<.0002,'Invalid local zero-code slope'
  r['zero_slope_v_per_code']=slope
  for i in range(4):
   last=r['points'][-1]['measurement']
   zero=round(zero-last['dc_v']/slope);peak=round(peak*.07/last['vpp_v'])
   output(zero,peak);pause(20);last=measure('adjust'+str(i))['measurement']
   if abs(last['vpp_v']-.07)<.0005 and abs(last['dc_v'])<.0015:break
  r['status']='final_hold';save();checks=hold('final_hold',180,360,target=True)
 r['verified_setting']=dict(frequency_hz=100000,zero_code=zero,peak_codes=peak,
  dac_sample_rate_hz=125000000,scope_bandwidth=s.ask(':CHANnel3:BWLimit?'),
  qualification='100 kHz only, warmed, scope-relative; other frequencies and cold-start repeatability unverified')
 from read_scope import read_scope
 r['screen']=read_scope('169.254.1.5',3,OUT/'scope_final','TX3 100kHz 70mVpp warmed stability check; 20MHz bandwidth',s.s)
 r['passed']=True;r['status']='complete'
except BaseException as e:
 r['error']=repr(e);r['status']='incomplete';print('STOP',repr(e),flush=True)
finally:
 try:r['close']=a.close()
 except Exception as e:r['close_error']=repr(e)
 if s:
  try:s.write(':CHANnel3:BWLimit 20M');s.write(':RUN');r['bandwidth_readback']=s.ask(':CHANnel3:BWLimit?')
  except Exception as e:r['scope_close_error']=repr(e)
  s.s.close()
 r['finished']=datetime.now(timezone(timedelta(hours=8))).isoformat();save()
print('DONE',json.dumps(dict(passed=r['passed'],status=r['status'],close=r.get('close'),error=r.get('error'))),flush=True)
