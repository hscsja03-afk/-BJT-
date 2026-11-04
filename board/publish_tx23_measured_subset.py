"""Publish independently revisited nodes after an explicit user wrap-up."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def publish(source):
    source=Path(source).resolve();r=json.loads(source.read_text(encoding='utf8'))
    if not r.get('cleanup_confirmed') or not r.get('closed',{}).get('cleanup_confirmed'):
        raise ValueError('Output cleanup must be confirmed')
    if r['status']!='incomplete' or 'Stop requested' not in r.get('error',''):
        raise ValueError('Expected the preserved user-requested stop record')
    if r.get('center_is_acceptance_criterion',True):raise ValueError('This publication excludes center by explicit user request')
    for name in ('dac_calibration.json','tx2_waveform_calibration.json','tx3_waveform_calibration.json'):
        if (ROOT/'data'/name).read_bytes()!=(source.parent/'data_before'/name).read_bytes():
            raise ValueError('Calibration changed during acquisition: '+name)
    identity=r['initialized']['identity'];source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    if identity['dac_divider']!=8 or r['probe']!=1:raise ValueError('Unexpected clock or probe')
    staged={};counts={}
    for channel in (2,3):
        rows=copy.deepcopy([p for p in r['verification'] if p['channel']==channel])
        if not rows:raise ValueError('No independently verified nodes for TX'+str(channel))
        keys=[(p['shape'],p['frequency_hz'],p['target_vpp_v']) for p in rows]
        if len(keys)!=len(set(keys)):raise ValueError('Duplicate verification node')
        for p in rows:
            if not p['amplitude_passed'] or abs(p['measurement']['vpp_v']-p['target_vpp_v'])>max(.0015,.02*p['target_vpp_v']):
                raise ValueError('Failed amplitude node')
            raw=ROOT/p['measurement']['raw_file']
            if hashlib.sha256(raw.read_bytes()).hexdigest()!=p['measurement']['raw_sha256']:raise ValueError('RAW file changed')
        validation={shape:dict(amplitude_only=True,
            amplitude_stability_qualified=r['warmup'][f'TX{channel}_{shape}']['stability']['amplitude_stable'],
            warm_stability=r['warmup'][f'TX{channel}_{shape}']['stability'],offset_validation_status='excluded_by_user')
            for shape in {p['shape'] for p in rows}}
        old=json.loads((ROOT/f'data/tx{channel}_waveform_calibration.json').read_text(encoding='utf8'))
        common=dict(calibration_id=f'tx{channel}-measured-subset-20261103-{source_hash[:8]}',
            recorded_at=r['finished'],source=str(source.relative_to(ROOT)),source_sha256=source_hash,
            acquisition_status=r['status'],acquisition_cleanup_confirmed=True,scope_idn=r['scope_idn'],scope_relative=True,
            connection=f'TX{channel} direct BNC to CH{r["connection"][f"TX{channel}"]}, x1, DC, high impedance',
            qualification_scope='completed_amplitude_revisits_only_center_excluded_by_user',
            completion_scope='User requested wrap-up; no claim of full calibration or stability for failed warm-up shapes')
        if channel==2:
            result=dict(schema_version=1,**common,status='partial_measured_nodes',exact_nodes_only=True,offset_v=.9,
                dac_sample_rate_hz=125000000,bitstream_sha256=identity['bit_sha256'],hwh_sha256=identity['hwh_sha256'],
                points=rows,shape_validation=validation)
            variants=[p for p in [old]+old.get('hardware_variants',[]) if
                (p.get('bitstream_sha256'),p.get('hwh_sha256'))!=(identity['bit_sha256'],identity['hwh_sha256'])]
            if variants:result['hardware_variants']=[{k:v for k,v in p.items() if k!='hardware_variants'} for p in variants]
        else:
            if old['bitstream_sha256']!=identity['bit_sha256'] or old['dac_sample_rate_hz']!=125000000:
                raise ValueError('Cannot combine different TX3 hardware calibration references')
            result=copy.deepcopy(old)
            result['legacy_grid_source']={k:old.get(k) for k in ('calibration_id','source','source_sha256','recorded_at')}
            result.update(common)
            result['exact_overrides']=dict(points=rows,shape_validation=validation,exact_nodes_only=True)
        result['previous_profile']=dict(calibration_id=old['calibration_id'],
            backup=str((source.parent/'subset_data_before'/f'tx{channel}_waveform_calibration.json').relative_to(ROOT)),
            sha256=hashlib.sha256((ROOT/f'data/tx{channel}_waveform_calibration.json').read_bytes()).hexdigest())
        staged[channel]=result;counts[channel]=len(rows)
    backup=source.parent/'subset_data_before';backup.mkdir(exist_ok=False)
    for ch,result in staged.items():
        target=ROOT/f'data/tx{ch}_waveform_calibration.json';shutil.copy2(target,backup/target.name)
        temp=target.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(target)
    evidence=dict(published=True,source=str(source),nodes=counts,user_requested_wrap_up=True,
                  center_qualified=False,full_calibration_complete=False,
                  dc_unchanged=(ROOT/'data/dac_calibration.json').read_bytes()==(source.parent/'data_before/dac_calibration.json').read_bytes())
    assert evidence['dc_unchanged']
    (source.parent/'subset_publication.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('source',type=Path);ap.add_argument('--user-requested-wrap-up',action='store_true',required=True)
    args=ap.parse_args();publish(args.source)
