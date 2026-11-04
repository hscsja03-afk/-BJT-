"""Hold identical DAC codes; isolate elapsed time, reapply and scope range changes."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import json,time
from pathlib import Path
from board.calibration.tx.calibrate_tx3_multi import SlowScope
from board.instruments.tx2_scope_zero import ROOT, SerialAgent
out=ROOT/'report/tx3_sine5m_20261102/fixed_code_diagnostic';out.mkdir(exist_ok=False)
r=dict(events=[],points=[],complete=False,frequency_hz=500000,zero_code=28497,peak_codes=3570)
a=SerialAgent('COM7','xilinx',r['events'],base=ROOT/'build/dist/desktop_adc625_20261102/ZynqBjtDesktop/_internal');s=None
class Scope(SlowScope):
 def call(self,method,value):
  time.sleep(max(0,.4-(time.monotonic()-self.last)))
  return super().call(method,value)
def save():(out/'result.json').write_text(json.dumps(r,indent=2),encoding='utf8')
def output():
 return a.call('output',dict(channel=2,action='start',mode='sine_code',frequency_hz=r['frequency_hz'],
  offset=r['zero_code'],peak=r['peak_codes'],phase_degrees=0,wiring_confirmed=True),timeout=60)
def measure(stage):
 path=out/f'{len(r["points"]):02d}_{stage}.npz'
 m=s.sample(path,r['frequency_hz'],'sine')
 state={k:s.ask(k+'?') for k in (':CHANnel3:SCALe',':CHANnel3:OFFSet',':CHANnel3:BWLimit',':ACQuire:TYPE')}
 assert float(state[':CHANnel3:SCALe'])==.1 and float(state[':CHANnel3:OFFSet'])==0 and state[':CHANnel3:BWLimit']=='OFF' and state[':ACQuire:TYPE']=='NORM'
 row=dict(stage=stage,at=time.time(),measurement=m,scope=state)
 r['points'].append(row);save();print(stage,round(m['vpp_v'],6),round(m['dc_v'],6),round(m['thd_2_3'],4),flush=True)
try:
 s=Scope();r['scope_idn']=s.idn;r['connect']=a.connect();r['initialize']=a.call('initialize',timeout=120)
 assert r['initialize']['identity']['dac_divider']==8
 s.setup(3,sine=True,scale=.1);s.point(r['frequency_hz']);r['output']=output();time.sleep(5)
 start=time.monotonic()
 while time.monotonic()-start<240:
  measure('fixed_hold');time.sleep(10)
 for i in range(3):
  output();time.sleep(4);measure('same_codes_reapplied')
 for i in range(3):
  s.write(':CHANnel3:SCALe 0.01');time.sleep(1);s.write(':CHANnel3:SCALe 0.1');time.sleep(5)
  measure('range_return')
 r['final_status']=a.call('status');r['complete']=True
except BaseException as exc:r['error']=repr(exc);print('STOP',repr(exc),flush=True)
finally:
 try:r['close']=a.close()
 except Exception as exc:r['close_error']=repr(exc)
 if s:
  try:s.write(':RUN');s.s.close()
  except Exception as exc:r['scope_close_error']=repr(exc)
 save()
print('DONE',r['complete'],r.get('close'),flush=True)
