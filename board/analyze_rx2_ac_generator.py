"""Analyze recorded RX2 nominal sine response without changing calibration."""
from pathlib import Path
import hashlib
import json
import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(__file__).resolve().parents[1]
out=root/'report/rx2_ac_generator_20261031'
r=json.loads((out/'collection.json').read_text(encoding='utf-8'))
assert r['complete'] and r['generator_off_confirmed'] and r['board_close']['cleanup_confirmed']
cal=json.loads((root/'data/rx2_calibration.json').read_text(encoding='utf-8'))
points=[]
for p in r['points']:
    p={k:v for k,v in p.items() if k not in ('statistics','generator')}
    p['error_percent']=(p['gain']-1)*100
    raw=out/p['waveform_file'];assert hashlib.sha256(raw.read_bytes()).hexdigest()==p['waveform_sha256']
    frame=json.loads(raw.read_text(encoding='utf-8'))
    codes=np.array(frame['words'][1],dtype=np.uint32)&65535
    y=(codes.astype(float)-cal['zero_code'])*cal['volts_per_code']
    fs=frame['sample_rates_hz'][1];expected=p['frequency_hz'];f=expected
    if expected>=100000:
        t=(np.arange(len(y))-(len(y)-1)/2)/fs
        def design(freq):
            w=2*np.pi*freq*t
            return np.column_stack([np.ones(len(y))]+[fn(k*w) for k in (1,2,3) for fn in (np.sin,np.cos)])
        for _ in range(8):
            x=design(f);b=np.linalg.lstsq(x,y,rcond=None)[0]
            d=2*np.pi*t*(b[1]*np.cos(2*np.pi*f*t)-b[2]*np.sin(2*np.pi*f*t))
            delta=float(np.linalg.lstsq(np.column_stack((x,d)),y-x@b,rcond=None)[0][-1]);f+=delta
            if abs(delta)<expected*1e-9:break
        x=design(f);b=np.linalg.lstsq(x,y,rcond=None)[0];amp=float(np.hypot(b[1],b[2]))
        assert abs(f/expected-1)<.01
        fit=dict(frequency_hz=f,fundamental_vpp=2*amp,residual_rms_v=float(np.std(y-x@b)),
                 thd_2_3_percent=float(np.sqrt(np.sum(b[3:]**2))/amp*100),
                 fit_vs_statistics_percent=(2*amp/p['measured_vpp_sine_rms']-1)*100)
        p['waveform_fit']=fit
    points.append(p)
main=points[:20];small=points[20:30];repeated=points[30:]
summary=dict(complete=True,reference_basis=r['reference_basis'],frequency_range_hz=[10000,6000000],
             amplitudes_vpp=[1.,.05],points=points,measurement_points=len(points),
             max_abs_error_percent_1vpp=max(abs(p['error_percent']) for p in main),
             max_abs_error_percent_50mvpp=max(abs(p['error_percent']) for p in small),
             max_repeat_drift_percent=max(abs(p['gain']/next(q['gain'] for q in main if q['frequency_hz']==p['frequency_hz'])-1)*100 for p in repeated),
             max_fit_vs_statistics_percent=max(abs(p['waveform_fit']['fit_vs_statistics_percent']) for p in points if 'waveform_fit' in p),
             generator_off_confirmed=True,board_cleanup_confirmed=True,
             off_state_baseline_valid_for_noise=False,
             off_state_note='Generator OFF left RX2 at rail with fault_count=50000; these records are excluded, not treated as zero noise. All energized RX2 measurement windows had fault_count=0.',
             limitations=['Relative to nominal generator settings; source/cable response is included',
                          'RMS-equivalent sine amplitude; raw waveform fundamental cross-check available at >=100 kHz',
                          'No RX1/RX2 phase or simultaneous-channel calibration',
                          'No automatic inverse-response compensation installed; production DC calibration unchanged',
                          'Transistor fixture remains disconnected; this is RX2 connector testing'],
             scpi_reference='https://int.rigol.com/Images/DG1000Z_ProgrammingGuide_EN_tcm7-2817.pdf')
(out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
fig,axes=plt.subplots(2,1,figsize=(10,7),sharex=True,layout='constrained')
for group,label in ((main,'1 Vpp nominal'),(small,'50 mVpp nominal')):
    f=[p['frequency_hz']/1000 for p in group]
    axes[0].semilogx(f,[p['error_percent'] for p in group],'o-',label=label)
    axes[1].semilogx(f,[p['repeat_span_vpp']/p['nominal_vpp']*100 for p in group],'o-',label=label)
axes[0].axhline(0,color='grey',lw=.8);axes[0].set_ylabel('Amplitude error vs nominal (%)');axes[0].legend()
axes[1].set_ylabel('Five-capture span (% of nominal)');axes[1].set_xlabel('Frequency (kHz)')
for ax in axes:ax.grid(True,which='both',alpha=.3)
fig.suptitle('RX2 AC response | 50 MSPS | DG1032Z CH1, High-Z\nNominal source reference; no external amplitude reference')
fig.savefig(out/'response.png',dpi=160)
print(json.dumps({k:v for k,v in summary.items() if k.startswith('max_') or k=='measurement_points'}))
