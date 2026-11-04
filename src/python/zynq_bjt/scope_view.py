"""Instrument-style Tk scope for bounded, independently clocked RX snapshots."""
import math
import time
import csv
from collections import deque
import tkinter as tk
from tkinter import ttk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.ticker import AutoMinorLocator

from .scope_display import reference_channels, edge_positions, measure, nice_step, sample_at, finite, spectrum

BG = '#101827'
PANEL = '#1b2a40'
SCREEN = '#08121e'
FG = '#edf3ff'
MUTED = '#a6bad5'
COLORS = ('#ffda55', '#51d5f5')


def engineering(value, unit=''):
    if value is None or not math.isfinite(value):
        return '—'
    for scale, prefix in ((1e6, 'M'), (1e3, 'k'), (1, ''), (1e-3, 'm'), (1e-6, 'µ'), (1e-9, 'n')):
        if abs(value) >= scale or scale == 1e-9 or value == 0:
            return '{:.4g} {}{}'.format(value/scale, prefix if value else '', unit).strip()


class ScopePanel:
    def __init__(self, app, parent, scroll_class):
        self.app = app
        self.frame = None
        self.converted = []
        self.accepting = False
        self.single_pending = False
        self.trigger_time = None
        self.acquired_trigger_time = None
        self.acquisition_state = 'STOP'
        self.capture_job = None
        self.waiting = False
        self.last_received_at = None
        self.refresh_interval = None
        self._layout_key = None
        self._full_frame_settings = None
        self.auto_on_first_frame = False
        self.history = deque(maxlen=64)
        self.history_key = None
        self.display_mode = tk.StringVar(value='时域')
        self.persistence = tk.StringVar(value='关闭')
        self.fft_window = tk.StringVar(value='平顶（幅值）')
        self.fft_scale = tk.StringVar(value='dB')
        self.fft_max_khz = tk.StringVar(value='0')
        self.fft_remove_dc = tk.BooleanVar(value=True)
        self.cursor_times = [None, None]
        self.units = tk.StringVar(value='接口电压 V')
        self.timebase = tk.StringVar(value='2')
        self.window_us = tk.StringVar(value='1000')
        self.sample_count = tk.StringVar(value='4096')
        self.sample_stride = tk.StringVar(value='自动窗口')
        self.adc_clock_mhz = tk.StringVar(value='50')
        self.position = tk.StringVar(value='0')
        self.mode = tk.StringVar(value='Auto 自动')
        self.source = tk.StringVar(value='RX1')
        self.slope = tk.StringVar(value='上升沿')
        self.level = tk.StringVar(value='0')
        self.visible = [tk.BooleanVar(value=True) for _ in range(2)]
        self.scale = [tk.StringVar(value='0.2') for _ in range(2)]
        self.center = [tk.StringVar(value='0') for _ in range(2)]
        self.cursors = tk.BooleanVar(value=False)
        self.cursor_source = tk.StringVar(value='RX1')
        self.state = tk.StringVar(value='STOP  ·  等待采集')
        self.info = tk.StringVar(value='点数 / 抽取倍率可调 · 分帧采集')
        self.cursor_text = tk.StringVar(value='游标关闭')
        self.badges = [tk.StringVar() for _ in range(2)]
        self.stats = [tk.StringVar(value='RX{}  ·  等待采集'.format(c+1)) for c in range(2)]
        self.basis = tk.StringVar(value='电压依据：等待采集')

        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill='x', pady=(0, 8))
        self.run_button = app.button(bar, '运行 RUN', self.run, color='#236c57')
        self.single_button = app.button(bar, '单次 SINGLE', self.single, color='#34608a')
        self.stop_button = app.button(bar, '停止取帧', self.stop, color='#874a47')
        self.auto_button = app.button(bar, '自动设置', self.autoset, color='#6b592c')
        self.save_button = app.button(bar, '保存 CSV / 图像', app.save_frame, color=PANEL)
        for button in (self.run_button, self.single_button, self.stop_button, self.auto_button, self.save_button):
            button.pack(side='left', padx=(0, 6))

        controls = scroll_class(parent, width=app.px(315))
        controls.pack(side='right', fill='y', padx=(10, 0))
        controls.pack_propagate(False)
        self.controls_panel = controls
        side = controls.inner
        side.columnconfigure(1, weight=1)
        row = 0
        self.control_tabs=ttk.Notebook(side)
        self.control_tabs.grid(row=0,column=0,columnspan=2,sticky='nsew')
        self.control_sections={}
        def section(name):
            nonlocal side,row
            side=tk.Frame(self.control_tabs,bg=PANEL)
            side.columnconfigure(1,weight=1)
            self.control_tabs.add(side,text=name)
            self.control_sections[name]=side
            row=0

        def heading(text, color=MUTED):
            nonlocal row
            app.label(side, text, fg=color, font=('Microsoft YaHei UI', 10, 'bold')).grid(
                row=row, column=0, columnspan=2, sticky='w', padx=10, pady=(12, 5))
            row += 1

        def field(text, variable, choices=None, command=None):
            nonlocal row
            app.label(side, text, fg=MUTED).grid(row=row, column=0, sticky='w', padx=(10, 4), pady=3)
            if choices:
                widget = ttk.Combobox(side, textvariable=variable, values=choices, width=12, state='readonly')
                widget.bind('<<ComboboxSelected>>', lambda e: (command or self.redraw)())
            else:
                widget = ttk.Entry(side, textvariable=variable, width=12)
                widget.bind('<Return>', lambda e: (command or self.redraw)())
                widget.bind('<FocusOut>', lambda e: (command or self.redraw)())
            widget.grid(row=row, column=1, sticky='ew', padx=(0, 10), pady=3)
            row += 1
            return widget

        section('显示')
        heading('显示 DISPLAY')
        field('视图', self.display_mode, ('时域', 'FFT 频域'))
        field('显示单位', self.units, ('接口电压 V', 'ADC 原始码'), self.change_units)
        field('余辉保留', self.persistence, ('关闭', '8 帧', '24 帧', '64 帧'), self.clear_history)
        app.button(side, '清除余辉', self.clear_history, color='#354b6d').grid(row=row, column=0, columnspan=2, sticky='ew', padx=10, pady=4)
        row += 1
        field('FFT 窗', self.fft_window, ('平顶（幅值）','Hann', '矩形'))
        field('FFT 幅度', self.fft_scale, ('dB', 'RMS'))
        field('FFT 上限 kHz（0=全频）', self.fft_max_khz)
        tk.Checkbutton(side, text='FFT 去直流', variable=self.fft_remove_dc, command=self.redraw,
                       bg=PANEL, fg=FG, selectcolor=SCREEN).grid(row=row,column=0,columnspan=2,sticky='w',padx=6)
        row += 1
        section('水平')
        heading('水平 HORIZONTAL')
        self.adc_clock_choice=field('物理时钟 MHz',self.adc_clock_mhz,('50',),lambda:None)
        self.adc_clock_button=app.button(side,'应用时钟（重新自检）',self.apply_adc_clock,color='#354b6d')
        self.adc_clock_button.grid(row=row,column=0,columnspan=2,sticky='ew',padx=10,pady=4)
        row+=1
        field('点数 / 路', self.sample_count, ('256','512','1024','2048','4096'), self.window_changed)
        field('抽取倍率', self.sample_stride, ('自动窗口','1','2','4','5','10','20','25','50','100','128','250','256'), self.window_changed)
        field('自动窗口 µs', self.window_us, ('20', '100', '400', '1000', '5000','10000','20000'), self.window_changed)
        field('时基 µs/div', self.timebase, ('.02', '.05', '.1', '.2', '.5', '1', '2', '5', '10', '20', '40', '100', '500'))
        field('水平位置 µs', self.position)
        app.button(side, '全帧显示', self.fit_time, color='#354b6d').grid(row=row, column=0, columnspan=2, sticky='ew', padx=10, pady=4)
        row += 1
        heading('采集说明')
        app.label(side, '点数与抽取倍率决定记录时长。\n倍率1保留原始采样率；自动窗口自动选倍率。\n抽取无抗混叠滤波；FFT建议至少记录6个周期。\n两路首点不同步。', fg=MUTED,
                  justify='left', wraplength=app.px(235), font=('Microsoft YaHei UI', 9)).grid(row=row, column=0, columnspan=2, sticky='w', padx=10, pady=(5, 15))

        self.channel_fields=[[],[]]
        for c in range(2):
            section('RX{}'.format(c+1))
            heading('RX{} / ADC {} · 垂直参数'.format(c+1,'B' if c==0 else 'A'),COLORS[c])
            tk.Checkbutton(side, text='显示 RX{} 波形'.format(c+1), variable=self.visible[c],
                           command=self.redraw, bg=PANEL, fg=COLORS[c], selectcolor=SCREEN,
                           activebackground=PANEL, activeforeground=COLORS[c]).grid(row=row, column=0, columnspan=2, sticky='w', padx=6, pady=(8, 0))
            row += 1
            field('每格 V / code', self.scale[c]);self.channel_fields[c].extend(side.grid_slaves(row=row-1))
            field('中心 V / code', self.center[c]);self.channel_fields[c].extend(side.grid_slaves(row=row-1))
        section('触发')
        heading('触发 TRIGGER · 帧内定位')
        field('模式', self.mode, ('Auto 自动', 'Normal 正常'))
        field('源', self.source, ('RX1', 'RX2'), self.update_trigger)
        field('边沿', self.slope, ('上升沿', '下降沿'), self.update_trigger)
        field('电平 V / code', self.level, command=self.update_trigger)
        app.button(side, '电平置中 50%', self.midlevel, color='#354b6d').grid(row=row, column=0, columnspan=2, sticky='ew', padx=10, pady=4)
        row += 1
        section('游标')
        heading('游标 CURSORS')
        tk.Checkbutton(side, text='启用 A / B 时间游标', variable=self.cursors, command=self.redraw,
                       bg=PANEL, fg=FG, selectcolor=SCREEN, activebackground=PANEL,
                       activeforeground=FG).grid(row=row, column=0, columnspan=2, sticky='w', padx=6)
        row += 1
        field('读数通道', self.cursor_source, ('RX1', 'RX2'))

        display = tk.Frame(parent, bg=SCREEN)
        display.pack(side='left', fill='both', expand=True)
        status = tk.Frame(display, bg=SCREEN, padx=10, pady=8)
        status.pack(fill='x')
        app.label(status, textvariable=self.state, fg='#72e3aa', anchor='w').pack(side='left')
        app.label(status, textvariable=self.info, fg=MUTED, anchor='e').pack(side='right')
        footer = tk.Frame(display, bg=SCREEN, padx=10, pady=5)
        footer.pack(side='bottom', fill='x')
        from .metric_strip import MetricStrip
        self.metric_strips=[];self.channel_readouts=[]
        for c in range(2):
            channel=tk.Frame(footer,bg=SCREEN);channel.pack(fill='x');self.channel_readouts.append(channel)
            app.label(channel, textvariable=self.badges[c], fg=COLORS[c], anchor='center',
                      font=('Microsoft YaHei UI', 10, 'bold')).pack(fill='x', pady=(3, 0))
            strip=MetricStrip(channel,COLORS[c]);strip.pack(fill='x');strip.set([('RX'+str(c+1),'等待采集')]);self.metric_strips.append(strip)
        self.cursor_strip=MetricStrip(footer,'#d7b7ff');self.cursor_strip.pack(fill='x',pady=3)
        self.cursor_text.trace_add('write',lambda *_:self.cursor_strip.set([('游标',self.cursor_text.get().split(' · ')[0])]) if '\n' not in self.cursor_text.get() else None)
        self.figure = Figure(figsize=(6, 3), dpi=100, facecolor=SCREEN)
        self.ax = self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=.08, right=.97, bottom=.17, top=.89)
        self.canvas = FigureCanvasTkAgg(self.figure, display)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        self.canvas.mpl_connect('button_press_event', self.click_cursor)
        self.canvas.mpl_connect('scroll_event', self.zoom_time)
        self.redraw()

    @property
    def raw(self):
        return self.units.get() == 'ADC 原始码'

    def settings(self):
        return dict(units=self.units.get(), window_us=float(self.window_us.get()), timebase_us=float(self.timebase.get()),
                    sample_count=int(self.sample_count.get()), sample_stride=self.sample_stride.get(),
                    position_us=float(self.position.get()), scale=[float(v.get()) for v in self.scale],
                    center=[float(v.get()) for v in self.center], visible=[v.get() for v in self.visible],
                    trigger_mode=self.mode.get(), trigger_source=self.source.get(),
                    trigger_slope=self.slope.get(), trigger_level=float(self.level.get()),
                    trigger_time_s=self.trigger_time, trigger_kind='software_in_frame',
                    acquisition_trigger_time_s=self.acquired_trigger_time,
                    starts_aligned=False, acquisition_state=self.acquisition_state,
                    cursors_enabled=self.cursors.get(), cursor_source=self.cursor_source.get(),
                    cursor_times_us=self.cursor_times, display_mode=self.display_mode.get(),
                    persistence=self.persistence.get(), fft_window=self.fft_window.get(),
                    fft_scale=self.fft_scale.get(), fft_remove_dc=self.fft_remove_dc.get(),
                    fft_max_khz=float(self.fft_max_khz.get()))

    def validate(self):
        maximum=float(self.fft_max_khz.get())
        if not math.isfinite(maximum) or maximum<0:
            raise ValueError('FFT 频率上限须为非负有限数字')
        values = [float(v.get()) for v in (self.timebase, self.position, self.level, *self.scale, *self.center)]
        if not all(math.isfinite(v) for v in values) or values[0] <= 0 or any(float(v.get()) <= 0 for v in self.scale):
            raise ValueError('时基、每格刻度必须为正数；位置和电平必须为有限数字')

    def controls(self):
        ready = bool(self.app.transport and self.app.transport.alive and self.app.last_status and self.app.last_status.get('initialized'))
        for button in (self.run_button, self.single_button):
            button.config(state='normal' if ready and not self.app.busy else 'disabled')
        self.stop_button.config(state='normal' if self.accepting else 'disabled')
        maximum=(self.app.last_status or {}).get('adc_max_rate_hz',50e6)
        self.adc_clock_choice['values']=tuple(name for name,divider in self.clock_options().items() if 1e9/divider<=maximum+1)
        self.adc_clock_button.config(state='normal' if ready and not self.app.busy else 'disabled')
        for button in (self.auto_button, self.save_button):
            button.config(state='normal' if self.frame else 'disabled')

    def arm(self, single):
        if self.app.busy or not self.app.transport:
            return
        try:
            self.validate()
        except ValueError as error:
            self.app.error(error)
            return
        self.auto_on_first_frame = self.frame is None
        self.last_received_at = None
        self.accepting = True
        self.single_pending = single
        self.app.live = True
        self.acquisition_state = 'SINGLE WAIT' if single else 'RUN'
        self.state.set(self.acquisition_state+'  ·  等待帧内边沿')
        self.app.submit('capture', self.capture_request())

    def run(self):
        self.arm(False)

    def single(self):
        self.arm(True)

    def stop(self, reason='STOP'):
        if self.capture_job is not None:
            self.app.root.after_cancel(self.capture_job)
            self.capture_job = None
        self.accepting = False
        self.waiting = False
        self.single_pending = False
        self.app.live = False
        self.acquisition_state = reason
        self.state.set(reason+'  ·  '+('保留帧 #{}'.format(self.frame['sequence']) if self.frame else '等待采集'))
        self.controls()
        if self.frame: self.redraw()

    def schedule(self):
        if self.capture_job is not None:
            self.app.root.after_cancel(self.capture_job)
        self.capture_job = self.app.root.after(50, self.next_capture) if self.app.live else None

    def next_capture(self):
        self.capture_job = None
        if self.app.live and self.accepting and not self.app.busy:
            self.app.submit('capture', self.capture_request())

    def capture_request(self):
        result = dict(window_us=float(self.window_us.get()),sample_count=int(self.sample_count.get()))
        if self.sample_stride.get()!='自动窗口': result['sample_stride']=int(self.sample_stride.get())
        return result

    @staticmethod
    def clock_options():return {'50':20,'62.5':16,'83.333':12,'100':10,'125':8}

    def apply_adc_clock(self):
        self.stop();self.app.meter.stop()
        self.app.submit('adc_clock',{'adc_divider':self.clock_options()[self.adc_clock_mhz.get()]})

    def clock_applied(self,status):
        self.frame=None;self.converted=[];self.app.last_frame=None;self.history.clear()
        rate=min(status.get('sample_rates_hz') or [50e6])
        self.adc_clock_mhz.set(min(self.clock_options(),key=lambda name:abs(1e9/self.clock_options()[name]-rate)))
        self.units.set('ADC 原始码' if rate>51e6 else '接口电压 V')
        self.change_units();self.state.set('STOP · 时钟已应用，等待重新采集')

    def fft_window_key(self):
        return {'平顶（幅值）':'flattop','Hann':'hann','矩形':'rectangular'}[self.fft_window.get()]

    def window_changed(self):
        self.history.clear()
        self.auto_on_first_frame = True
        self.redraw()

    def values(self, converted):
        return [ch['codes'] if self.raw else ch['reference_volts'] for ch in converted]

    def locate(self, frame, converted):
        c = int(self.source.get()[-1])-1
        values = self.values(converted)[c]
        # A clipped/invalid trigger source cannot qualify a Normal/Single frame.
        if converted[c]['overrange'] or not all(finite(v) for v in values):
            return None
        span = max(values)-min(values)
        hits = edge_positions(values, float(self.level.get()), self.slope.get() == '上升沿', span*.02)
        if not hits:
            return None
        # Prefer an edge with enough recorded context for the left quarter screen.
        desired = float(self.timebase.get())*1e-6*2.5*frame['sample_rates_hz'][c]
        hit = next((h for h in hits if h >= desired), hits[0])
        return hit/frame['sample_rates_hz'][c]

    def receive(self, frame):
        if not self.accepting:
            return False  # Stop freezes immediately, even if a worker is finishing.
        try:
            self.validate()
        except ValueError as error:
            self.stop('参数无效'); self.app.error(error)
            return False
        converted = reference_channels(frame, self.app.scope_calibration)
        trigger = self.locate(frame, converted)
        if trigger is None and (self.single_pending or self.mode.get().startswith('Normal')):
            self.waiting = True
            self.state.set(('SINGLE WAIT' if self.single_pending else 'WAIT')+'  ·  无有效边沿，保留上一帧')
            return False
        self.waiting = False
        now = time.monotonic()
        self.refresh_interval = now-self.last_received_at if self.last_received_at is not None else None
        self.last_received_at = now
        self.frame = frame
        self.converted = converted
        self.trigger_time = trigger
        self.acquired_trigger_time = trigger
        key = (tuple(frame['sample_rates_hz']),len(frame['words'][0]), frame.get('sample_stride', 1), frame['simulated'],
               self.raw, self.source.get(), self.slope.get(), self.level.get(), self.mode.get())
        if key != self.history_key:
            self.history.clear()
            self.history_key = key
        self.history.append((frame, converted, trigger))
        self.app.last_frame = frame
        self.acquisition_state = 'TRIG’D' if trigger is not None else 'AUTO · 未触发'
        if self.single_pending:
            self.stop('SINGLE 完成')
        if self.auto_on_first_frame:
            self.auto_on_first_frame = False
            self.autoset()
        elif self._full_frame_settings == (self.timebase.get(), self.position.get()):
            self.fit_time()
        else:
            self._full_frame_settings = None
            self.redraw()
        return True

    def midlevel(self):
        if not self.frame:
            return
        c = int(self.source.get()[-1])-1
        values = [v for v in self.values(self.converted)[c] if finite(v)]
        if values:
            self.level.set('{:.7g}'.format((min(values)+max(values))/2))
        self.update_trigger()

    def update_trigger(self):
        self.history.clear()
        try:
            self.validate()
            if self.frame:
                self.trigger_time = self.locate(self.frame, self.converted)
        except (ValueError, tk.TclError):
            pass
        self.redraw()

    def fit_time(self):
        if self.frame:
            duration = max((len(w)-1)/r for w, r in zip(self.frame['words'], self.frame['sample_rates_hz']))
            self.timebase.set('{:.7g}'.format(duration*1e6/10))
            # Keep the entire recorded frame visible, including after triggering.
            span = float(self.timebase.get())*1e-6*10
            self.position.set('{:.7g}'.format((span*.25-(self.trigger_time or 0))*1e6 if self.trigger_time is not None else 0))
            self._full_frame_settings = (self.timebase.get(), self.position.get())
        self.redraw()

    def autoset(self):
        if not self.frame:
            return
        if not any(v.get() for v in self.visible):
            self.visible[0].set(True)
        values_by_channel=self.values(self.converted)
        periodic={}
        for c, values in enumerate(values_by_channel):
            if not self.visible[c].get():continue
            valid = [v for v in values if finite(v)]
            if valid:
                lo, hi = min(valid), max(valid)
                self.scale[c].set('{:.7g}'.format(nice_step(max((hi-lo)/6, 1 if self.raw else .001))))
                self.center[c].set('{:.7g}'.format((hi+lo)/2))
            stats=measure(values,self.frame['sample_rates_hz'][c],invalid=bool(self.converted[c]['overrange']),noise_floor=32 if self.raw else .002)
            if stats['period'] is not None:periodic[c]=stats['period']
        source=int(self.source.get()[-1])-1
        if source not in periodic:
            source=next(iter(periodic),next(c for c,v in enumerate(self.visible) if v.get()))
        self.source.set('RX{}'.format(source+1))
        period=periodic.get(source)
        duration=(len(self.frame['words'][source])-1)/self.frame['sample_rates_hz'][source]
        if period is not None and duration>=3*period:
            # Frame length is for acquisition/FFT; autoset shows four cycles.
            self.timebase.set('{:.3g}'.format(min(4*period,duration)*1e5))
            self.position.set('0')
            self._full_frame_settings=None
            self.midlevel()
        else:
            self.midlevel()
            self.fit_time()

    def change_units(self):
        self.history.clear()
        for c in range(2):
            self.scale[c].set('8192' if self.raw else '.2')
            self.center[c].set('32768' if self.raw else '0')
        self.level.set('32768' if self.raw else '0')
        self.cursor_times = [None, None]
        self.autoset() if self.frame else self.redraw()

    def zoom_time(self, event):
        if event.inaxes != self.ax or self.display_mode.get() != '时域':
            return
        choices = [.02, .05, .1, .2, .5, 1, 2, 5, 10]
        current = float(self.timebase.get())
        options = [x for x in choices if x < current*.999] if event.button == 'up' else [x for x in choices if x > current*1.001]
        if options:
            self.timebase.set(str(max(options) if event.button == 'up' else min(options)))
            self.redraw()

    def click_cursor(self, event):
        if event.inaxes != self.ax or self.display_mode.get() != '时域' or not self.cursors.get() or not self.frame:
            return
        if event.button not in (1,3) or event.xdata is None:return
        index = 0 if event.button == 1 else 1
        self.cursor_times[index] = event.xdata
        self.redraw()

    def sync_visibility(self):
        show_cursor=self.cursors.get() and self.display_mode.get()=='时域' and self.visible[int(self.cursor_source.get()[-1])-1].get()
        if show_cursor:self.cursor_strip.pack(fill='x',pady=3)
        else:self.cursor_strip.pack_forget()
        for c,frame in enumerate(self.channel_readouts):
            enabled=self.visible[c].get()
            for widget in self.channel_fields[c]:
                if enabled:widget.grid()
                else:widget.grid_remove()
            if enabled:
                before=next((other for other in self.channel_readouts[c+1:]+[self.cursor_strip] if other.winfo_manager()),None)
                frame.pack(fill='x',**({'before':before} if before is not None else {}))
            else:
                frame.pack_forget();self.badges[c].set('');self.stats[c].set('');self.metric_strips[c].set([])

    def redraw(self):
        self.sync_visibility()
        try:
            self.validate()
        except (ValueError, tk.TclError):
            self.state.set('参数无效 · 时基 / 每格须为正数，按 Enter 应用')
            return
        if self.display_mode.get() == 'FFT 频域':
            self.draw_fft()
            return
        ax = self.ax
        layout_key = (self.raw, self.timebase.get(), self.position.get(), self.trigger_time is not None)
        rebuild = layout_key != self._layout_key
        self._layout_key = layout_key
        if not rebuild:
            for artist in list(ax.lines)[1:] + list(ax.texts) + list(ax.patches): artist.remove()
        if rebuild:
            ax.clear()
        span = float(self.timebase.get())*10
        origin = float(self.position.get())-(span*.25 if self.trigger_time is not None else 0)
        if rebuild:
            ax.set_facecolor(SCREEN)
            ax.set_ylim(-4, 4)
            ax.set_yticks(range(-4, 5))
            ax.set_yticklabels([])
            ax.tick_params(colors=MUTED, labelsize=8, length=0)
            for spine in ax.spines.values():
                spine.set_color('#42566c')
            ax.grid(color='#34465a', linewidth=.65)
            ax.xaxis.set_minor_locator(AutoMinorLocator(5))
            ax.yaxis.set_minor_locator(AutoMinorLocator(5))
            ax.grid(which='minor', color='#243345', linewidth=.3, linestyle=':')
            ax.axhline(0, color='#6b8095', linewidth=.7)
            ax.set_xlim(origin, origin+span)
            ax.set_xticks([origin+i*span/10 for i in range(11)])
            ax.set_xlabel('时间 / µs   ·   滚轮调时基', color=MUTED, fontsize=9)
        unit = 'code' if self.raw else 'V'
        for c in range(2):
            if not self.visible[c].get():continue
            self.badges[c].set('RX{}  {}  {} /div  ·  中心 {}'.format(c+1, '●' if self.visible[c].get() else '关闭', engineering(float(self.scale[c].get()),unit), engineering(float(self.center[c].get()),unit)))
        if not self.frame:
            ax.text(.5, .5, '等待采集\n选择离线模拟 → 连接 → 初始化 → 运行', ha='center', va='center', color=MUTED, transform=ax.transAxes)
            self.canvas.draw_idle()
            return
        frame = self.frame
        simulated = frame['simulated']
        if not self.waiting:
            self.state.set(('模拟 · ' if simulated else '实采 · ')+self.acquisition_state+'  #'+str(frame['sequence']))
        duration_us = min((len(w)-1)/r for w,r in zip(frame['words'],frame['sample_rates_hz']))*1e6
        refresh = ' | {:.1f} 帧/s'.format(1/self.refresh_interval) if self.refresh_interval and self.accepting else ''
        count=0 if self.persistence.get()=='关闭' else int(self.persistence.get().split()[0])
        kept=min(count,max(1,len(self.history))) if count else 0
        persistence=' | 余晖 {}/{} 帧'.format(kept,count) if count else ' | 余晖关闭'
        self.info.set('{} 点 | {:.2f} µs 实采窗口{}{}'.format(len(frame['words'][0]),duration_us,refresh,persistence))
        end_us = duration_us-(self.trigger_time or 0)*1e6
        start_us = -(self.trigger_time or 0)*1e6
        if origin < start_us:
            ax.axvspan(origin,min(start_us,origin+span),color='#42566c',alpha=.20)
        if origin+span > end_us+max(1e6/r for r in frame['sample_rates_hz']):
            ax.axvspan(max(end_us,origin),origin+span,color='#42566c',alpha=.20)
            ax.text(.99,.04,'阴影区无采样数据',transform=ax.transAxes,ha='right',color=MUTED,fontsize=8)
        ax.set_title(('模拟 / ' if simulated else '实采 / ')+'{} /div   ·   {} {} @ {} {}   ·   帧内定位'.format(engineering(float(self.timebase.get())*1e-6, 's'),
                     self.source.get(), '↗' if self.slope.get() == '上升沿' else '↘', engineering(float(self.level.get()),unit), ''), color=FG, fontsize=9, loc='left')
        all_values = self.values(self.converted)
        for c, values in enumerate(all_values):
            if not self.visible[c].get():continue
            converted = self.converted[c]
            rate = frame['sample_rates_hz'][c]
            scale, center = float(self.scale[c].get()), float(self.center[c].get())
            if self.visible[c].get():
                count = 0 if self.persistence.get()=='关闭' else int(self.persistence.get().split()[0])
                previous = list(self.history)[:-1][-(count-1):] if count else []
                for index, (old_frame, old_converted, old_trigger) in enumerate(previous):
                    if old_converted[c]['overrange']: continue
                    old_values = self.values(old_converted)[c]
                    old_rate = old_frame['sample_rates_hz'][c]
                    old_times = [(i/old_rate-(old_trigger or 0))*1e6 for i in range(len(old_values))]
                    old_ys = [(v-center)/scale if finite(v) else float('nan') for v in old_values]
                    ax.plot(old_times, old_ys, color=COLORS[c], linewidth=.7,
                            alpha=.04+.30*(index+1)/max(1,len(previous)), clip_on=True)
                times = [(i/rate-(self.trigger_time or 0))*1e6 for i in range(len(values))]
                ys = [(v-center)/scale if finite(v) else float('nan') for v in values]
                ax.plot(times, ys, color=COLORS[c], linewidth=1.2, clip_on=True)
                zero = -center/scale
                if -4 <= zero <= 4:
                    ax.text(.005+c*.04, zero, '{}>'.format(c+1), color=COLORS[c], transform=ax.get_yaxis_transform(), va='center', fontsize=9)
                if any(finite(y) and abs(y) > 4 and origin <= t <= origin+span for t, y in zip(times, ys)):
                    self.badges[c].set(self.badges[c].get()+'  · 超出屏幕')
            stats = measure(values, rate, invalid=bool(converted['overrange']), noise_floor=32 if self.raw else .002)
            self.stats[c].set('帧内 Vpp {}   均值 {}   RMS {}   频率 {}\nMin {}   Max {}   AC RMS {}   OR {}'.format(
                *[engineering(stats[k], unit) for k in ('vpp', 'mean', 'rms')], engineering(stats['frequency'], 'Hz'),
                *[engineering(stats[k], unit) for k in ('min', 'max', 'ac_rms')], converted['overrange']))
            self.metric_strips[c].set([(label,engineering(stats[key],'Hz' if key=='frequency' else unit)) for label,key in
                [('帧内 Vpp','vpp'),('均值','mean'),('RMS','rms'),('频率','frequency'),('最小','min'),('最大','max'),('AC RMS','ac_rms')]]+[('过量程',str(converted['overrange']))])
        if self.trigger_time is not None:
            ax.axvline(0, color='#ffaf60', linewidth=.8, linestyle='--')
            ax.text(0, 3.85, 'T', color='#ffaf60', va='top', ha='center', clip_on=True)
        c = int(self.source.get()[-1])-1
        ty = (float(self.level.get())-float(self.center[c].get()))/float(self.scale[c].get())
        if self.visible[c].get() and -4 <= ty <= 4:
            ax.axhline(ty, color=COLORS[c], linewidth=.6, linestyle='--', alpha=.6)
        self.draw_cursors(all_values)
        basis = '模拟数据，仅演示。' if simulated else '接口电压按各路 DC 校准表换算；交流幅值不代表完整交流校准。'
        if not simulated:
            basis += ' '.join('RX{}：{}'.format(c+1, '发生器标称 DC' if ch['nominal_dc_calibrated'] else
                              '采样率不匹配' if ch['voltage_basis'] == 'profile_rate_mismatch' else
                              'DC 校准线性外推' if ch['voltage_basis'] == 'linear_extrapolation' else '历史参考表换算')
                              for c, ch in enumerate(self.converted))
        invalid = ['RX{} 无效 {} 点'.format(c+1, ch['invalid_samples']) for c, ch in enumerate(self.converted) if ch['invalid_samples']]
        stride=frame.get('sample_stride',1)
        sampling=' 记录间隔×{}，有效采样率{}；10 kHz约{:.2f}周期。'.format(stride,engineering(min(frame['sample_rates_hz']),'Sa/s'),duration_us/100)
        if stride>1: sampling+=' 无抗混叠滤波，高频请切20 µs短窗口。'
        self.basis.set(basis+sampling+' 两路首点不同步，不比较相位。'+(' / '.join(invalid)))
        self.canvas.draw_idle()

    def clear_history(self):
        self.history.clear()
        self.redraw()

    def draw_fft(self):
        self.sync_visibility()
        ax = self.ax
        ax.clear()
        self._layout_key = None
        ax.set_facecolor(SCREEN)
        ax.tick_params(colors=MUTED,labelsize=8)
        for spine in ax.spines.values(): spine.set_color('#42566c')
        ax.grid(color='#34465a',linewidth=.65)
        unit = 'code' if self.raw else 'V'
        logarithmic = self.fft_scale.get()=='dB'
        ax.set_xlabel('频率 / kHz',color=MUTED)
        ax.set_ylabel(('dB re 1 code RMS' if self.raw else 'dBV RMS') if logarithmic else unit+' RMS',color=MUTED)
        ax.set_title('FFT · 完整采集帧 · '+self.fft_window.get()+'窗',color=FG,fontsize=10)
        if not self.frame:
            ax.text(.5,.5,'等待采集',transform=ax.transAxes,ha='center',color=MUTED)
            self.canvas.draw_idle();return
        frame = self.frame
        if not self.waiting:
            self.state.set(('模拟 · ' if frame['simulated'] else '实采 · ')+self.acquisition_state+'  #'+str(frame['sequence']))
        self.info.set('FFT · {} 点 · 有效 {}'.format(len(frame['words'][0]),engineering(min(frame['sample_rates_hz']),'Sa/s')))
        for c, values in enumerate(self.values(self.converted)):
            if not self.visible[c].get():continue
            self.badges[c].set('RX{} · {}'.format(c+1, 'FFT' if self.visible[c].get() else '关闭'))
            if self.converted[c]['overrange'] or not all(finite(v) for v in values):
                self.stats[c].set('无有效频谱：过量程或采样无效')
                self.metric_strips[c].set([('FFT','采样无效')])
                continue
            result = spectrum(values,frame['sample_rates_hz'][c],
                              self.fft_window_key(),self.fft_remove_dc.get())
            if self.visible[c].get():
                ax.plot(result['frequency_hz']/1000,result['db'] if logarithmic else result['rms'],color=COLORS[c],linewidth=1)
            start = 1 if self.fft_remove_dc.get() else 0
            peak = int(result['rms'][start:].argmax())+start
            harmonics=' / '.join('{}× {}'.format(h['order'],engineering(h['rms'],unit)) for h in result['harmonics'] if h['order'] in (3,5,7))
            db = 20*math.log10(max(result['peak_rms'],1e-15)) if result['peak_rms'] is not None else None
            peak_db = ' / {:.2f} dB'.format(db) if db is not None else ''
            self.stats[c].set('交流谱峰 {} · {} RMS{}；全波 AC RMS {}\nΔf {} · Nyquist {} · {}'.format(
                engineering(result['peak_frequency_hz'],'Hz'),engineering(result['peak_rms'],unit),peak_db,engineering(result['ac_rms'],unit),
                engineering(result['bin_hz'],'Hz'),engineering(result['nyquist_hz'],'Hz'),harmonics if result['resolved'] else '周期不足或靠近频带边界'))
            self.metric_strips[c].set([('谱峰频率',engineering(result['peak_frequency_hz'],'Hz')),('谱峰 RMS',engineering(result['peak_rms'],unit)),
                ('谱峰 dB','{:.2f}'.format(db) if db is not None else '—'),('全波 AC RMS',engineering(result['ac_rms'],unit)),
                ('频率间隔',engineering(result['bin_hz'],'Hz')),('Nyquist',engineering(result['nyquist_hz'],'Hz'))])
        if logarithmic:
            lines = ax.lines
            if lines:
                top = max(float(max(line.get_ydata())) for line in lines)
                ax.set_ylim(max(-300,top-100),max(-200,top+10))
        else: ax.set_ylim(bottom=0)
        ax.set_xlim(left=0)
        if float(self.fft_max_khz.get())>0:
            ax.set_xlim(0,min(float(self.fft_max_khz.get()),max(frame['sample_rates_hz'])/2000))
        self.cursor_text.set('频谱使用完整帧；时间游标与余辉仅用于时域。')
        self.basis.set(('模拟频谱。' if frame['simulated'] else '幅度沿用RX换算，未新增交流校准。')+
                       '谱线为单个频率分量RMS，不能当成方波总幅值；平顶窗适合读幅度，Hann适合分辨邻频。抽取无抗混叠滤波。')
        self.canvas.draw_idle()

    def export_spectrum(self, path):
        with path.open('w', newline='', encoding='utf-8-sig') as stream:
            writer=csv.writer(stream)
            writer.writerow(['channel','frequency_hz','amplitude_rms','amplitude_db','unit',
                             'window','remove_dc','simulated','sample_rate_hz'])
            for c, values in enumerate(self.values(self.converted)):
                if self.converted[c]['overrange'] or not all(finite(v) for v in values): continue
                rate=self.frame['sample_rates_hz'][c]
                result=spectrum(values,rate,self.fft_window_key(),self.fft_remove_dc.get())
                for frequency, amplitude, db in zip(result['frequency_hz'],result['rms'],result['db']):
                    writer.writerow([c+1,frequency,amplitude,db,'code' if self.raw else 'V',
                                     result['window'],result['remove_dc'],self.frame['simulated'],rate])

    def export_png(self, path):
        """Include scale, source and measurements, not just an unlabelled trace."""
        size = self.figure.get_size_inches().copy()
        bottom = self.figure.subplotpars.bottom
        labels = []
        try:
            from matplotlib.patches import Rectangle
            self.figure.set_size_inches(12, 8, forward=False)
            visible=[c for c in range(2) if self.visible[c].get()]
            cursor_shown=bool(self.cursor_strip.winfo_manager())
            margin=.13+.12*len(visible)+(.11 if cursor_shown else 0)
            self.figure.subplots_adjust(bottom=margin)
            labels.append(self.figure.text(.08, .95, self.state.get()+'  |  '+self.info.get(), color=FG, fontsize=11))
            def cards(items,y,color):
                width=.89/max(1,len(items))
                for i,(title,value) in enumerate(items):
                    left=.08+i*width
                    box=Rectangle((left,y-.025),width-.004,.072,transform=self.figure.transFigure,facecolor='#0b1b2a',edgecolor='#42566c',lw=.6)
                    self.figure.add_artist(box);labels.append(box)
                    labels.append(self.figure.text(left+width/2,y+.025,title,ha='center',color=MUTED,fontsize=8))
                    labels.append(self.figure.text(left+width/2,y-.006,value,ha='center',color=color,fontsize=9))
            for row,c in enumerate(visible):
                labels.append(self.figure.text(.525,margin-.07-row*.12,self.badges[c].get(),ha='center',color=COLORS[c],fontsize=10))
                cards(self.metric_strips[c].values,margin-.13-row*.12,COLORS[c])
            if cursor_shown:cards(getattr(self.cursor_strip,'values',[]),.11,'#d7b7ff')
            self.figure.savefig(path, dpi=160)
        finally:
            for label in labels:
                label.remove()
            self.figure.set_size_inches(size, forward=False)
            self.figure.subplots_adjust(bottom=bottom)
            self.canvas.draw_idle()

    def draw_cursors(self, values):
        if not self.cursors.get():
            self.cursor_text.set('游标关闭 · 在右侧启用后，点击波形放置 A / B')
            return
        if not self.visible[int(self.cursor_source.get()[-1])-1].get():return
        for name, x in zip(('A', 'B'), self.cursor_times):
            if x is not None:
                self.ax.axvline(x, color='#d7b7ff', linewidth=.9, linestyle=':')
                self.ax.text(x, -3.8, name, color='#d7b7ff', ha='center')
        a, b = self.cursor_times
        if a is None or b is None:
            self.cursor_text.set('点击波形放置游标 '+('A' if a is None else 'B'))
            return
        c = int(self.cursor_source.get()[-1])-1
        if not self.visible[c].get():return
        cursor_values = [None if word >> 16 else v for v, word in zip(values[c], self.frame['words'][c])]
        samples = [sample_at(cursor_values, self.frame['sample_rates_hz'][c], x*1e-6+(self.trigger_time or 0)) for x in (a, b)]
        delta = samples[1]-samples[0] if all(finite(v) for v in samples) else None
        if delta is not None and abs(delta)<1e-12:delta=0.0
        dt = (b-a)*1e-6
        self.cursor_text.set('A {:.4g} µs   B {:.4g} µs   Δt {}   1/|Δt| {}\n{}：A {}   B {}   ΔV {}'.format(a, b,
            engineering(dt, 's'), engineering(1/abs(dt) if dt else None, 'Hz'), self.cursor_source.get(),
            *[engineering(v, 'code' if self.raw else 'V') for v in (*samples, delta)]))
        self.cursor_strip.set([('A 时间',engineering(a*1e-6,'s')),('B 时间',engineering(b*1e-6,'s')),('Δt',engineering(dt,'s')),
            ('1/|Δt|',engineering(1/abs(dt) if dt else None,'Hz'))]+[(self.cursor_source.get()+' '+label,engineering(v,'code' if self.raw else 'V')) for label,v in zip(('A','B','ΔV'),(*samples,delta))])
