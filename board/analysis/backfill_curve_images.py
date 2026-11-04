"""Offline main-plot backfill through the same desktop autosave path."""
import csv,json,sys,tkinter as tk
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.desktop import App
from zynq_bjt.desktop_session import MEASUREMENTS
from zynq_bjt.profiles import LABELS
out=ROOT/'report/curve_autosave_20261102';out.mkdir(exist_ok=True)
root=tk.Tk();root.withdraw();app=App(root,workspace=out/'backfill_workspace');root.withdraw()
report=dict(saved=[],empty=[],errors=[])
try:
    for path in sorted((ROOT/'measurements/results').rglob('run.json')):
        try:
            state=json.loads(path.read_text(encoding='utf-8-sig'))
            name=state.get('measurement') or ('input' if 'uce_values_v' in state.get('config',{}) else None)
            if name not in MEASUREMENTS:continue
            source=path.parent/MEASUREMENTS[name][2]
            if not source.exists():continue
            with source.open(encoding='utf-8-sig',newline='') as f:
                if next(csv.DictReader(f),None) is None:report['empty'].append(str(path));continue
            profile=state.get('profile',state.get('config',{}).get('profile','npn_small'))
            state.update(measurement=name,profile=profile)
            app.last_result=None;app.rows=[];app.measurement=name;app._parameter_profile=profile
            app.profile.set(LABELS[profile]);app.sync_measurement_columns();app.reset_measurement_plot()
            app.last_result=dict(state=state,run_id=path.parent.name,local_directory=str(path.parent))
            app.read_result(path.parent)
            images=list(path.parent.glob('curve*.png'))
            if not images:raise RuntimeError('No autosaved main image')
            report['saved'].append(dict(directory=str(path.parent),images=[p.name for p in images]))
        except Exception as e:report['errors'].append(dict(path=str(path),error=repr(e)))
        root.update_idletasks()
finally:
    app.tools.close()
    for job in root.tk.call('after','info'):root.tk.call('after','cancel',job)
    root.destroy()
    (out/'backfill.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print({k:len(v) for k,v in report.items()})
