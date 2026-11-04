"""Add derived figures beside existing runs without modifying source records."""
import argparse,csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src/python'))
import matplotlib
matplotlib.use('Agg');matplotlib.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans'];matplotlib.rcParams['axes.unicode_minus']=False
from zynq_bjt.measurement_views import export_derived
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT/'measurements');p.add_argument('--report',type=Path,required=True);a=p.parse_args()
report=dict(completed=[],skipped=[],errors=[])
for path in a.root.rglob('run.json'):
    try:
        state=json.loads(path.read_text(encoding='utf-8-sig'));kind=state.get('measurement')
        if kind not in ('output','ac'):continue
        source=path.parent/('output_points.csv' if kind=='output' else 'ac_points.csv')
        if not source.exists():source=path.parent/'points.csv'
        if not source.exists():report['skipped'].append(dict(path=str(path),reason='No supported point CSV'));continue
        with source.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        result=export_derived(path.parent,rows,state)
        if result:report['completed'].append(dict(path=str(path.parent),measurement=kind,analysis=result['analysis']))
    except Exception as e:report['errors'].append(dict(path=str(path),error=str(e)))
a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:len(v) for k,v in report.items()}))
