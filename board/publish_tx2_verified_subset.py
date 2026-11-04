"""Install independently verified TX2 nodes from interrupted runs, exactly only.

Separate bitstreams remain separate profiles. Unverified nodes are not inferred.
No hardware access, DC mutation, or TX3 calibration mutation is performed.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'report/tx_wave_calibration_20261103'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_for(run):
    source=BASE/run/'result.json'
    record=json.loads(source.read_text(encoding='utf8'))
    identity=record['initialized']['identity']
    if record['probe']!=1 or identity['dac_divider']!=8:
        raise ValueError('Unexpected connection/clock')
    dc=ROOT/'data/dac_calibration.json'
    if dc.read_bytes()!=(source.parent/'data_before'/dc.name).read_bytes():
        raise ValueError('DC calibration has changed since this acquisition')
    accepted=[]
    for row in record['verification']:
        if row['channel']!=2 or not row['amplitude_passed'] or not row['dc_passed']:
            continue
        m=row['measurement']
        if abs(m['vpp_v']-row['target_vpp_v'])>max(.0015,.02*row['target_vpp_v']) or abs(m['dc_v']-.9)>.005:
            raise ValueError('Verification flag disagrees with measured value')
        if digest(ROOT/m['raw_file'])!=m['raw_sha256']:
            raise ValueError('Verification raw waveform hash mismatch')
        candidate=next(p for p in record['points'] if p.get('attempts') and p['channel']==2
            and p['shape']==row['shape'] and p['frequency_hz']==row['frequency_hz']
            and p['target_vpp_v']==row['target_vpp_v'])
        if any(candidate[key]!=row[key] for key in ('zero_code','peak_codes')):
            raise ValueError('Independent revisit changed candidate codes')
        if not record['warmup']['TX2_'+row['shape']]['stability']['amplitude_stable']:
            raise ValueError('Fixed-code amplitude stability did not pass')
        accepted.append(copy.deepcopy(row))
    if not accepted:raise ValueError('No independently verified TX2 nodes')
    if len({(p['shape'],p['frequency_hz'],p['target_vpp_v']) for p in accepted})!=len(accepted):
        raise ValueError('Duplicate nodes')
    validation={}
    for shape in {row['shape'] for row in accepted}:
        warm=record['warmup']['TX2_'+shape]['stability']
        validation[shape]=dict(amplitude_only=not warm['dc_stable'],
            amplitude_stability_qualified=True,warm_stability=warm,
            offset_validation_status='session_grid_verified' if warm['dc_stable'] else 'drift_observed')
    return dict(schema_version=1,calibration_id='tx2-subset-'+run+'-'+digest(source)[:8],
        status='partial_independently_verified_nodes',exact_nodes_only=True,offset_v=.9,
        dac_sample_rate_hz=125000000,bitstream_sha256=identity['bit_sha256'],hwh_sha256=identity['hwh_sha256'],
        recorded_at=record['finished'],scope_idn=record['scope_idn'],scope_relative=True,
        connection='TX2 direct BNC to Rigol CH3, DC x1, high impedance, full bandwidth',
        source=str(source.relative_to(ROOT)),source_sha256=digest(source),
        acquisition_status=record['status'],acquisition_cleanup_confirmed=record.get('cleanup_confirmed',False),
        subsequent_cleanup_source='report/tx_wave_calibration_20261103/wrap_up.json',
        subsequent_cleanup_sha256=digest(BASE/'wrap_up.json'),
        limitations='Only listed frequency/amplitude nodes at 0.9 V offset and matching bitstream/HWH are enabled. No interpolation/extrapolation or unmeasured waveform qualification. Current wiring/load/temperature; warm amplitude stability passed; DC center drift status retained. DC tables unchanged.',
        points=accepted,shape_validation=validation)


def main():
    cleanup=json.loads((BASE/'wrap_up.json').read_text(encoding='utf8'))
    if not cleanup['all_tx_outputs_disabled'] or cleanup['gpio_output']!=0:
        raise ValueError('Post-acquisition cleanup has not been confirmed')
    default=profile_for('boot_grid')
    native=profile_for('direct_grid')
    if len(default['points'])!=6 or len(native['points'])!=25:
        raise ValueError('Reviewed node counts have changed')
    default['hardware_variants']=[native]
    out=BASE/'partial_release';out.mkdir(exist_ok=True)
    target=ROOT/'data/tx2_waveform_calibration.json'
    protected={name:digest(ROOT/'data'/name) for name in ('dac_calibration.json','tx3_waveform_calibration.json')}
    if target.exists():shutil.copy2(target,out/'tx2_waveform_calibration.before.json')
    temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(default,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(target)
    assert all(digest(ROOT/'data'/name)==sha for name,sha in protected.items())
    report=dict(status='installed_verified_subset',nodes_default=6,nodes_native=25,
        exact_nodes_only=True,calibration_file=str(target.relative_to(ROOT)),calibration_sha256=digest(target),
        unchanged_files_sha256=protected,hardware_outputs_changed=False)
    (out/'publication.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
