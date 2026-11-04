"""Two-channel voltage table, using the board's full-rate ADC statistics."""
import csv
import json
from pathlib import Path
import time
import tkinter as tk


class MeterPanel:
    def __init__(self, app, parent):
        self.app = app
        self.running = False
        self.job = None
        self.last = None
        self.state = tk.StringVar(value='等待采集')
        self.info = tk.StringVar(value='单位 V  ·  DC / True RMS / AC RMS  ·  软件输入上限 2 V')
        self.values = {(r,c):tk.StringVar(value='—') for r in range(3) for c in range(2)}
        bar = tk.Frame(parent, bg='#101827'); bar.pack(fill='x', pady=(0,10))
        self.single_button = app.button(bar,'单次运行',lambda:self.start(False),color='#34608a')
        self.run_button = app.button(bar,'持续运行',lambda:self.start(True),color='#236c57')
        self.stop_button = app.button(bar,'停止采集',self.stop,color='#874a47')
        self.save_button = app.button(bar,'保存读数',self.save,color='#1b2a40')
        for button in (self.single_button,self.run_button,self.stop_button,self.save_button):
            button.pack(side='left',padx=(0,6))
        app.label(parent,textvariable=self.info,fg='#a6bad5',anchor='w').pack(fill='x',pady=(0,12))
        table = tk.Frame(parent,bg='#9cabbc',bd=1,relief='solid');table.pack(fill='x')
        self.table = table
        table.columnconfigure(0,weight=0,minsize=app.px(145))
        for col in (1,2): table.columnconfigure(col,weight=1,uniform='meter')
        for col,text in enumerate(('电压 / V','RX1 / CH1','RX2 / CH2')):
            tk.Label(table,text=text,bg='#edf2f8',fg='#24364d',font=('Microsoft YaHei UI',13,'bold'),pady=12).grid(row=0,column=col,sticky='nsew',padx=1,pady=1)
        for row,label in enumerate(('直流 DC','True RMS','AC RMS')):
            tk.Label(table,text=label,bg='#f1f5fa',fg='#24364d',font=('Microsoft YaHei UI',13,'bold'),padx=10,pady=22).grid(row=row+1,column=0,sticky='nsew',padx=1,pady=1)
            for col in range(2):
                tk.Label(table,textvariable=self.values[row,col],bg='white',fg='#174a77',font=('Consolas',23,'bold'),padx=12,pady=22).grid(row=row+1,column=col+1,sticky='nsew',padx=1,pady=1)
        app.label(parent,textvariable=self.state,fg='#a6bad5',anchor='w').pack(fill='x',pady=12)
        app.label(parent,'True RMS 包含直流；AC RMS 去除直流。RMS 按本次连续采样窗计算。',fg='#a6bad5',anchor='w').pack(fill='x')

    def controls(self):
        app = self.app
        ready = bool(app.transport and app.transport.alive and app.last_status and app.last_status.get('initialized'))
        for button in (self.single_button,self.run_button):
            button.config(state='normal' if ready and not app.busy else 'disabled')
        self.stop_button.config(state='normal' if self.running else 'disabled')
        self.save_button.config(state='normal' if self.last else 'disabled')

    def start(self, continuous):
        app = self.app
        if app.busy or not app.transport or not app.last_status or not app.last_status.get('initialized'): return
        self.stop()
        self.running = continuous
        self.state.set('正在采集…')
        app.submit('meter')

    def stop(self, reason='停止 · 保留最近读数'):
        self.running = False
        if self.job is not None:
            self.app.root.after_cancel(self.job)
            self.job = None
        self.state.set(reason)
        self.controls()

    def receive(self, value):
        self.last = value
        errors = []
        for col,ch in enumerate(value['channels']):
            for row,key in enumerate(('dc_v','true_rms_v','ac_rms_v')):
                v = ch[key]
                self.values[row,col].set('—' if v is None else '{:.5f}'.format(v))
            if ch.get('error'): errors.append('RX{}：{}'.format(col+1,ch['error']))
        stamp = time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(value['completed_at']))
        self.info.set('单位 V  ·  采样窗 {:g} ms  ·  {:g} MSPS  ·  软件输入上限 2 V'.format(value['window_ms'][0],value['sample_rates_hz'][0]/1e6))
        self.state.set(('模拟 · ' if value['simulated'] else '')+stamp+'  ·  '+('；'.join(errors) if errors else '已更新'))
        self.controls()
        if self.running: self.job = self.app.root.after(400,self.next_capture)

    def next_capture(self):
        self.job = None
        if self.running and not self.app.busy: self.app.submit('meter')

    def save(self):
        if not self.last: return
        from .result_paths import create_run
        folder = create_run(self.app.results,'instrument','meter')
        (folder/'reading.json').write_text(json.dumps(self.last,ensure_ascii=False,indent=2),encoding='utf-8')
        with (folder/'reading.csv').open('w',newline='',encoding='utf-8-sig') as stream:
            writer=csv.writer(stream);writer.writerow(['channel','DC_V','True_RMS_V','AC_RMS_V','error'])
            for ch,row in enumerate(self.last['channels']):
                writer.writerow(['RX{}'.format(ch+1),row['dc_v'],row['true_rms_v'],row['ac_rms_v'],row['error']])
        self.app.log('电压表读数已保存：'+str(folder))
