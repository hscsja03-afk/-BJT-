"""Summarize measured calibration and released-package verification evidence."""
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'report/tx23_calibration_20261030'
def read(name):return json.loads((BASE/name).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

dc=read('tx2/result.json');sine=read('tx3_final/result.json');release=read('packaged_hardware_v3/result.json')
package=read('desktop_packaged.json');deploy=read('uart_deployment.json')
paired=read('paired_dc/result.json');cross=read('dc_crosstalk/result.json')
# Preserve the failed simultaneous-scope precision result. Separate it from
# valid voltage-mode checks and the fixed-scope paired output experiment.
assert dc['verified'] and sine['verified'] and package['passed'] and deploy['verified']
assert release['tx2_max_error_v']<.0015 and release['tx3_max_vpp_error_v']<.00075 and release['tx3_max_dc_error_v']<.002
assert paired['within_1p5mv']
assert all(r['close']['cleanup_confirmed'] for r in (dc,sine,release,paired,cross))
active=ROOT/'data/dac_calibration.json';assets=ROOT/'build/dist/desktop/ZynqBjtDesktop/_internal'
assert active.read_bytes()==(assets/'data/dac_calibration.json').read_bytes()
dist=assets.parent;manifest=json.loads((dist/'manifest.json').read_text())
assert all(sha(dist/name)==digest for name,digest in manifest.items())
summary=dict(status='tx2_tx3_individually_calibrated_with_documented_simultaneous_limits',scope_idn=release['scope_idn'],
             connection='TX2 -> CH3; TX3 -> CH4; direct high-impedance coax, DC x1',
             hardware_profile='PYNQ custom50 / 50 MSPS DAC / AD9747 FSC 0x01F9',
             tx2=dict(range_v=[0,1.8],measured_knots=37,independent_knots_and_midpoints=73,
                      table_entries=181,zero_code=dc['candidate_codes'][0],
                      calibration_max_error_v=dc['max_verification_error_v'],
                      packaged_max_error_v=release['tx2_max_error_v'],
                      packaged_zero_v=[p['measurement']['mean_v'] for p in release['dc'] if p['request_v']==0]),
             tx3=dict(frequency_range_hz=[10000,6000000],target_vpp_v=.05,frequency_knots=78,midpoints=12,
                      final_zero_checks=13,zero_code=sine['zero_code'],
                      calibration_max_vpp_error_v=sine['max_vpp_error_v'],
                      final_zero_max_error_v=sine['max_dc_error_v'],
                      packaged_max_vpp_error_v=release['tx3_max_vpp_error_v'],
                      packaged_max_dc_error_v=release['tx3_max_dc_error_v']),
             simultaneous_tx2_0p5v_max_error_v=release['tx2_simultaneous_max_error_v'],
             simultaneous_dual_display_precision_passed=release['passed'],
             packaged_voltage_modes_verified=True,
             paired_output_test=dict(tx2_requested_v=.5,tx3_test_hz=[100000,6000000,100000],
                                     scope_ch4_display=False,paired_on_minus_off_v=paired['paired_differences_v'],
                                     max_paired_difference_v=paired['max_paired_difference_v'],within_1p5mv=paired['within_1p5mv']),
             largest_raw_screen_dc_mean_disagreement_v=max(abs(p['waveforms']['RAW']['mean_v']-p['waveforms']['NORM']['mean_v']) for p in cross['points']),
             software_fix='Frequency-only sine edits now commit the frequency-compensated table; DC/raw to sine restores the table. New sine profile rejects other DAC sample rates.',
             source_dac_sha256=sha(active),packaged_dac_sha256=sha(assets/'data/dac_calibration.json'),
             packaged_agent_sha256=sha(assets/'agent.pyz'),desktop_exe_sha256=sha(dist/'ZynqBjtDesktop.exe'),
             manifest_files_verified=len(manifest),uart_deployment=deploy['remote'],
             old_calibration_preserved='report/tx23_calibration_20261030/prior/dac_calibration.json',
             outputs_disabled_cleanup_confirmed=paired['close']['cleanup_confirmed'],
             limitations='Single-output scope-relative calibration at high impedance and current warmed-up hardware. Not traceable DMM accuracy or a guarantee across temperature/cold boot/loads. Fixed-scope paired test at TX2=0.5 V found about +0.9..1.0 mV when TX3 is enabled. Dual-display automatic DC readings and waveform means differed by several mV; simultaneous full-range precision is not qualified. TX3 smaller amplitudes are scaled estimates. RX unchanged and unqualified after hardware modifications; TX1 nominal; no BJT qualification inferred.',
             evidence=['tx2/result.json','tx3/result.json','tx3_continued/result.json','tx3_final/result.json',
                       'packaged_hardware/result.json','packaged_hardware_v2/result.json','packaged_hardware_v3/result.json',
                       'dc_crosstalk/result.json','paired_dc/result.json','desktop_packaged.json','uart_deployment.json'])
(BASE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

fig,axes=plt.subplots(3,1,figsize=(9,9),layout='constrained')
a=sorted(dc['verification'],key=lambda p:p['target_v'])
axes[0].plot([p['target_v'] for p in a],[p['error_v']*1000 for p in a],'.-',color='#1769aa',lw=1)
axes[0].set(xlabel='TX2 requested DC voltage (V)',ylabel='Error (mV)',title='TX2: independent reverse sweep, 73 measured points')
a=sorted(sine['verification'],key=lambda p:p['requested_hz']);b=sine['midpoints']
axes[1].plot([p['requested_hz']/1e6 for p in a],[p['error_v']*1000 for p in a],'.-',color='#1769aa',lw=1,label='78 frequency knots')
axes[1].scatter([p['requested_hz']/1e6 for p in b],[p['error_v']*1000 for p in b],marker='x',color='#da670b',label='12 interpolation checks')
axes[1].set(xlabel='TX3 sine frequency (MHz)',ylabel='Vpp error (mV)',title='TX3: 50 mVpp fundamental amplitude, scope-referenced');axes[1].legend(loc='lower right')
a=sine['final_zero_verification'];b=release['sine']
axes[2].scatter([p['requested_hz']/1e6 for p in a],[p['dc_v']*1000 for p in a],color='#1769aa',label='Final zero calibration')
axes[2].scatter([p['requested_hz']/1e6 for p in b],[p['dc_v']*1000 for p in b],marker='x',color='#da670b',label='Packaged software; both TX enabled')
axes[2].set(xlabel='TX3 sine frequency (MHz)',ylabel='DC offset (mV)',title='TX3: final zero and released-package verification');axes[2].legend(loc='upper right')
for ax in axes:ax.axhline(0,color='gray',lw=.7);ax.grid(alpha=.25)
fig.savefig(BASE/'calibration_results.png',dpi=180);plt.close(fig)
print(json.dumps(summary,ensure_ascii=False,indent=2))
