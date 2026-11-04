"""Derived plots retain measured points, fit ranges and historical provenance."""
import csv
import hashlib
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from matplotlib.figure import Figure
from .analysis import input_resistance_summary
from .characteristics import _early_summary
from .profiles import Profile

VERSION=2


def draw_early(ax,rows,profile):
    ax.clear();summary=_early_summary(rows)
    fits={str(f['curve']):f for f in summary['curves']}
    for curve in sorted({str(p['curve']) for p in rows},key=float):
        points=sorted((p for p in rows if str(p['curve'])==curve),key=lambda p:float(p['uce_v']))
        x=[float(p['uce_v']) for p in points];y=[float(p['ic_a'])*1000 for p in points]
        label='IB≈{:.3g} {}'.format(float(points[0]['ib_estimated_a'])*(1000 if profile.big else 1e6),'mA' if profile.big else 'µA')
        fit=fits.get(curve)
        if fit:label+=' · ro≈{:.3g} kΩ{}'.format(fit['ro_ohm']/1000,'' if fit['fit_reliable'] else '（低可信）')
        line,=ax.plot(x,y,'.-',lw=1,ms=3,label=label)
        if fit:
            left=fit['x_intercept_v'];k=fit['slope_mA_per_v'];b=fit['intercept_mA']
            ax.plot([left,max(x)],[0,k*max(x)+b],'--',color=line.get_color(),lw=1,alpha=.8 if fit['fit_reliable'] else .35)
            ax.plot([left],[0],'x',color=line.get_color(),ms=6)
            selected=[(a,c) for a,c in zip(x,y) if fit['fit_start_uce_v']<=a<=fit['fit_stop_uce_v']]
            ax.scatter([p[0] for p in selected],[p[1] for p in selected],s=20,facecolors='none',edgecolors=line.get_color())
    va=summary['median_va_v']
    if va is not None:
        ax.axvline(-va,color='#9a4f55',ls=':',lw=1)
        note='VA 中位数 ≈ {:.3g} V\n各曲线独立外推，未强制共点'.format(va)
    else:note='尚无可靠 Early 拟合\n需足够的放大区线性测点'
    ax.text(.02,.97,note,transform=ax.transAxes,va='top',fontsize=9,bbox=dict(facecolor='white',edgecolor='#d0d8e2',alpha=.92))
    ax.axhline(0,color='#586879',lw=.7);ax.axvline(0,color='#586879',lw=.7)
    ax.set(xlabel=profile.voltage_axis+' / V',ylabel='IC / mA',title=profile.key.upper()+' · Early 外推 / ro')
    ax.grid(alpha=.2)
    if rows:ax.legend(fontsize=8,loc='upper left',bbox_to_anchor=(1.01,1))
    return summary


def draw_rin(ax,rows,config,record=None):
    ax.clear()
    if record is not None:
        series=record.get('rin_series',[])
        from .ac_history import draw_reference_series
        draw_reference_series(ax,series,resistance=True)
        summary=dict(display_only=True,record_id=record['id'],source_sha256=record['source_sha256'],basis=record.get('rin_basis'))
    else:
        points=[]
        for row in rows:
            try:f=float(row['actual_freq_hz']);r=float(row['input_resistance_ohm'])
            except (KeyError,ValueError,TypeError):continue
            if math.isfinite(f+r) and f>0 and r>0:points.append((f,r,row.get('mode')))
        for mode,label,style in (('coarse','扫描点','.-'),('refine','截止附近补测','D')):
            selected=sorted((f,r) for f,r,m in points if (m=='refine')==(mode=='refine'))
            if selected:ax.plot(*zip(*selected),style,ms=4,lw=1,label=label)
        summary=input_resistance_summary(rows,config.get('passband_stop_hz',150000))
        rtest=config.get('input_test_resistor_ohm')
        summary['test_resistor_ohm']=rtest
        median=summary['passband_median_ohm']
        if median is not None:ax.axhline(median,ls=':',color='#ba6545',label='通带中位数 {:.3g} Ω'.format(median))
    ax.set_title('')
    ax.set_xscale('log');ax.set(xlabel='频率 / kHz' if record is not None else '频率 / Hz',ylabel='Rin / Ω');ax.grid(alpha=.2)
    if ax.lines or ax.collections:ax.legend(fontsize=8,loc='best')
    return summary


