import json,time
from pathlib import Path
from calibrate_tx3_multi import SlowScope
from tx2_scope_zero import SerialAgent,ROOT
r={'events':[]};s=None;a=SerialAgent('COM7','xilinx',r['events'],base=ROOT/'build/dist/desktop_pnp_input_table_manuals_20261101/ZynqBjtDesktop/_internal')
try:
 s=SlowScope();r['before']=s.prior
 r['connected']=a.connect();r['initialize']=a.call('initialize',timeout=120)
 s.setup(3,sine=True,scale=.5);s.point(100000)
 r['muted']={q:s.ask(q) for q in (':MEASure:ITEM? VAVG,CHANnel3',':MEASure:ITEM? VPP,CHANnel3')}
 r['start']=a.call('output',dict(channel=2,action='start',mode='sine_code',offset=28167,peak=499,frequency_hz=100000,phase_degrees=0,wiring_confirmed=True))
 time.sleep(3)
 r['active']={q:s.ask(q) for q in (':MEASure:ITEM? VAVG,CHANnel3',':MEASure:ITEM? VPP,CHANnel3',':MEASure:ITEM? FREQuency,CHANnel3',':CHANnel3:SCALe?',':CHANnel3:OFFSet?')}
 print(json.dumps(r['active']),flush=True)
 try:r['sample']=s.sample(ROOT/'report/tx3_multi_20261101/diagnostic.npz',100000,'sine')
 except Exception as e:r['sample_error']=repr(e)
except Exception as e:r['error']=repr(e)
finally:
 try:r['close']=a.close()
 except Exception as e:r['close_error']=repr(e)
 if s:s.write(':RUN');s.s.close()
 (ROOT/'report/tx3_multi_20261101/diagnostic.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in r.items() if k in ('sample','sample_error','error','muted','active','close')}),flush=True)
