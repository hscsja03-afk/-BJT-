"""LCD只读浏览已保存记录；不启动扫描，不改变历史轮换游标。"""
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path

MODES = {'输入':'input','输出':'output','β':'beta','交流':'ac','Early':'output','Rin':'ac'}
COLORS = (6,7,9,14,8,13)


def load_latest(results, data, profile, mode):
    measurement=MODES[mode]
    candidates=[]
    for path in Path(results).rglob('run.json'):
        try:
            state=json.loads(path.read_text(encoding='utf-8-sig'))
            key=state.get('profile',state.get('config',{}).get('profile'))
            if key==profile and state.get('measurement')==measurement:
                candidates.append((path.stat().st_mtime_ns,path,state))
        except (OSError,ValueError):continue
    for _,path,state in sorted(candidates,key=lambda p:p[0],reverse=True):
        raw=path.parent/(measurement+'_points.csv')
        if not raw.exists():raw=path.parent/'points.csv'
        if not raw.exists():continue
        with raw.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
        if not rows:continue
        result=make_plot(rows,state,mode)
        if measurement=='ac' and profile.startswith('pnp'):
            reference_path=path.parent/'display_reference.json'
            reference=state.get('display_reference')
            if reference_path.exists():
                reference=json.loads(reference_path.read_text(encoding='utf-8-sig')).get('reference')
            if reference:
                index=json.loads((Path(data)/'pnp_ac_history/index.json').read_text(encoding='utf-8'))
                record=next((r for r in index['records'] if r['id']==reference['id'] and r['profile']==profile),None)
                if record is None:raise ValueError('历史记录未找到')
                source=Path(data)/'pnp_ac_history'/record['id']/'curves.csv'
                if hashlib.sha256(source.read_bytes()).hexdigest()!=record['source_sha256']:
                    raise ValueError('历史记录校验失败')
                from .ac_history import progressive_record
                record=progressive_record(record,rows,state.get('status')=='complete')
                series=record.get('rin_series' if mode=='Rin' else 'series',[])
                selected=[s for s in series if s['label'].startswith('sweep' if mode=='交流' else 'input resistance')]
                result['curves']=[([(float(x)/1000,float(y)) for x,y in s['points']],COLORS[i%6]) for i,s in enumerate(selected)]
                result['label']='历史参考 · '+record['id']
                if not any(points for points,_ in result['curves']):result['label']='该记录暂无可显示的历史点'
        if profile.startswith('pnp'):
            result['xlabel']=result['xlabel'].replace('UBE','UEB').replace('UCE','UEC')
        result['source']=str(path.parent)
        fit_limits(result)
        return result
    raise ValueError('暂无该档位记录')


def make_plot(rows,state,mode):
    curves=[]
    status=state.get('status','unknown')
    text={'running':'扫描中','complete':'已完成','cancelled':'已取消','failed':'运行异常',
          'acquired':'采集完成'}.get(status,status)
    label=('模拟' if state.get('simulated') else '实测')+' · '+text+' · {} 点'.format(len(rows))
    if mode=='Early':
        from .characteristics import _early_summary
        summary=_early_summary(rows)
        fits=[f for f in summary['curves'] if f['fit_reliable']]
        for i,fit in enumerate(fits):
            x=fit['fit_stop_uce_v'];k=fit['slope_mA_per_v'];b=fit['intercept_mA']
            curves.append(([(fit['x_intercept_v'],0),(x,k*x+b)],COLORS[i%6]))
        va=summary['median_va_v']
        if fits:
            ro=statistics.median(f['ro_ohm'] for f in fits)
            label=('模拟 · ' if state.get('simulated') else '已存 · ')+f'VA≈{va:.3g} V · ro中位≈{ro/1000:.3g} kΩ'
        else:label='有效线性测点不足'
        xlabel,ylabel='UCE / V','IC / mA'
    else:
        mapping={'输入':('ube_v','ib_estimated_a',1,1e6,'UBE / V','IB / µA'),
                 '输出':('uce_v','ic_a',1,1000,'UCE / V','IC / mA'),
                 'β':('ic_a','beta',1000,1,'IC / mA','β'),
                 '交流':('actual_freq_hz','gain',.001,1,'频率 / kHz','|β|'),
                 'Rin':('actual_freq_hz','input_resistance_ohm',.001,1,'频率 / kHz','Rin / Ω')}
        xkey,ykey,xscale,yscale,xlabel,ylabel=mapping[mode]
        groups={}
        for row in rows:
            try:
                x=float(row[xkey])*xscale;y=float(row[ykey])*yscale
                if not math.isfinite(x+y):continue
            except (KeyError,TypeError,ValueError):continue
            groups.setdefault(row.get('curve','0') if mode in ('输入','输出') else '0',[]).append((x,y))
        curves=[(sorted(points),COLORS[i%6]) for i,points in enumerate(groups.values())]
    profile=state.get('profile',state.get('config',{}).get('profile',''))
    if profile.startswith('pnp'):
        xlabel=xlabel.replace('UBE','UEB').replace('UCE','UEC')
    return dict(curves=curves,xlabel=xlabel,ylabel=ylabel,label=label)


def fit_limits(result):
    points=[p for curve,_ in result['curves'] for p in curve if all(math.isfinite(v) for v in p)]
    if not points:
        result.update(xlim=(0,1),ylim=(0,1));return
    for axis,key in ((0,'xlim'),(1,'ylim')):
        values=[p[axis] for p in points]
        low,high=min(0,min(values)),max(0,max(values))
        if low==high:high=low+1
        padding=(high-low)*.04
        result[key]=(low-padding,high+padding)
