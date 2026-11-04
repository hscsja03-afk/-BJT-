"""Publish a complete, independently verified LAN AC grid without changing DC."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[3]


def publish(source, amplitude_only=False):
    source=Path(source).resolve()
    result=json.loads(source.read_text(encoding='utf8'))
    if result['status']!='complete' or not result.get('cleanup_confirmed') or not result.get('dc_calibration_unchanged'):
        raise ValueError('Incomplete acquisition/cleanup; refusing publication')
    dc=ROOT/'data/dac_calibration.json'
    if dc.read_bytes()!=(source.parent/'data_before/dac_calibration.json').read_bytes():
        raise ValueError('DC calibration changed since acquisition')
    old_tx3=ROOT/'data/tx3_waveform_calibration.json'
    if old_tx3.read_bytes()!=(source.parent/'data_before/tx3_waveform_calibration.json').read_bytes():
        raise ValueError('TX3 table changed during acquisition; review concurrent changes first')
    tx2_backup=source.parent/'data_before/tx2_waveform_calibration.json'
    if tx2_backup.exists() and (ROOT/'data/tx2_waveform_calibration.json').read_bytes()!=tx2_backup.read_bytes():
        raise ValueError('TX2 table changed during acquisition; review concurrent changes first')
    identity=result['initialized']['identity']
    if identity['dac_divider']!=8 or result['probe']!=1:
        raise ValueError('This release expects DAC125 and confirmed direct BNC')
    expected={(s,f,a) for s,frequencies in result['frequencies_hz'].items()
              for f in frequencies for a in result['target_amplitudes_vpp']}
    profiles={}
    for channel in (2,3):
        rows=[r for r in result['verification'] if r['channel']==channel]
        if len(rows)!=len(expected) or {(r['shape'],r['frequency_hz'],r['target_vpp_v']) for r in rows}!=expected:
            raise ValueError(f'TX{channel} verification grid is incomplete')
        for row in rows:
            if (not row['amplitude_passed'] or abs(row['amplitude_error_v'])>max(.0015,.02*row['target_vpp_v'])
                    or abs(row['measurement']['vpp_v']-row['target_vpp_v'])>max(.0015,.02*row['target_vpp_v'])
                    or (not amplitude_only and abs(row['measurement']['dc_v']-row['offset_v'])>.02)):
                raise ValueError(f'TX{channel} failed verification: {row["shape"]}, {row["frequency_hz"]}, {row["target_vpp_v"]}')
            raw=ROOT/row['measurement']['raw_file']
            if hashlib.sha256(raw.read_bytes()).hexdigest()!=row['measurement']['raw_sha256']:
                raise ValueError('Raw verification waveform hash mismatch')
        shape_validation={}
        for shape,frequencies in result['frequencies_hz'].items():
            warm=result['warmup'][f'TX{channel}_{shape}']['stability']
            if not warm['amplitude_stable']:
                raise ValueError(f'TX{channel} {shape} fixed-code amplitude is not stable')
            dc_passed=all(r['dc_passed'] for r in rows if r['shape']==shape) and warm['dc_stable']
            shape_validation[shape]=dict(amplitude_only=amplitude_only or not dc_passed,
                amplitude_stability_qualified=warm['amplitude_stable'],warm_stability=warm,
                offset_validation_status='excluded_by_user' if amplitude_only else 'session_grid_verified' if dc_passed else 'drift_observed',
                frequency_min_hz=min(frequencies),frequency_max_hz=max(frequencies),scope_bandwidth='OFF')
        source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
        profiles[channel]=dict(schema_version=1,calibration_id=f'tx{channel}-lan-20261103-{source_hash[:8]}',
            recorded_at=result['finished'],dac_sample_rate_hz=125000000,
            bitstream_sha256=identity['bit_sha256'],hwh_sha256=identity['hwh_sha256'],
            scope_idn=result['scope_idn'],scope_relative=True,scope_bandwidth='OFF',
            qualification_scope='amplitude_only_center_excluded_by_user' if amplitude_only else 'amplitude_with_recorded_center_status',
            connection=f'TX{channel} direct BNC to CH{result.get("connection",{}).get(f"TX{channel}",channel+1)}, high impedance, DC x1',
            offset_v=.9 if channel==2 else 0,zero_offset_only=channel==3,square_duty_percent=50,
            source=str(source.relative_to(ROOT)),source_sha256=source_hash,
            limitations='Current wiring/load/temperature and exact measured bitstream only. Sine fundamental Vpp; square central plateau mean Vpp; triangle phase-folded Vpp. Independent reverse revisits use fixed codes. See per-shape stability and center drift. Interpolation is an estimate; no absolute, cold-start or long-term accuracy claim. TX1/TX2 DC tables unchanged.',
            points=copy.deepcopy(rows),shape_validation=shape_validation)
    backup=source.parent/'published_data_before'
    backup.mkdir(exist_ok=False)
    dc_hash=hashlib.sha256(dc.read_bytes()).hexdigest()
    for channel,profile in profiles.items():
        target=ROOT/f'data/tx{channel}_waveform_calibration.json'
        if target.exists():
            shutil.copy2(target,backup/target.name)
            old=json.loads(target.read_text(encoding='utf8'))
            if channel==2:
                variants=[p for p in [old]+old.get('hardware_variants',[])
                          if (p.get('bitstream_sha256'),p.get('hwh_sha256'))!=
                             (profile['bitstream_sha256'],profile['hwh_sha256'])]
                if variants:
                    profile['hardware_variants']=[{k:v for k,v in p.items() if k!='hardware_variants'} for p in variants]
            compatible=[record for record in old.get('compatible_bitstreams',[])
                        if record.get('source_bitstream_sha256')==profile['bitstream_sha256']]
            if compatible:profile['compatible_bitstreams']=compatible
            profile['previous_profile']=dict(calibration_id=old['calibration_id'],
                backup=str((backup/target.name).relative_to(ROOT)),sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf8')
        temporary.replace(target)
    if hashlib.sha256(dc.read_bytes()).hexdigest()!=dc_hash:
        raise RuntimeError('Unexpected DC file mutation')
    print('Published TX2/TX3 AC grids; DC calibration unchanged.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result',type=Path)
    parser.add_argument('--amplitude-only',action='store_true',help='Record center values without treating them as acceptance criteria')
    args=parser.parse_args()
    publish(args.result,amplitude_only=args.amplitude_only)
