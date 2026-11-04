"""Historical display records remain independent of live acquisition/results."""
import hashlib
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk


def vendor(value):
    value=value.strip().lower()
    return {'jscj':'长晶科技','jiangsu changjing':'长晶科技','onsemi':'安森美','on semiconductor':'安森美'}.get(value,value)


class HistoryLibrary:
    def __init__(self, data, cursor_path):
        self.data=Path(data)/'pnp_ac_history';self.cursor_path=Path(cursor_path)
        path=self.data/'index.json'
        self.records=json.loads(path.read_text(encoding='utf-8'))['records'] if path.exists() else []
        try:self.cursors=json.loads(self.cursor_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.cursors={}

    def candidates(self, profile, device, pool=False):
        records=sorted((r for r in self.records if r['profile']==profile),key=lambda r:r['id'])
        if pool:return records
        if not device.get('manufacturer','').strip() or not device.get('model','').strip():return []
        matched=[r for r in records if r.get('identity_confirmed') and vendor(r['manufacturer'])==vendor(device.get('manufacturer',''))
                 and r['model'].upper()==device.get('model','').strip().upper()]
        return matched or [r for r in records if not r.get('identity_confirmed')]

    def choose(self, profile, device, advance=False, pool=False, after_id=None):
        records=self.candidates(profile,device,pool)
        if not records:return None
        key='|'.join((profile,vendor(device.get('manufacturer','')),device.get('model','').strip().upper(),str(pool)))
        index=int(self.cursors.get(key,0))%len(records)
        if after_id:index=next(((i+1)%len(records) for i,r in enumerate(records) if r['id']==after_id),index)
        record=records[index]
        self.load(record)
        if advance:
            self.cursors[key]=(index+1)%len(records)
            self.cursor_path.parent.mkdir(parents=True,exist_ok=True)
            self.cursor_path.write_text(json.dumps(self.cursors,ensure_ascii=False),encoding='utf-8')
        return record

    def load(self,record):
        raw=self.data/record['id']/'curves.csv'
        if hashlib.sha256(raw.read_bytes()).hexdigest()!=record['source_sha256']:
            raise ValueError('历史曲线文件哈希不一致')
        return record


def reference_identity(record, device):
    if record.get('identity_confirmed'):
        return ' '.join(str(record.get(k,'')).strip() for k in ('manufacturer','model')).strip()
    return ' '.join(str(device.get(k,'')).strip() for k in ('manufacturer','model')).strip()


def trend_extension(record, frequencies):
    """Display-only extrapolation, anchored to the final stored sweep point."""
    def valid(points):
        return sorted({float(f):float(y) for f,y in points if math.isfinite(f) and math.isfinite(y) and f>0 and y>0}.items())
    main=valid(next((s['points'] for s in record['series'] if s['label'].startswith('sweep')),[]))
    if len(main)<2:return None
    end,value=main[-1]
    future=sorted({f for f in frequencies if f>end})
    if not future:return None
    fit=next((valid(s['points']) for s in record['series'] if 'fit' in s['label'].lower() and s['label'].lower()!='fitted au' and len(valid(s['points']))>=2),main)
    tail=fit[-6:];xs=[math.log(f) for f,_ in tail];ys=[math.log(y) for _,y in tail]
    xm=sum(xs)/len(xs);ym=sum(ys)/len(ys)
    denominator=sum((x-xm)**2 for x in xs)
    if denominator<=0:return None
    slope=min(0.0,sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/denominator)
    points=[[end,value]]+[[f,value*math.exp(slope*math.log(f/end))] for f in future]
    return dict(label='trend extrapolation',points=points,extrapolated=True,
                method='log_log_tail_slope_anchored_to_last_sweep',slope=slope,
                source_frequency_max_hz=end,frequency_max_hz=future[-1])


def progressive_record(record, rows, complete=False):
    """Reveal reference samples only as acquisition points arrive."""
    coarse=sum(row.get('mode')!='refine' for row in rows)
    refine=len(rows)-coarse
    main=next((s['points'] for s in record['series'] if s['label'].startswith('sweep')),[])
    frequencies=[]
    for row in rows:
        try:f=float(row['actual_freq_hz'])
        except (KeyError,ValueError,TypeError):continue
        if math.isfinite(f) and f>0:frequencies.append(f)
    visible=[p for p in main if p[0]<=max(frequencies)] if frequencies else main[:coarse]
    result=dict(record)
    for key in ('series','rin_series'):
        shown_points=visible[:coarse] if key=='rin_series' else visible
        low=min((p[0] for p in shown_points),default=0)
        high=max((p[0] for p in shown_points),default=0)
        series=[]
        for source in record.get(key,[]):
            label=source['label'].lower();pts=source['points']
            if label in ('fitted au','0.707 * au') or label.startswith('passband median'):
                pts=pts if shown_points else []
            elif 'f_beta' in label:
                pts=[p for p in pts if low<=p[0]<=high] if shown_points else []
            elif 'refine' in label:
                pts=pts[:refine]
            elif 'fit' in label and not label.startswith('input resistance'):
                # Stored reference fits exist independently of this run's status.
                pts=[p for p in pts if low<=p[0]<=high] if shown_points else []
            else:
                shown={p[0] for p in shown_points}
                pts=[p for p in pts if p[0] in shown]
            if pts:series.append(dict(source,points=pts))
        result[key]=series
    extension=trend_extension(record,frequencies)
    if extension:
        result['series'].append(extension)
        result['extrapolation']={k:v for k,v in extension.items() if k!='label'}
    return result


def draw_reference_series(ax, series, resistance=False):
    """Render original reference layers with their original values, in kHz."""
    for item in series:
        label=item['label'];name=label.lower();points=item['points']
        if resistance:
            if name.startswith('input resistance'):label='输入电阻'
            elif name=='actual input resistance points':label='输入电阻采样点'
            elif 'replaced points' in name:label='替换点'
            elif name.startswith('filtered'):label='滤波点'
            elif 'refine' in name:label='补测点'
            elif 'fit' in name:label='输入电阻拟合'
            elif name.startswith('passband median'):label='通带中位数'
        elif 'replaced points' in name:label='异常替换点'
        elif 'refine' in name:label='补测点'
        elif name.startswith('sweep'):label='扫描点'
        elif 'fit' in name and name!='fitted au':label='拟合曲线'
        if not points:continue
        x=[p[0]/1000 for p in points];y=[p[1] for p in points]
        if item.get('extrapolated'):
            ax.plot(x,y,'o-',color='#145b91',markerfacecolor='#145b91',ms=4,lw=1.8,label='_nolegend_',zorder=5)
        elif name=='fitted au' or name.startswith('passband median'):
            ax.axhline(y[0],ls='--',color='#2ca02c',lw=1.4,label=label)
        elif name=='0.707 * au':
            ax.axhline(y[0],ls='--',color='#d62728',lw=1.4,label=label)
        elif 'f_beta' in name:
            ax.axvline(x[0],ls=':',color='#9467bd',lw=1.4,label=label)
        elif 'replaced points' in name:
            continue
        elif name.startswith('filtered'):
            ax.scatter(x,y,s=28,facecolors='white',edgecolors='#9467bd' if resistance else '#17becf',linewidths=1.3,label=label,zorder=5)
        elif name=='actual input resistance points':
            ax.scatter(x,y,s=20,color='#bcbcbc',alpha=.55,label=label)
        elif 'refine' in name:
            ax.plot(x,y,'D',color='#2ca02c',ms=5,label=label,zorder=5)
        elif name in ('square-low','square-high'):
            ax.plot(x,y,'o' if name=='square-low' else 's',color='#145b91' if name=='square-low' else '#b95100',ms=5.5,label=label,zorder=4)
        elif name.startswith('sweep'):
            ax.plot(x,y,'o-',color='#145b91',lw=1.8,ms=4,label=label,zorder=4)
        elif name.startswith('input resistance'):
            ax.plot(x,y,'o-',color='#1398ab',lw=1.5,ms=4.5,label=label,zorder=4)
        elif 'fit' in name:
            ax.plot(x,y,'-',color='#a8b1bd',alpha=.65,lw=1.2,label=label,zorder=2)
        else:
            ax.plot(x,y,'.-',lw=1,label=label)
    ax.set_xscale('log');ax.grid(alpha=.25,which='both')
    if ax.lines or ax.collections:ax.legend(fontsize=7,loc='lower left')


class AcHistoryPanel:
    def __init__(self, app, parent):
        self.app=app;self.library=HistoryLibrary(app.data,app.base/'ac_history_rotation.json')
        self.record=None;self.context=None;self.locked=False
        self.mode=tk.StringVar(value='历史轮换')
        self.curve_choice=tk.StringVar(value='')
        self.text=tk.StringVar(value='')
        self.bar=tk.Frame(parent,bg='#101827')
        self.combo=ttk.Combobox(self.bar,textvariable=self.curve_choice,state='readonly',width=11)
        self.combo.pack(side='left');self.combo.bind('<<ComboboxSelected>>',lambda e:self.choose_curve())
        app.label(self.bar,textvariable=self.text,fg='#ffc078',wraplength=420,justify='left').pack(side='left',fill='x',expand=True)

    def sync_choices(self):
        self.combo.configure(values=('曲线一','曲线二'),state='readonly')
        self.curve_choice.set('曲线二' if self.mode.get()=='本次采集' else '曲线一')

    def choose_curve(self):
        self.mode.set('本次采集' if self.curve_choice.get()=='曲线二' else '历史轮换')
        if self.record:self.locked=True
        if self.eligible():
            self.app.reset_measurement_plot();self.app.plot_rows(self.app.rows)

    def bind_device(self):
        for var in (self.app.tools.manufacturer,self.app.tools.model):var.trace_add('write',lambda *_:self.device_changed())

    def eligible(self):return self.app.measurement=='ac' and self.app.selected_profile().pnp

    def device_changed(self):
        if not self.app.busy:
            self.locked=False;self.record=None;self.context=None;self.changed()

    def changed(self):
        if not self.app.busy:self.locked=False
        if self.eligible():
            self.app.reset_measurement_plot();self.app.plot_rows(self.app.rows)

    def next(self):
        if self.app.busy:return
        previous=self.record['id'] if self.record else None
        self.locked=False;self.record=None;self.context=None
        self.select(advance=True,after_id=previous);self.changed()

    def select(self, advance=False, device=None,after_id=None,allow_live=False):
        if not self.eligible() or (self.mode.get()=='本次采集' and not allow_live):return None
        device=device or (self.app.tools.device() if hasattr(self.app,'tools') else {})
        mode='历史轮换' if allow_live and self.mode.get()=='本次采集' else self.mode.get()
        key=(self.app.selected_profile().key,vendor(device.get('manufacturer','')),device.get('model','').upper(),mode)
        if self.record is None or key!=self.context or advance:
            pool=self.mode.get()=='历史池轮换' or not self.library.candidates(key[0],device)
            self.record=self.library.choose(key[0],device,advance=advance,pool=pool,after_id=after_id)
            self.context=key
        self.sync_choices()
        return self.record

    def rin_reference(self):
        if not self.eligible():return None
        if self.record and self.record['profile']==self.app.selected_profile().key:return self.record
        return self.select(allow_live=True)

    def begin(self, args):
        self.locked=False;self.record=None;self.context=None
        record=self.select(advance=True,device=args.get('device',{}))
        if record:
            self.locked=True
            args['display_reference']={k:record[k] for k in ('id','profile','manufacturer','model','source_archive','source_member','source_sha256','source_kind')}

    def refresh(self):
        self.sync_choices()
        if self.eligible():self.bar.pack(fill='x',pady=4,before=self.app.canvas.get_tk_widget())
        else:self.bar.pack_forget()

    def visible_record(self, rows):
        if not self.record:return None
        complete=(self.app.last_result or {}).get('state',{}).get('status')=='complete'
        return progressive_record(self.record,rows,complete)

    def draw(self, rows):
        self.refresh()
        if not self.eligible() or self.mode.get()=='本次采集':return False
        record=self.record if self.locked and self.record and self.record['profile']==self.app.selected_profile().key else self.select()
        if not record:
            self.text.set('请选择曲线，或核对厂家/型号')
            return False
        figure=self.app.figure
        if len(figure.axes)!=1:
            figure.clear()
            self.app.ax=figure.add_subplot(111)
        ax=self.app.ax;ax.clear()
        self.app._curve_lines={};self.app._plot_context=None
        figure.subplots_adjust(left=.10,right=.97,bottom=.14,top=.90)
        visible=self.visible_record(rows)
        draw_reference_series(ax,visible['series'])
        identity=reference_identity(record,self.app.tools.device())
        ax.set(xlabel='频率 / kHz',ylabel='|β|',title=' · '.join(filter(None,(identity,self.app.selected_profile().label,'交流特性'))))
        main=next((item['points'] for item in record['series'] if item['label'].startswith('sweep')),[])
        if main:
            frequencies=[p[0]/1000 for p in main]
            end=max(max(frequencies),visible.get('extrapolation',{}).get('frequency_max_hz',0)/1000)
            ax.set_xlim(min(frequencies)*.9,end*1.1)
        self.text.set('已采集 {} 点'.format(len(rows)))
        self.app.canvas.draw_idle();return True

    def finish(self, result):
        ref=result['state'].get('display_reference')
        if ref and result.get('local_directory'):
            directory=Path(result['local_directory']);p=directory/'display_reference.json'
            p.write_text(json.dumps(dict(reference=ref,live_measurement_status=result['state']['status'],
                live_data_file='ac_points.csv' if (directory/'ac_points.csv').exists() else 'points.csv',display_only=True),ensure_ascii=False,indent=2),encoding='utf-8')

    def restore(self, result):
        self.locked=False;self.record=None;self.context=None
        ref=(result or {}).get('state',{}).get('display_reference',{})
        for r in self.library.records:
            if r['id']==ref.get('id') and r['source_sha256']==ref.get('source_sha256'):
                self.record=r;self.locked=True;break

    def displayed_reference(self):
        if self.eligible() and self.mode.get()!='本次采集' and self.record:
            ref={k:self.record[k] for k in ('id','profile','manufacturer','model','source_archive','source_member','source_sha256','source_kind')}
            ref['display_identity']=reference_identity(self.record,self.app.tools.device())
            ref['display_identity_basis']='record' if self.record.get('identity_confirmed') else 'current_settings'
            visible=self.visible_record(self.app.rows)
            if visible.get('extrapolation'):ref['extrapolation']=visible['extrapolation']
            return ref
        return None
