"""仅将完整且独立复测通过的45点表安装到本地数据目录。"""
import argparse,hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('result',type=Path);args=ap.parse_args()
source=args.result.resolve();result=json.loads(source.read_text(encoding='utf-8'))
assert result['status']=='complete' and result['passed'] and result['close']['cleanup_confirmed']
rows=result['verification']
expected={(shape,f,a) for shape in ('sine','square','triangle') for f in (10000,100000,1000000) for a in (.05,.07,.1,.2,.5)}
assert len(rows)==45 and {(r['shape'],r['frequency_hz'],r['target_vpp_v']) for r in rows}==expected
assert all(r['passed'] and abs(r['amplitude_error_v'])<=max(.0015,.02*r['target_vpp_v']) and abs(r['measurement']['dc_v'])<=.005 for r in rows)
profile=dict(schema_version=1,calibration_id='tx3-multi-20261101',dac_sample_rate_hz=125000000,
             recorded_at=result['finished'],scope_idn=result['scope_idn'],connection=result['connection'],
             scope_bandwidth='20M',source=str(source.relative_to(ROOT)),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
             scope_relative=True,zero_offset_only=True,square_duty_percent=50,
             limitations='Session-relative, current wiring/load/temperature. Sine fundamental Vpp; square plateau Vpp; triangle 128-bin phase-average Vpp. No cold-start, long-term stability, nonzero offsets or other square duties qualification. Interpolation/extrapolation are estimates.',
             previous_zero_reference_incompatible=True,points=rows)
target=ROOT/'data/tx3_waveform_calibration.json'
backup=source.parent/'data_before';backup.mkdir(exist_ok=True)
for name in ('dac_calibration.json','tx3_waveform_calibration.json'):
 path=ROOT/'data'/name
 if path.exists():shutil.copy2(path,backup/name)
target.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
print(target)
