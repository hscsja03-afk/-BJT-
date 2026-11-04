"""Publish independently checked sine nodes; retain other waveform histories."""
import argparse,copy,hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('result',type=Path);p.add_argument('--other-result',type=Path,required=True);args=p.parse_args()
source=args.result.resolve();r=json.loads(source.read_text(encoding='utf8'))
assert r.get('standalone_tx3_calibration_eligible') is True
assert r['amplitude_passed'] and r['status']=='complete' and r['close']['cleanup_confirmed']
assert r['initialized']['identity']['dac_divider']==8 and r['warm_stability']['amplitude_stable']
expected={(f,a) for f in r['frequencies_hz'] for a in r['amplitudes_vpp']}
assert len(expected)==50 and max(f for f,a in expected)==5000000
rows=r['verification'];assert len(rows)==50 and {(x['frequency_hz'],x['target_vpp_v']) for x in rows}==expected
assert all(x['shape']=='sine' and x['amplitude_passed'] and abs(x['amplitude_error_v'])<=max(.0015,.02*x['target_vpp_v']) and abs(x['measurement']['dc_v'])<=.02 for x in rows)
other_source=args.other_result.resolve();other=json.loads(other_source.read_text(encoding='utf8'))
assert other.get('standalone_tx3_calibration_eligible') is True
assert other['amplitude_passed'] and other['status']=='complete' and other['close']['cleanup_confirmed']
assert other['warm_stability']['amplitude_stable'] or other.get('qualification')=='reference_only_unstable_warmup'
assert other['initialized']['identity']['bit_sha256']==r['initialized']['identity']['bit_sha256']
expected_other={(s,f,a) for s in ('square','triangle') for f in (10000,100000,1000000) for a in r['amplitudes_vpp']}
assert len(other['verification'])==30 and {(x['shape'],x['frequency_hz'],x['target_vpp_v']) for x in other['verification']}==expected_other
assert all(x['amplitude_passed'] and abs(x['amplitude_error_v'])<=max(.0015,.02*x['target_vpp_v']) and abs(x['measurement']['dc_v'])<=.02 for x in other['verification'])
target=ROOT/'data/tx3_waveform_calibration.json';old=json.loads(target.read_text(encoding='utf8'))
backup=source.parent/'published_data_before';backup.mkdir(exist_ok=False)
shutil.copy2(target,backup/target.name)
profile=copy.deepcopy(old)
profile['previous_profile']=dict(calibration_id=old['calibration_id'],source=old.get('source'),source_sha256=old.get('source_sha256'),scope_bandwidth=old.get('scope_bandwidth'),release_verification=old.get('release_verification'))
profile.pop('release_verification',None)
profile.update(calibration_id='tx3-sine5m-dac125-20261102',recorded_at=r['finished'],scope_idn=r['scope_idn'],connection=r['connection'],
 source=str(source.relative_to(ROOT)),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),scope_bandwidth='OFF',
 limitations='Sine: 10 kHz..5 MHz; square/triangle: 10/100/1000 kHz; 50/70/100/200/500 mVpp. DAC125, DS1104Z CH3 DC x1 high impedance, full bandwidth. Sine fundamental Vpp, square central plateau mean Vpp, triangle phase-folded Vpp. Independent reverse amplitude verification passed. Read shape_validation for failed fixed-code stability; affected shapes remain reference-only. DC qualification is recorded separately; drift is not hidden by amplitude correction. Interpolation remains an estimate; cold start, long-term stability, other loads/offsets and absolute accuracy are unqualified.',
 bitstream_sha256=r['initialized']['identity']['bit_sha256'])
profile['shape_validation']=copy.deepcopy(old.get('shape_validation',{}))
profile['shape_validation']['sine']=dict(offset_validation_status='session_grid_verified' if r['dc_passed'] else 'drift_observed',amplitude_only=not r['dc_passed'],
 amplitude_stability_qualified=r['warm_stability']['amplitude_stable'],
 frequency_min_hz=10000,frequency_max_hz=5000000,scope_bandwidth='OFF',source=profile['source'],source_sha256=profile['source_sha256'],
 warm_stability=r['warm_stability'])
others=copy.deepcopy(other['verification'])
for shape in ('square','triangle'):
 profile['shape_validation'][shape]=dict(offset_validation_status='session_grid_verified' if other['dc_passed'] else 'drift_observed',
  amplitude_stability_qualified=other['warm_stability']['amplitude_stable'],
  amplitude_only=not other['dc_passed'],frequency_min_hz=10000,frequency_max_hz=1000000,scope_bandwidth='OFF',
  source=str(other_source.relative_to(ROOT)),source_sha256=hashlib.sha256(other_source.read_bytes()).hexdigest(),warm_stability=other['warm_stability'],
  unstable_warm_reference=other.get('unstable_warm_reference'))
profile['points']=others+copy.deepcopy(rows)
target.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf8')
print('TX3_SINE5M_INSTALLED',len(rows),'sine nodes;',len(others),'other waveform nodes rechecked')
