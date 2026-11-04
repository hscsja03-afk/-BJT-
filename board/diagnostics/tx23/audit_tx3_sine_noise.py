"""Separate residual waveform energy from sine-amplitude repeatability."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[3]))

import argparse,json
from pathlib import Path
import numpy as np
from board.calibration.tx.calibrate_tx23_scope import fit_sine
from board.instruments.tx2_scope_zero import ROOT
p=argparse.ArgumentParser();p.add_argument('result',type=Path);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
r=json.loads(args.result.read_text(encoding='utf8'));rows=[]
assert r['status']=='complete' and len(r['verification'])==50
for row in r['verification']:
 z=np.load(ROOT/row['measurement']['raw_file']);raw=z['raw'];pre=z['preamble'];n=len(raw)//2
 half=[fit_sine(raw[:n],pre,row['frequency_hz']),fit_sine(raw[n:],pre,row['frequency_hz'])]
 diff=abs(half[0]['vpp_v']-half[1]['vpp_v']);limit=max(.0015,.02*row['target_vpp_v'])
 rows.append(dict(frequency_hz=row['frequency_hz'],target_vpp_v=row['target_vpp_v'],
  residual_rms_v=row['measurement']['residual_rms_v'],half_fits=half,half_vpp_difference_v=diff,limit_v=limit,passed=diff<=limit))
report=dict(source=str(args.result),rows=rows,passed=all(x['passed'] for x in rows),
 max_half_vpp_difference_v=max(x['half_vpp_difference_v'] for x in rows),
 limit='Within-frame check only; residual includes distortion and noise. Independent reverse and release captures are recorded separately.')
args.out.write_text(json.dumps(report,indent=2),encoding='utf8');print(report['passed'],report['max_half_vpp_difference_v'])
raise SystemExit(0 if report['passed'] else 1)
