"""Dual-input check after user connected generator CH2 to RX2."""
import json,sys,time
from pathlib import Path
from tx2_scope_zero import SerialAgent,ROOT
from calibrate_rx1_generator import Generator
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.scope_display import spectrum

out=ROOT/'report/adc_rate_raise_20261102/hardware_dual';out.mkdir(exist_ok=True)
r=dict(connection='DG1032Z CH1 -> RX1; CH2 -> RX2, user confirmed',events=[],captures=[],rates=[],passed=False)
a=SerialAgent('COM7','xilinx',r['events'],base=ROOT/'build/work/adc_rate_agent_20261102',
 bitfile='/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/adc625_mmcm_20261102/bjt.bit')
class SlowGenerator(Generator):
 def call(self,kind,command):
  time.sleep(max(0,.4-(time.monotonic()-self.last)))
  return super().call(kind,command)
g=None;initial=None;changed=False
def save():(out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf8')
try:
 g=SlowGenerator(out/'generator.jsonl')
 keys=[q for c in (1,2) for q in (f':SOUR{c}:FUNC?',f':SOUR{c}:FREQ?',f':SOUR{c}:VOLT?',
  f':SOUR{c}:VOLT:UNIT?',f':SOUR{c}:VOLT:OFFS?',f':SOUR{c}:FUNC:SQU:DCYC?',f':OUTP{c}?',f':OUTP{c}:LOAD?',
  f':SOUR{c}:MOD:STAT?',f':SOUR{c}:SWE:STAT?',f':SOUR{c}:BURS:STAT?',f':SOUR{c}:TRACK?')]
 initial={q:g.ask(q) for q in keys};r['generator_initial']=initial;save()
 assert initial[':OUTP2?']=='OFF'
 for c in (1,2):
  assert initial[f':SOUR{c}:VOLT:UNIT?']=='VPP' and abs(float(initial[f':SOUR{c}:VOLT:OFFS?']))<1e-8
  assert float(initial[f':OUTP{c}:LOAD?'])>1e6
  assert all(initial[f':SOUR{c}:{mode}?']=='OFF' for mode in ('MOD:STAT','SWE:STAT','BURS:STAT','TRACK'))
 assert float(initial[':SOUR1:VOLT?'])==1 and initial[':OUTP1?']=='ON'
 r['connected']=a.connect()
 changed=True
 g.write(':SOUR2:VOLT 1');g.write(':SOUR2:FREQ 8000');g.write(':SOUR2:FUNC SQU')
 assert float(g.ask(':SOUR2:VOLT?'))==1 and float(g.ask(':SOUR2:VOLT:OFFS?'))==0
 g.write(':OUTP2 ON');assert g.ask(':OUTP2?')=='ON'
 for divider in (16,20):
  status=a.call('adc_clock',dict(adc_divider=divider),timeout=120)
  assert all(abs(rate/(1e9/divider)-1)<.002 for rate in status['sample_rates_hz'])
  assert len(status['identity']['digital_test_results'])==8
  assert all(d['errors']==0 and d['samples']==4096 for d in status['identity']['digital_test_results'])
  r['rates'].append(status);save()
  for shape,hz,stride in [('SQU',8000,64),('SIN',1000000,1),('SIN',5000000,1),('SIN',10000000,1)]:
   for c in (1,2):
    g.write(f':SOUR{c}:FREQ {hz}');g.write(f':SOUR{c}:FUNC {shape}')
    assert g.ask(f':SOUR{c}:FUNC?')==shape and abs(float(g.ask(f':SOUR{c}:FREQ?'))-hz)<1
   time.sleep(1)
   for rep in range(2):
    frame=a.call('capture',dict(sample_count=4096,sample_stride=stride),timeout=30)
    filename=f'div{divider}_{shape}_{hz}_{rep}.json';(out/filename).write_text(json.dumps(frame))
    assert not frame['simulated']
    for ch in (0,1):
     words=frame['words'][ch];codes=[w&65535 for w in words]
     assert len(codes)==4096 and not any(w>>16 for w in words)
     fft=spectrum(codes,frame['sample_rates_hz'][ch],'flattop')
     error=abs(fft['peak_frequency_hz']/hz-1)
     row=dict(file=filename,divider=divider,channel=ch+1,shape=shape,frequency_hz=hz,error=error,
      peak_code_rms=fft['peak_rms'],ac_rms_code=fft['ac_rms'],min_code=min(codes),max_code=max(codes))
     r['captures'].append(row);save();assert error<.002,row
    time.sleep(.4)
 r['passed']=True
except BaseException as exc:
 r['error']=str(exc);raise
finally:
 try:r['close']=a.close()
 finally:
  try:
   if g and changed:
    g.write(':OUTP2 OFF')
    for c in (1,2):
     g.write(f':SOUR{c}:FREQ '+initial[f':SOUR{c}:FREQ?'])
     g.write(f':SOUR{c}:FUNC '+initial[f':SOUR{c}:FUNC?'])
    g.write(':SOUR2:VOLT '+initial[':SOUR2:VOLT?'])
    r['restored']={q:g.ask(q) for q in initial};assert r['restored']==initial
  finally:
   if g:g.s.close()
   save()
print('DUAL_ADC_PASS',r['passed'],r.get('close'))
