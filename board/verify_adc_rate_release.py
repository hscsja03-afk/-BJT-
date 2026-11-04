"""Check the packaged agent against the promoted default overlay."""
import json,hashlib
from tx2_scope_zero import SerialAgent,ROOT
out=ROOT/'report/adc_rate_raise_20261102'
r=dict(events=[],passed=False)
a=SerialAgent('COM7','xilinx',r['events'],base=ROOT/'build/dist/desktop_adc625_20261102/ZynqBjtDesktop/_internal')
try:
 r['connected']=a.connect()
 assert r['connected']['status']['adc_max_rate_hz']==62500000
 r['initialized']=a.call('initialize',timeout=120)
 assert r['initialized']['identity']['adc_divider']==20
 assert r['initialized']['identity']['bit_sha256']=='d844e70d6bb3a813ab08eedd0cf181cbffe8774fe22cac0b4dadf0089bd54001'
 r['high']=a.call('adc_clock',{'adc_divider':16},timeout=120)
 assert all(62400000<rate<62600000 for rate in r['high']['sample_rates_hz'])
 frame=a.call('capture',{'sample_count':4096,'sample_stride':64},timeout=30)
 (out/'production_frame.json').write_text(json.dumps(frame))
 assert not frame['simulated'] and all(len(w)==4096 for w in frame['words'])
 r['default']=a.call('adc_clock',{'adc_divider':20},timeout=120)
 assert all(49900000<rate<50100000 for rate in r['default']['sample_rates_hz'])
 assert not any(v['enabled'] for v in r['default']['outputs'])
 r['passed']=True
finally:
 try:r['close']=a.close()
 finally:(out/'production_verify.json').write_text(json.dumps(r,indent=2))
print('PRODUCTION_ADC_CLOCK_PASS',r['passed'],r['close'])
