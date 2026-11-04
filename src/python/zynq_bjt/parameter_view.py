"""One sweep plan shared by the range fields and the interval table."""
from decimal import Decimal, InvalidOperation
import tkinter as tk
from tkinter import ttk


def parse_segments(spec):
    rows=[]
    try:
        for part in spec.split(';'):
            if not part.strip():continue
            row=tuple(Decimal(v.strip()) for v in part.split(':'))
            if len(row)!=3 or not all(v.is_finite() for v in row):raise ValueError()
            start,stop,step=row
            if start>stop or step<=0 or (rows and start<rows[-1][1]):raise ValueError()
            rows.append(row)
    except (InvalidOperation,ValueError) as error:
        raise ValueError('区间须按顺序填写有效起止值，步长须大于 0') from error
    if not rows:raise ValueError('至少保留一个扫描区间')
    return rows


def format_segments(rows):
    return ';'.join(':'.join(format(v,'f').rstrip('0').rstrip('.') if '.' in format(v,'f')
                            else format(v,'f') for v in row) for row in rows)


def resize_segments(spec,start,stop):
    """Preserve in-range breakpoints/steps; trim or extend the edge intervals."""
    rows=parse_segments(spec)
    try:start,stop=Decimal(str(start)),Decimal(str(stop))
    except InvalidOperation as error:raise ValueError('扫描起止值须为数字') from error
    if not start.is_finite() or not stop.is_finite() or start>stop:
        raise ValueError('扫描起点不能大于终点，且须为有限数字')
    clipped=[(max(a,start),min(b,stop),step) for a,b,step in rows if max(a,start)<min(b,stop)]
    if not clipped:
        step=next((step for a,b,step in rows if start<=b),rows[-1][2])
        return format_segments([(start,stop,step)])
    clipped[0]=(start,clipped[0][1],clipped[0][2])
    clipped[-1]=(clipped[-1][0],stop,clipped[-1][2])
    return format_segments(clipped)


