"""Compare physical ADC clock settings with real generator sine and square input."""
import argparse,json,math,sys,time
from pathlib import Path
from tx2_scope_zero import SerialAgent,ROOT
from calibrate_rx1_generator import Generator
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.scope_display import spectrum
from zynq_bjt.frontend import Calibration

ap=argparse.ArgumentParser();ap.add_argument('--divider',type=int,required=True);ap.add_argument('--bitfile',required=True);args=ap.parse_args()
out=ROOT/'report/adc_rate_raise_20261102'/('hardware_div'+str(args.divider));out.mkdir(exist_ok=True)
r=dict(events=[],captures=[],passed=False);cal=Calibration(ROOT/'data')
a=SerialAgent('COM7','xilinx',r['events'],base=ROOT/'build/work/adc_rate_agent_20261102',bitfile=args.bitfile)
class SlowGenerator(Generator):
 def call(self,kind,command):
  time.sleep(max(0,.35-(time.monotonic()-self.last)))
  return super().call(kind,command)
g=None;initial=None;changed=False
def save():(out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf8')
try:
 g=SlowGenerator(out/'generator.jsonl')
 initial={q:g.ask(q) for q in (':SOUR1:FUNC?',':SOUR1:FREQ?',':SOUR1:VOLT?',':SOUR1:VOLT:OFFS?',':SOUR1:FUNC:SQU:DCYC?',':OUTP1?',':OUTP1:LOAD?')}
 r['generator_initial']=initial
 assert initial[':SOUR1:FUNC?']=='SQU' and float(initial[':SOUR1:VOLT?'])<=1 and abs(float(initial[':SOUR1:VOLT:OFFS?']))<1e-8
 assert float(initial[':OUTP1:LOAD?'])>1e6 and g.ask(':SOUR1:TRACK?')=='OFF'
 r['connected']=a.connect();r['initialized']=a.call('initialize',{'adc_divider':args.divider},timeout=120)
 digital=r['initialized']['identity']['digital_test_results']
 assert len(digital)==8 and all(d['errors']==0 and d['samples']==4096 for d in digital)
 assert all(abs(rate/(1e9/args.divider)-1)<.002 for rate in r['initialized']['sample_rates_hz'])
 for shape,frequency,stride in [('SQU',8000,64),('SIN',1000000,1),('SIN',5000000,1),('SIN',10000000,1)]:
  changed=True;g.write(':SOUR1:FREQ '+str(frequency));g.write(':SOUR1:FUNC '+shape)
  assert g.ask(':SOUR1:FUNC?')==shape and abs(float(g.ask(':SOUR1:FREQ?'))-frequency)<1
  time.sleep(1)
  for rep in range(5):
   frame=a.call('capture',{'sample_count':4096,'sample_stride':stride},timeout=30)
   name=f'{shape}_{frequency}_{rep}.json';(out/name).write_text(json.dumps(frame),encoding='utf8')
   codes=[w&65535 for w in frame['words'][0]]
   assert len(codes)==4096 and not any(w>>16 for w in frame['words'][0]) and not frame['simulated']
   fft=spectrum(codes,frame['sample_rates_hz'][0],'flattop')
   error=abs(fft['peak_frequency_hz']/frequency-1)
   row=dict(file=name,shape=shape,frequency_hz=frequency,stride=stride,error=error,peak_code_rms=fft['peak_rms'],ac_rms_code=fft['ac_rms'],mean_code=sum(codes)/len(codes),min_code=min(codes),max_code=max(codes))
   r['captures'].append(row);save()
   assert error<.002,row
   time.sleep(.3)
 if args.divider==20:
  r['switch_checks']=[]
  for divider in (16,20):
   status=a.call('adc_clock',{'adc_divider':divider},timeout=120)
   assert all(abs(rate/(1e9/divider)-1)<.002 for rate in status['sample_rates_hz'])
   assert all(d['errors']==0 and d['samples']==4096 for d in status['identity']['digital_test_results'])
   assert not any(output['enabled'] for output in status['outputs'])
   r['switch_checks'].append(status);save()
 r['passed']=True
finally:
 try:r['close']=a.close()
 finally:
  try:
   if g and changed:
    g.write(':SOUR1:FREQ '+initial[':SOUR1:FREQ?']);g.write(':SOUR1:FUNC '+initial[':SOUR1:FUNC?'])
    r['restored']={q:g.ask(q) for q in initial};assert r['restored']==initial
  finally:
   if g:g.s.close()
   save()
print(r['passed'],r.get('close'))
