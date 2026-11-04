"""用本次示波器原始记录核对FFT幅值与独立正弦拟合。"""
import json,sys,math
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.scope_display import spectrum
source=ROOT/'report/tx3_multi_resume_20261101/result.json'
records=json.loads(source.read_text(encoding='utf-8'))['points']
results=[]
for row in records:
 if row['shape']!='sine' or 'peak_codes' not in row:continue
 m=row['attempts'][-1]['measurement']
 raw=np.load(ROOT/m['raw_file']);pre=raw['preamble']
 volts=(raw['raw'].astype(float)-pre[8]-pre[9])*pre[7]
 fft=spectrum(volts,1/pre[4]);index=int(np.argmax(fft['rms'][1:]))+1
 target=m['vpp_v']/math.sqrt(8)
 result=dict(frequency_hz=row['frequency_hz'],target_vpp_v=row['target_vpp_v'],
             fft_peak_hz=float(fft['frequency_hz'][index]),fft_rms_v=float(fft['rms'][index]),
             sine_fit_rms_v=target,relative_error=float(fft['rms'][index]/target-1),source=m['raw_file'])
 assert abs(result['relative_error'])<.03,result
 assert abs(result['fft_peak_hz']-m['frequency_hz'])<=fft['bin_hz'],result
 results.append(result)
out=ROOT/'report/scope_fft_persistence_20261101/recorded_fft_check.json'
out.write_text(json.dumps(dict(passed=True,source='Rigol CH3 waveform records, not FPGA RX acquisition',points=results),indent=2),encoding='utf-8')
print('PASS',len(results),'recorded sine FFT comparisons')
