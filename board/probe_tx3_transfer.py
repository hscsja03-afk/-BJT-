import json,time
from calibrate_tx3_multi import SlowScope
from tx2_scope_zero import SerialAgent,ROOT
r={'events':[],'points':[]};s=None;a=SerialAgent('COM7','xilinx',r['events'],base=ROOT/'build/dist/desktop_pnp_input_table_manuals_20261101/ZynqBjtDesktop/_internal')
try:
 s=SlowScope();r['connect']=a.connect();r['initialize']=a.call('initialize',timeout=120)
 s.setup(3,sine=False,scale=1)
 for code in (32768,28167,24576,16384,8192,32768):
  r['state']=a.call('output',dict(channel=2,action='start',mode='dc_code',offset=code,wiring_confirmed=True))
  time.sleep(3)
  values=[float(s.ask(':MEASure:ITEM? VAVG,CHANnel3')) for _ in range(3)]
  row=dict(code=code,values=values);r['points'].append(row);print(row,flush=True)
  if any(abs(v)>3 for v in values):raise RuntimeError('Beyond probe voltage bound')
except Exception as e:r['error']=repr(e)
finally:
 try:r['close']=a.close()
 except Exception as e:r['close_error']=repr(e)
 if s:s.write(':RUN');s.s.close()
 (ROOT/'report/tx3_multi_20261101/transfer_probe.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
 print('DONE',r.get('error'),r.get('close'),flush=True)