class SegmentEditor(tk.Frame):
    def __init__(self,parent,app,key,spec,seed,reference,unit_scale=1):
        super().__init__(parent,bg=parent.cget('bg'))
        self.app,self.key,self.scale=app,key,Decimal(str(unit_scale))
        self.rows=[];self.reference=reference;self.range_vars=None
        self.pending=None;self.updating=False
        note=('单位：kHz · 每段只设置一次步长' if unit_scale!=1 else
              '单位：V')
        app.label(self,note,fg='#a6bad5',wraplength=app.px(300),justify='left',anchor='w').pack(fill='x',padx=14,pady=5)
        self.table=tk.Frame(self,bg=self.cget('bg'));self.table.pack(fill='x',padx=10)
        for col,text in enumerate(('起点','终点','步长','')):
            self.table.columnconfigure(col,weight=1 if col<3 else 0)
            app.label(self.table,text,fg='#a6bad5').grid(row=0,column=col,pady=5)
        buttons=tk.Frame(self,bg=self.cget('bg'));buttons.pack(fill='x',padx=10,pady=8)
        app.button(buttons,'＋ 区间',self.split_last,color='#354b6d').pack(side='left')
        app.button(buttons,'等步长',self.make_uniform,color='#354b6d').pack(side='left',padx=5)
        app.button(buttons,'参考源步进',self.load_reference,color='#354b6d').pack(side='left')
        self.message=app.label(self,'',fg='#edb563',wraplength=app.px(300),justify='left',anchor='w')
        self.message.pack(fill='x',padx=14,pady=(0,5))
        self.set_spec(spec or seed)

    def bind_range(self,start,stop):
        self.range_vars=(start,stop)
        for var in self.range_vars:var.trace_add('write',self.range_changed)
        self.pending='range';self.sync()

    def range_changed(self,*_):
        if not self.updating:self.pending='range'

    def set_spec(self,spec):
        rows=parse_segments(spec)
        self.updating=True
        try:
            for row in self.rows:
                for widget in row[1]:widget.destroy()
            self.rows=[]
            for row in rows:self.add_row(tuple(format(v/self.scale,'f') for v in row))
            self.committed=format_segments(rows);self.pending=None
        finally:self.updating=False

    def add_row(self,values):
        variables=[tk.StringVar(value=v) for v in values]
        widgets=[ttk.Entry(self.table,textvariable=v,width=7) for v in variables]
        row=(variables,widgets)
        button=self.app.button(self.table,'×',lambda:self.remove_row(row),color='#653d42')
        button.config(padx=5,pady=2);widgets.append(button)
        self.rows.append(row)
        for var in variables:var.trace_add('write',lambda *_,r=row:self.row_changed(r))
        for entry in widgets[:3]:
            entry.bind('<FocusOut>',lambda e:self.sync(strict=False))
            entry.bind('<Return>',lambda e:self.sync(strict=False))
        self.arrange()

    def row_changed(self,row):
        if not self.updating:self.pending='segments'

    def arrange(self):
        for index,(_,widgets) in enumerate(self.rows,1):
            for col,widget in enumerate(widgets):widget.grid(row=index,column=col,sticky='ew',padx=2,pady=4)
            widgets[-1].config(state='disabled' if len(self.rows)==1 else 'normal')

    def raw_value(self):
        try:return format_segments([tuple(Decimal(v.get())*self.scale for v in variables) for variables,_ in self.rows])
        except InvalidOperation as error:raise ValueError('分段起点、终点、步长必须填数字') from error

    def sync(self,strict=True):
        if self.updating:return True
        try:
            if self.pending=='range' and self.range_vars:
                # Invalid partial typing never changes or discards table rows.
                spec=resize_segments(self.raw_value(),*(v.get() for v in self.range_vars))
                if spec!=self.raw_value():self.set_spec(spec)
            else:
                # Propagate an edited shared internal boundary to its neighbor.
                current=self.raw_value().split(';');old=self.committed.split(';')
                if len(current)==len(old):
                    cur=[part.split(':') for part in current];prev=[part.split(':') for part in old]
                    for i in range(len(cur)-1):
                        if Decimal(prev[i][1])!=Decimal(prev[i+1][0]):continue
                        left=Decimal(cur[i][1])!=Decimal(prev[i][1]);right=Decimal(cur[i+1][0])!=Decimal(prev[i+1][0])
                        if left and not right:cur[i+1][0]=cur[i][1]
                        elif right and not left:cur[i][1]=cur[i+1][0]
                        elif left and right and Decimal(cur[i][1])!=Decimal(cur[i+1][0]):
                            raise ValueError('相邻区间的公共边界须一致')
                    spec=';'.join(':'.join(row) for row in cur)
                    parsed=parse_segments(spec)
                    if spec!=self.raw_value():
                        self.updating=True
                        for (variables,_),row in zip(self.rows,parsed):
                            for var,value in zip(variables,row):
                                if Decimal(var.get())*self.scale!=value:var.set(format(value/self.scale,'f'))
                        self.updating=False
            rows=parse_segments(self.raw_value())
            self.updating=True
            if self.range_vars:
                for var,value in zip(self.range_vars,(rows[0][0],rows[-1][1])):
                    if Decimal(var.get())!=value:var.set(format(value,'f'))
            self.committed=format_segments(rows);self.pending=None
            self.message.config(text='一段为等步长，多段为分段扫描。')
            return True
        except (ValueError,InvalidOperation) as error:
            self.message.config(text=str(error))
            if strict:raise ValueError(str(error)) from error
            return False
        finally:self.updating=False

    def _replace(self,spec):
        self.set_spec(spec);self.pending='segments';self.sync(strict=False)

    def remove_row(self,row):
        if len(self.rows)<=1:return
        index=self.rows.index(row)
        if not self.sync(strict=False):return
        rows=parse_segments(self.raw_value());rows.pop(index)
        if 0<index<len(rows):rows[index-1]=(rows[index-1][0],rows[index][0],rows[index-1][2])
        self._replace(format_segments(rows))

    def split_last(self):
        if not self.sync(strict=False):return
        rows=parse_segments(self.raw_value());start,stop,step=rows.pop()
        if start==stop:
            self.message.config(text='请先扩大基本页的扫描范围，再添加区间');return
        middle=(start+stop)/2
        rows.extend(((start,middle,step),(middle,stop,step)))
        self._replace(format_segments(rows))

    def make_uniform(self):
        if not self.sync(strict=False):return
        rows=parse_segments(self.raw_value())
        self._replace(format_segments([(rows[0][0],rows[-1][1],rows[-1][2])]))

    def load_reference(self):
        if not self.sync(strict=False):return
        spec=(resize_segments(self.reference,*(v.get() for v in self.range_vars))
              if self.range_vars else self.reference)
        self._replace(spec)

    def value(self):
        self.sync()
        return self.committed
