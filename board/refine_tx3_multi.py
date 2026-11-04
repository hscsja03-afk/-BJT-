"""仅重调超限点，保留首次复测，并对修正后码值连续三次复验。"""
import argparse,copy,json,time
from datetime import datetime
from pathlib import Path
import numpy as np
from calibrate_tx3_multi import SlowScope
from tx2_scope_zero import ROOT,SerialAgent
ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('--out',type=Path,required=True)
args=ap.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
r=json.loads(args.source.read_text(encoding='utf-8'))
assert r['status']=='complete' and r['close']['cleanup_confirmed']
r['initial_verification']=copy.deepcopy(r['verification']);r['refine_source']=str(args.source.resolve())
r['refinement']=[];r['passed']=False;r['status']='refining';r['events']=[]
r.pop('close',None);s=None;a=SerialAgent('COM7','xilinx',r['events'],base=ROOT/'build/dist/desktop_pnp_input_table_manuals_20261101/ZynqBjtDesktop/_internal')
counter=0
def save():(out/'result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
def output(row,z,p):
 if not 6000<=z<=38000 or not 100<=p<=6000:raise ValueError('Code bounds')
 a.call('output',dict(channel=2,action='start',mode=row['shape']+'_code',offset=z,peak=p,
        frequency_hz=row['frequency_hz'],phase_degrees=0,duty_percent=50,wiring_confirmed=True))
def measure(row,label):
 global counter
 for retry in range(3):
  counter+=1
  try:return s.sample(out/f'{counter:03d}_{label}.npz',row['frequency_hz'],row['shape'])
  except ValueError as error:
   r.setdefault('rejected_refine',[]).append(str(error));save()
   if retry==2:raise
   time.sleep(3)
try:
 s=SlowScope();r['refine_connected']=a.connect();r['refine_initialized']=a.call('initialize',timeout=120)
 s.setup(3,sine=True,scale=.1);s.write(':CHANnel3:BWLimit 20M')
 for row in r['verification']:
  if row['passed']:continue
  amp=row['target_vpp_v'];z=row['zero_code'];p=row['peak_codes']
  scale=next(v for v in (.01,.02,.05,.1,.2,.5) if v>=amp/5)
  s.write(f':CHANnel3:SCALe {scale}');s.scale=scale;s.point(row['frequency_hz'])
  record=dict(shape=row['shape'],frequency_hz=row['frequency_hz'],target_vpp_v=amp,adjustments=[])
  r['refinement'].append(record)
  for attempt in range(3):
   output(row,z,p);time.sleep(5);m=measure(row,'adjust')
   record['adjustments'].append(dict(zero_code=z,peak_codes=p,measurement=m));save()
   if abs(m['dc_v'])<.0015 and abs(m['vpp_v']-amp)<max(.0007,.008*amp):break
   z=round(z-m['dc_v']/r['zero_slope_v_per_code']);p=round(p*amp/m['vpp_v'])
  output(row,z,p);time.sleep(8)
  repeats=[]
  for i in range(3):
   repeats.append(measure(row,'verify'));time.sleep(4)
  row['previous_verification']=copy.deepcopy(row)
  row['zero_code']=z;row['peak_codes']=p;row['repeat_validation']=repeats
  row['measurement']=dict(vpp_v=float(np.mean([m['vpp_v'] for m in repeats])),
                          dc_v=float(np.mean([m['dc_v'] for m in repeats])),metric=repeats[0]['metric'],
                          raw_file=repeats[-1]['raw_file'],raw_files=[m['raw_file'] for m in repeats])
  row['amplitude_error_v']=row['measurement']['vpp_v']-amp
  row['passed']=all(abs(m['vpp_v']-amp)<=max(.0015,.02*amp) and abs(m['dc_v'])<=.005 for m in repeats)
  record['passed']=row['passed'];save();print('REFINED',record['shape'],record['frequency_hz'],amp,row['measurement'],row['passed'],flush=True)
 r['status']='complete';r['passed']=all(row['passed'] for row in r['verification'])
except BaseException as error:r['status']='incomplete';r['refine_error']=repr(error);print('STOP',repr(error),flush=True)
finally:
 try:r['close']=a.close()
 except Exception as error:r['close_error']=repr(error)
 if s:
  try:s.write(':RUN');s.s.close()
  except Exception as error:r['scope_close_error']=repr(error)
 r['finished']=datetime.now().astimezone().isoformat();save();print('DONE',r['passed'],r.get('close'),flush=True)
raise SystemExit(0 if r['passed'] and r.get('close',{}).get('cleanup_confirmed') else 1)
