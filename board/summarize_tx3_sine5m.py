"""Export calibration evidence without conflating amplitude and DC checks."""
import argparse,csv,json,hashlib
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=argparse.ArgumentParser();p.add_argument('--sine',type=Path,required=True);p.add_argument('--other',type=Path,required=True)
p.add_argument('--release',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
read=lambda path:json.loads(path.read_text(encoding='utf8'))
sine,other,release=map(read,(args.sine,args.other,args.release));args.out.mkdir(exist_ok=True,parents=True)
assert all(r['amplitude_passed'] and r['close']['cleanup_confirmed'] for r in (sine,other,release))
rows=sine['verification']+other['verification']
with (args.out/'calibration_nodes.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.writer(f);w.writerow(['shape','frequency_hz','target_vpp_v','measured_vpp_v','amplitude_metric','error_percent','dc_v','amplitude_passed','dc_passed','zero_code','peak_codes'])
 for x in rows:w.writerow([x['shape'],x['frequency_hz'],x['target_vpp_v'],x['measurement']['vpp_v'],x['measurement']['metric'],100*x['amplitude_error_v']/x['target_vpp_v'],x['measurement']['dc_v'],x['amplitude_passed'],x['dc_passed'],x['zero_code'],x['peak_codes']])
with (args.out/'release_frames.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.writer(f);w.writerow(['shape','frequency_hz','target_vpp_v','repeat','measured_vpp_v','error_percent','dc_v','raw_file'])
 for x in release['points']:
  for i,m in enumerate(x['repeats']):w.writerow([x['shape'],x['frequency_hz'],x['target_vpp_v'],i+1,m['vpp_v'],100*(m['vpp_v']/x['target_vpp_v']-1),m['dc_v'],m['raw_file']])
fig,axes=plt.subplots(2,1,figsize=(10,7),sharex=True,layout='constrained')
for amp in sine['amplitudes_vpp']:
 group=sorted((x for x in sine['verification'] if x['target_vpp_v']==amp),key=lambda x:x['frequency_hz'])
 x=[v['frequency_hz']/1e6 for v in group]
 axes[0].plot(x,[100*v['amplitude_error_v']/amp for v in group],'.-',label=f'{amp*1000:g} mVpp')
 axes[1].plot(x,[v['measurement']['dc_v']*1000 for v in group],'.-')
axes[0].set_ylabel('Fundamental amplitude error (%)');axes[0].legend(ncol=5,fontsize=8)
axes[0].set_title('TX3 sine: DAC 125 MHz, scope full bandwidth, independent reverse checks')
axes[1].axhline(5,color='red',ls='--',lw=1);axes[1].axhline(-5,color='red',ls='--',lw=1)
released_sine=[x for x in release['points'] if x['shape']=='sine']
axes[1].scatter([x['frequency_hz']/1e6 for x in released_sine],[x['measurement']['dc_v']*1000 for x in released_sine],marker='x',color='black',label='Packaged requests after service restart')
axes[1].legend(fontsize=8)
axes[1].set_ylabel('DC center (mV)');axes[1].set_xlabel('Frequency (MHz)')
for ax in axes:ax.set_xscale('log');ax.grid(True,alpha=.25)
fig.savefig(args.out/'sine_validation.png',dpi=180);plt.close(fig)
summary=dict(dac_clock_hz=125000000,scope_bandwidth='OFF',sine_nodes=len(sine['verification']),other_nodes=len(other['verification']),
 sine_frequency_hz=sine['frequencies_hz'],amplitudes_vpp=sine['amplitudes_vpp'],session_amplitude_checks_passed=True,
 amplitude_stability_qualified=dict(sine=sine['warm_stability']['amplitude_stable'],square=other['warm_stability']['amplitude_stable'],triangle=other['warm_stability']['amplitude_stable']),
 dc_qualified=all(r['dc_passed'] for r in (sine,other,release)),
 sine_max_abs_amplitude_error_v=max(abs(x['amplitude_error_v']) for x in sine['verification']),
 sine_max_abs_amplitude_error_percent=max(abs(x['amplitude_error_v']/x['target_vpp_v'])*100 for x in sine['verification']),
 sine_max_abs_dc_v=max(abs(x['measurement']['dc_v']) for x in sine['verification']),
 release_settings=len(release['points']),release_independent_frames=sum(len(x['repeats']) for x in release['points']),
 release_max_vpp_spread_v=max(x['measurement']['vpp_spread_v'] for x in release['points']),
 release_max_abs_error_v=max(abs(v['vpp_v']-x['target_vpp_v']) for x in release['points'] for v in x['repeats']),
 release_max_abs_error_percent=max(100*abs(v['vpp_v']/x['target_vpp_v']-1) for x in release['points'] for v in x['repeats']),
 release_max_abs_dc_v=max(abs(v['dc_v']) for x in release['points'] for v in x['repeats']),
 release_dc_failed_settings=sum(not x['dc_passed'] for x in release['points']),
 cleanup_confirmed=True,bit_sha256=sine['initialized']['identity']['bit_sha256'],
 source_sha256={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.sine,args.other,args.release)},
 limitations='Scope-relative amplitudes with per-waveform metrics; sine residual contains both noise and distortion. Passing point checks does not qualify fixed-code stability: read amplitude_stability_qualified by shape. DC stability, absolute traceability, cold start and long-term behavior remain separate.')
summary['waveforms']={shape:dict(nodes=len(group),
 max_abs_error_v=max(abs(x['amplitude_error_v']) for x in group),
 max_abs_error_percent=max(100*abs(x['amplitude_error_v'])/x['target_vpp_v'] for x in group),
 dc_failed_nodes=[dict(frequency_hz=x['frequency_hz'],target_vpp_v=x['target_vpp_v'],dc_v=x['measurement']['dc_v']) for x in group if not x['dc_passed']])
 for shape in ('sine','square','triangle') if (group:=[x for x in rows if x['shape']==shape])}
(args.out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8');print(json.dumps(summary,indent=2))
