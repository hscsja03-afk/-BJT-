"""Import the user-selected legacy folders; keep uncertain identities explicit."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('C:/Users/lgw/Downloads/IP-SDK_3.0 (2)/IP-SDK_3.0/IP-SDK/Python/RainDrop_Transistor_Scanner_Bundle_logo/runtime_scripts')
dest=ROOT/'data/pnp_ac_history';dest.mkdir(parents=True,exist_ok=True)
records=[];excluded=[]
for profile in ('pnp_small','pnp_big'):
    folders=sorted({p.parent for p in (SOURCE/profile/'ac').glob('**/*.csv')})
    for folder in folders:
        configs=list(folder.glob('*_config.json'))
        config=json.loads(configs[0].read_text(encoding='utf-8-sig')) if configs else {}
        plotted=list(folder.glob('*_curves.csv'))
        source=plotted[0] if plotted else sorted(folder.glob('*.csv'))[0]
        raw=source.read_bytes();lines=raw.decode('utf-8-sig').splitlines();groups={};rin_groups={};metrics={}
        if plotted:
            for row in csv.DictReader(io.StringIO('\n'.join(lines))):
                if row['figure']=='1' and row['axes']=='2' and ('resistance' in row['label'].lower() or 'rin' in row['label'].lower() or 'passband median' in row['label'].lower()):
                    rin_groups.setdefault((row['series_type'],row['label']),[]).append([float(row['x'])*1000,float(row['y'])])
                if row['figure']!='1' or row['axes']!='1':continue
                groups.setdefault((row['series_type'],row['label']),[]).append([float(row['x'])*1000,float(row['y'])])
        else:
            start=next((i for i,s in enumerate(lines) if s.startswith('mode,')),None)
            if start is None:excluded.append(str(source));continue
            for row in csv.reader(lines[:start]):
                if len(row)==2:metrics[row[0]]=row[1]
            for row in csv.DictReader(lines[start:]):
                f=float(row['actual_freq_Hz']);g=float(row.get('filtered_gain_replacing_outliers') or row['gain'])
                if not math.isfinite(f+g) or f<=0:continue
                label='square-refine' if 'refine' in row['mode'] else 'sweep (outliers replaced)'
                groups.setdefault(('line',label),[]).append([f,g])
                rin=row.get('filtered_input_resistance_ohm_replacing_outliers') or row.get('input_resistance_ohm_excluding_50ohm') or row.get('input_resistance_ohm')
                if rin and math.isfinite(float(rin)) and float(rin)>0:
                    rin_groups.setdefault(('line','refine resistance' if 'refine' in row['mode'] else 'input resistance (legacy processed)'),[]).append([f,float(rin)])
                if row.get('fitted_input_resistance_ohm'):
                    rin_groups.setdefault(('line','stored resistance fit'),[]).append([f,float(row['fitted_input_resistance_ohm'])])
                if row.get('fit_inlier')=='False':groups.setdefault(('scatter','gain replaced points'),[]).append([f,g])
            fit=[[float(r['actual_freq_Hz']),float(r['fitted_gain'])] for r in csv.DictReader(lines[start:]) if r.get('fitted_gain')]
            if fit:groups[('line','stored fit samples')]=sorted(fit)
        if not groups:excluded.append(str(source));continue
        original=dict(manufacturer=config.get('device_vendor',''),model=config.get('device_model',''))
        known=(original['model'].upper() in ('2N5401','TIP42C') and bool(original['manufacturer']))
        stamp=folder.name;rid=profile+'_'+stamp;target=dest/rid;target.mkdir(exist_ok=True)
        (target/'curves.csv').write_bytes(raw)
        if configs:(target/'config.json').write_bytes(configs[0].read_bytes())
        records.append(dict(id=rid,recorded_at=stamp,profile=profile,
            manufacturer=original['manufacturer'] if known else '未确认',model=original['model'].upper() if known else '未确认',
            identity_confirmed=known,original_device=original,source_archive='PNP 交流参考数据集',
            source_member=str(source.relative_to(SOURCE)),source_path=str(source),source_sha256=hashlib.sha256(raw).hexdigest(),
            source_kind='historical_display_processed' if plotted else 'historical_csv_processed',
            frequency_source_unit='kHz' if plotted else 'Hz',parameters=config.get('parameters',{}),metrics=metrics,
            series=[dict(kind=k[0],label=k[1],points=v) for k,v in groups.items()],
            rin_series=[dict(kind=k[0],label=k[1],points=v) for k,v in rin_groups.items()],
            rin_basis='Original processed display points, including any PNP frequency mirroring/outlier replacement; original resistance parameters, not current fixture measurements'))
(dest/'index.json').write_text(json.dumps(dict(schema_version=2,records=records,excluded=excluded),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(total=len(records),profiles={p:sum(r['profile']==p for r in records) for p in ('pnp_small','pnp_big')},identified=sum(r['identity_confirmed'] for r in records),excluded=excluded)))