def export_derived(directory,rows,state):
    measurement=state.get('measurement');directory=Path(directory)
    if measurement not in ('output','ac') or not rows:return None
    raw=directory/('output_points.csv' if measurement=='output' else 'ac_points.csv')
    if not raw.exists():raw=directory/'points.csv'
    if not raw.exists():return None
    signature=hashlib.sha256(raw.read_bytes()+json.dumps(state.get('config',{}),sort_keys=True).encode()).hexdigest()
    out=directory/'derived_analysis';target=out/'analysis.json'
    if target.exists():
        saved=json.loads(target.read_text(encoding='utf8'))
        if saved.get('source_sha256')==signature and saved.get('version')==VERSION:return saved
    out.mkdir(exist_ok=True)
    fig=Figure(figsize=(10,6),layout='constrained');ax=fig.add_subplot(111)
    profile=Profile(state.get('profile','npn_small'))
    summary=draw_early(ax,rows,profile) if measurement=='output' else draw_rin(ax,rows,state.get('config',{}))
    basis='模拟数据' if state.get('simulated') else '本次测点 / 按记录参数换算'
    if measurement=='output':fig.suptitle(basis+' · '+str(state.get('status','')),fontsize=10,color='#586879')
    fig.savefig(out/('early_voltage.png' if measurement=='output' else 'input_resistance.png'),dpi=160)
    if measurement=='output' and summary['curves']:
        with (out/'early_parameters.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(summary['curves'][0]));writer.writeheader();writer.writerows(summary['curves'])
    result=dict(version=VERSION,source_sha256=signature,source_file=raw.name,measurement=measurement,
                profile=profile.key,simulated=state.get('simulated'),analysis=summary)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


class DerivedPlots:
    def __init__(self,app):
        self.app=app;self.tabs={};self.key=None
        for kind,title in (('output','Early / ro'),('ac','输入电阻 Rin')):
            frame=tk.Frame(app.measure_tabs,bg='#101827');app.measure_tabs.add(frame,text=title)
            if kind=='output':
                app.label(frame,'圈点为拟合区；虚线外推至负电压轴。ro=1000/k（k 单位 mA/V）。',fg='#a6bad5',wraplength=700).pack(fill='x',padx=10,pady=6)
            figure,ax,canvas=app._plot(frame)
            self.tabs[kind]=(frame,figure,ax,canvas)
            app.measure_tabs.hide(frame)

    def refresh(self,rows):
        app=self.app;name=app.measurement
        for kind,(frame,*_) in self.tabs.items():
            if kind==name:app.measure_tabs.add(frame)
            else:app.measure_tabs.hide(frame)
        if name not in self.tabs:return
        history=app.ac_history.rin_reference() if name=='ac' else None
        key=(name,id(app.last_result),len(rows),app.selected_profile().key,history['id'] if history else None)
        if key==self.key:return
        self.key=key
        _,figure,ax,canvas=self.tabs[name]
        if name=='output':
            figure.subplots_adjust(right=.70)
            draw_early(ax,rows,app.selected_profile())
        else:
            cfg=app.last_result['state'].get('config',{}) if app.last_result else app.config_values['ac']
            draw_rin(ax,rows,cfg,app.ac_history.visible_record(rows) if history else None)
        if name=='output' and app.last_result and app.last_result['state'].get('simulated'):ax.set_title('模拟 · '+ax.get_title(),fontsize=10)
        canvas.draw_idle()

    def save_rin(self,directory):
        app=self.app
        if app.measurement!='ac':return
        self.refresh(app.rows)
        out=Path(directory)/'derived_analysis';out.mkdir(exist_ok=True)
        self.tabs['ac'][1].savefig(out/'input_resistance.png',dpi=160)
        raw=Path(directory)/'ac_points.csv'
        if not raw.exists():raw=Path(directory)/'points.csv'
        metadata=dict(display_reference=None,source='current_run',source_file=raw.name,
                      source_sha256=hashlib.sha256(raw.read_bytes()).hexdigest() if raw.exists() else None,
                      simulated=(app.last_result or {}).get('state',{}).get('simulated'))
        record=app.ac_history.rin_reference()
        if record:
            metadata=dict(source='historical_record',display_reference={k:record[k] for k in ('id','profile','manufacturer','model','source_archive','source_member','source_sha256','source_kind')},
                          source_file='curves.csv',source_sha256=record['source_sha256'],progressive=True,
                          acquisition_source_file=raw.name,acquisition_source_sha256=metadata['source_sha256'])
        (out/'input_resistance.source.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf8')
