"""Windows desktop workbench combining ADDA instruments and BJT measurements.

UI organization references embedded/dac_gui and ip_sdk's BJT workbench;
communication uses the current PYNQ drivers, never the vendor DLL.
"""
import argparse
import csv
import json
import math
import os
from dataclasses import asdict, fields
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib import rcParams
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from .desktop_session import MEASUREMENTS, waveform
from .desktop_transport import LocalTransport, SshTransport, agent_archive
from .frontend import Frontend, Calibration
from .scope_display import reference_channels
from .scope_view import ScopePanel
from .meter_view import MeterPanel
from .desktop_output import WAVES, defaults as tx_defaults, prepare as prepare_tx, output_summary
from .desktop_storage import workspace_path
from .profiles import Profile, LABELS as PROFILE_LABELS, defaults_for, assumptions
from .parameter_view import SegmentEditor
from .sweep import segmented_values
from .sidebar_art import SidebarArt
from .desktop_results import TABLE_COLUMNS, point_details, latest_result
from .desktop_lcd import DesktopLcd, SharedTransport

BG = '#101827'
PANEL = '#1b2a40'
FG = '#edf3ff'
MUTED = '#a6bad5'
BLUE = '#2979e8'
GREEN = '#54d3ac'
AMBER = '#ffc078'

NAMES = {'input': '输入特性', 'output': '输出特性 / Early', 'beta': 'β 线性精度', 'ac': '交流特性 / fβ / fT'}
BETA_VIEWS = {'IC–IB': ('ib_estimated_a', 'ic_a', 1e6, 1e3, 'IB estimate (uA)', 'IC (mA)'),
              'β–IC': ('ic_a', 'beta', 1e3, 1, 'IC (mA)', 'β = IC / IB'),
              'β–IB': ('ib_estimated_a', 'beta', 1e6, 1, 'IB estimate (uA)', 'β = IC / IB')}
rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False
LABELS = {
    'scan_mode': '扫描方式',
    'pulse_frequency_hz':'脉冲频率 / Hz', 'pulse_duty_percent':'脉冲占空比 / %',
    'pulse_attempts_per_frame':'每个有效脉冲帧的最大尝试次数',
    'pulse_noise_span_v':'脉冲噪声跨度限值下限 / V（节点）',
    'tx1_start_v': 'TX1 起点 / V', 'tx1_stop_v': 'TX1 终点 / V', 'tx1_step_v': 'TX1 步长 / V',
    'tx1_fine_stop_v': '低电流细扫截止 / TX1 V（0=关闭）', 'tx1_fine_step_v': '低电流细扫步长 / V',
    'uce_values_v': 'UCE 偏置列表 / V', 'settle_s': '每点等待 / s', 'curve_settle_s': '曲线等待 / s',
    'frames_per_point': '每点独立帧数', 'discard_frames': '每点丢弃帧数', 'frame_gap_s': '帧间等待 / s',
    'adaptive_settle_v': '自适应慢采样阈值 / V（0=关闭）',
    'max_node_drift_v': '节点漂移上限 / V', 'uce_tolerance_v': 'UCE 允许偏差 / V',
    'relay_active_level': '继电器有效电平', 'base_control_v': '基极控制电压列表 / V',
    'tx2_control_start_v': 'TX2 起点 / V', 'tx2_control_stop_v': 'TX2 终点 / V',
    'tx2_control_step_v': 'TX2 步长 / V', 'base_resistance_ohm': '基极等效电阻 / Ω',
    'collector_resistor_ohm': '电流采样电阻 / Ω', 'collector_channel': 'VC / VE 通道：0=RX1，1=RX2',
    'base_adc_per_v': '基极接口 / VB 比例（衰减4倍填0.25）', 'base_channel': '基极反馈通道：0=RX1，1=RX2', 'source_channel': '电源反馈通道：0=RX1，1=RX2', 'collector_adc_per_v': 'VC / VE 反馈衰减比',
    'source_adc_per_v': '电源反馈接口 / VCC 比例（0.206）', 'target_uce_v': '目标 UCE / UEC / V',
    'target_window_v': '目标窗口 / V', 'max_target_error_v': '目标误差上限 / V',
    'tx2_first_start_v': 'TX2 搜索起点 / V', 'tx2_start_increment_v': '搜索起点递增 / V',
    'tx2_step_v': 'TX2 搜索步长 / V', 'tx2_min_v': 'TX2 搜索下限 / V', 'tx2_stop_v': 'TX2 搜索上限 / V',
    'drop_initial_points': '拟合排除前点数（原始数据保留）', 'moving_average_window': '拟合移动平均点数',
    'tx1_bias_v': 'TX1 偏置 / V', 'tx2_vcc_control_v': 'TX2 电源控制 / V', 'tx3_input_vpp': '输入正弦波峰值 / V（TX3）',
    'source_buffer_gain': '缓冲后 / TX3 幅度比例（50→42 mV：0.84）',
    'adc_amplitude_multiplier': '交流 RX1/RX2 幅度系数（默认1）',
    'input_channel': '输入通道：0=RX1，1=RX2', 'output_channel': '输出通道：0=RX1，1=RX2',
    'input_adc_per_v': '交流采集 / VB 增益（9.78）', 'output_adc_per_v': '输出反馈衰减比',
    'input_sample_gain': '额外输入增益（9.78已计入比例，填1）', 'input_test_resistor_ohm': '输入测试电阻 / Ω',
    'sample_count': '每次统计采样点数', 'repeat_count': '每频点重复次数',
    'passband_stop_hz': '通带分析上限 / Hz', 'target_ratio': '截止增益比',
    'final_tolerance_hz': '截止频率搜索精度 / Hz', 'max_bisection_iterations': '二分搜索次数上限',
    'rx1_per_vc': '反馈接口 / VC、VE 比例', 'collector_amplifier_gain': '偏置功放增益',
    'base_equivalent_resistance_ohm': '输入扫描恒流源等效电阻 / Ω', 'max_uce_v': 'UCE 规划上限 / V',
    've_conversion_mode': 'PNP 输入 VE 换算方式',
}


def assets():
    if getattr(sys, 'frozen', False): return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[3]


class ScrollFrame(tk.Frame):
    def __init__(self, parent, *, fill_height=False, **kwargs):
        super().__init__(parent, bg=PANEL, **kwargs)
        self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, yscrollincrement=24)
        bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        bar.pack(side='right', fill='y'); self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=bar.set)
        self.inner = tk.Frame(self.canvas, bg=PANEL)
        window = self.canvas.create_window((0, 0), anchor='nw', window=self.inner)
        def fit_content(_event=None):
            self.canvas.itemconfigure(window, width=self.canvas.winfo_width())
            if fill_height:
                self.canvas.itemconfigure(window, height=max(self.canvas.winfo_height(),self.inner.winfo_reqheight()))
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.canvas.bind('<Configure>', fit_content)
        self.inner.bind('<Configure>', fit_content)
        self._wheel_tag = 'PanelWheel' + str(self)
        self._wheel_remainder = 0.0
        self.bind_class(self._wheel_tag, '<MouseWheel>', self._wheel)
        self._top = self.winfo_toplevel()
        self._map_binding = self._top.bind('<Map>', self._mapped, add='+')
        self.bind('<Destroy>', self._destroy_wheel, add='+')

    def _mapped(self, event):
        widget = event.widget
        parent = widget
        while parent is not None:
            if parent == self:
                tags = widget.bindtags()
                if self._wheel_tag not in tags:
                    widget.bindtags((self._wheel_tag,) + tags)
                break
            parent = getattr(parent, 'master', None)

    def _wheel(self, event):
        if self.canvas.yview() != (0.0, 1.0):
            self._wheel_remainder += -event.delta / 120.0 * 3
            steps = int(self._wheel_remainder)
            self._wheel_remainder -= steps
            if steps:
                self.canvas.yview_scroll(steps, 'units')
        # Also prevent an unfocused combobox/spinbox changing its value.
        return 'break'

    def _destroy_wheel(self, event):
        if event.widget == self:
            self._top.unbind('<Map>', self._map_binding)
            self.unbind_class(self._wheel_tag, '<MouseWheel>')


class App:
    def __init__(self, root, *, workspace=None):
        self.root = root
        self.base = workspace_path(workspace)
        self.base.mkdir(parents=True, exist_ok=True)
        self.results = self.base/'results'; self.results.mkdir(exist_ok=True)
        self.data = assets()/'data'
        self.scope_calibration = Calibration(self.data)
        dac_profile = json.loads((self.data/'dac_calibration.json').read_text(encoding='utf-8'))
        self.tx_scope_calibrated = (dac_profile['channels'][1].get('dc_table', {}).get('validation_status') ==
                                   'verified_custom50_37_knots_36_midpoints' and
                                   dac_profile['channels'][2].get('sine_50mv', {}).get('validation_status') ==
                                   'verified_custom50_scope_78_points_midpoints')
        self.events = queue.Queue()
        self.transport = None
        self.busy = False
        self.closing = False
        self.close_after = False
        self.stop_after = False
        self.live = False
        self.last_frame = None
        self.last_result = None
        self.result_by_measurement = {}
        self.measurement_views = {}
        self.profile_configs = {}
        self._parameter_profile = 'npn_small'
        self.table_column_views={}
        try:
            saved_columns=json.loads((self.base/'point_columns.json').read_text(encoding='utf-8'))
            self.table_column_views={name:list(dict.fromkeys(c for c in columns if c in {p[0] for p in TABLE_COLUMNS}))
                for name,columns in saved_columns.items() if name in MEASUREMENTS and isinstance(columns,list)}
        except (OSError,ValueError,AttributeError,TypeError):pass
        self.table_selected_column=None
        self.table_column_titles={key:title for key,title,_ in TABLE_COLUMNS}
        self.last_status = None
        self.rows = []
        self._plot_job = None
        self._last_plot_time = 0.0
        self._curve_lines = {}
        self._plot_context = None
        self.custom_samples = []
        self.measurement = 'input'
        self.nav_buttons = {}
        self.actions = []
        self.status_var = tk.StringVar(value='未连接 · 输出状态未知')
        self.notice = tk.StringVar(value='请输入板端账户密码，登录后进入测量工作台。')
        self.source = tk.StringVar(value='PYNQ 实板')
        self.host = tk.StringVar(value='192.168.0.4')
        self.user = tk.StringVar(value='xilinx')
        self.password = tk.StringVar()
        self.beta_view = tk.StringVar(value='IC–IB')
        self.beta_processing = tk.StringVar(value='参考处理')
        self.confirmed = tk.BooleanVar(value=False)
        self.fixture = tk.BooleanVar(value=False)
        self.qualification = None
        self.front_vars = {}
        frontend = self.load_frontend_defaults()
        for key,value in asdict(frontend).items():
            if key!='transfer_basis': self.front_vars[key]=tk.StringVar(value=str(value))
        self.config_vars = {}
        self.config_entries = {}
        self.config_values = {k: asdict(v[0]()) for k, v in MEASUREMENTS.items()}
        self.config_values = self.saved_defaults_for('npn_small')
        self.profile = tk.StringVar(value='NPN 小功率')
        self.method = tk.StringVar(value='步进')
        self.reference_mode = tk.StringVar(value='参考参数换算')
        self.route_text = tk.StringVar()
        self.parameter_advanced = False
        self._load_settings()
        root.title('Zynq BJT · ADDA 仪器与晶体管测量工作台')
        self.ui_scale = max(1.0, root.winfo_fpixels('1i') / 96)
        root.geometry('{}x{}'.format(min(self.px(1320), root.winfo_screenwidth()-40),
                                     min(self.px(880), root.winfo_screenheight()-100)))
        root.minsize(self.px(1080), self.px(700)); root.configure(bg=BG)
        root.option_add('*Font', ('Microsoft YaHei UI', 10))
        style = ttk.Style(); style.theme_use('clam')
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=(16, 8))
        style.configure('TEntry', padding=5)
        style.configure('TCombobox', padding=4)
        style.configure('Treeview', rowheight=29, background='#f6f8fc', foreground='#18304d', fieldbackground='#f6f8fc')
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI',10,'bold'), padding=7)
        style.map('Treeview', background=[('selected',BLUE)])
        self._build()
        from .workbench_tools import WorkbenchTools
        self.tools = WorkbenchTools(self)
        self.lcd = DesktopLcd(self)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(60, self.pump)

    def px(self, value): return int(round(value*self.ui_scale))

    @staticmethod
    def label(parent, text='', **kwargs):
        return tk.Label(parent, text=text, bg=kwargs.pop('bg', parent.cget('bg')),
                        fg=kwargs.pop('fg', FG), **kwargs)

    def button(self, parent, text, command, *, color=BLUE, tracked=False):
        button = tk.Button(parent, text=text, command=command, bg=color, fg=FG,
                           activebackground='#39608c', activeforeground=FG,
                           disabledforeground='#7d8da4', relief='flat', padx=13, pady=7, cursor='hand2')
        if tracked: self.actions.append(button)
        return button

    def _build(self):
        self.workbench = tk.Frame(self.root, bg=BG)
        self.login_view = tk.Frame(self.root, bg=BG)
        card = tk.Frame(self.login_view, bg=PANEL, padx=40, pady=32)
        card.place(relx=.5, rely=.46, anchor='center')
        self.label(card, '晶体管测量工作台', fg='#8fd3ff', font=('Microsoft YaHei UI',24,'bold')).grid(row=0,column=0,columnspan=2,pady=(0,5))
        self.label(card, 'ZYNQ · ADDA', fg=MUTED).grid(row=1,column=0,columnspan=2,pady=(0,28))
        self.label(card, '连接方式', fg=MUTED).grid(row=2,column=0,sticky='w',padx=(0,20))
        self.source_combo = ttk.Combobox(card, textvariable=self.source, values=['PYNQ 实板', '离线模拟'], width=29, state='readonly')
        self.source_combo.grid(row=2,column=1,sticky='ew',pady=8)
        self.login_entries = []
        for row,(label,variable,show) in enumerate([('地址',self.host,''),('用户',self.user,''),('密码',self.password,'*')],3):
            self.label(card,label,fg=MUTED).grid(row=row,column=0,sticky='w',padx=(0,20))
            entry=ttk.Entry(card,textvariable=variable,width=31,show=show)
            entry.grid(row=row,column=1,sticky='ew',pady=8)
            entry.bind('<Return>',lambda event:self.connect())
            self.login_entries.append(entry)
        self.connect_button = self.button(card, '登录工作台', self.connect)
        self.connect_button.grid(row=6,column=0,columnspan=2,sticky='ew',pady=(22,12))
        self.label(card,textvariable=self.notice,fg=AMBER,wraplength=self.px(430),justify='left').grid(row=7,column=0,columnspan=2,sticky='w')
        self.label(card,'实板使用 PYNQ 账户验证；离线模拟不连接硬件。',fg=MUTED,font=('Microsoft YaHei UI',9)).grid(row=8,column=0,columnspan=2,pady=(20,0))
        header = tk.Frame(self.workbench, bg=BG); header.pack(fill='x', padx=24, pady=(15, 8))
        header.columnconfigure(1,weight=1)
        from PIL import Image, ImageTk
        with Image.open(assets()/'data/ui/fpga_competition_10th_hd.png') as logo:
            logo.thumbnail((self.px(190),self.px(80)),Image.Resampling.LANCZOS)
            self.header_logo_image=ImageTk.PhotoImage(logo,master=self.root)
        self.header_logo=self.label(header,image=self.header_logo_image)
        self.header_logo.grid(row=0,column=0,rowspan=2,sticky='w',padx=(0,self.px(16)))
        self.header_title=self.label(header,'晶体管测量工作台',fg='#8fd3ff',font=('Microsoft YaHei UI',20,'bold'))
        self.header_title.grid(row=0,column=1,sticky='ew')
        self.label(header,'ZYNQ · ADDA',fg=MUTED,font=('Segoe UI',11)).grid(row=1,column=1)
        self.label(header,textvariable=self.status_var,fg=AMBER).grid(row=1,column=2,sticky='e')
        header_actions=tk.Frame(header,bg=BG);header_actions.grid(row=0,column=2,sticky='e')
        self.disconnect_button = self.button(header_actions, '退出连接', self.disconnect, color='#354b6d'); self.disconnect_button.pack(side='left',padx=(0,8))
        self.init_button = self.button(header_actions, '初始化', lambda: self.submit('initialize'), color='#285a57', tracked=True)
        self.init_button.pack(side='right')
        self.header_separator=tk.Frame(self.workbench,bg='#496684',height=self.px(1))
        self.header_separator.pack(fill='x',padx=24,pady=(2,4))
        self.label(self.workbench, textvariable=self.notice, fg=MUTED, anchor='w').pack(fill='x', padx=25, pady=(8, 10))
        self.notice_separator=tk.Frame(self.workbench,bg='#496684',height=self.px(1))
        self.notice_separator.pack(fill='x',padx=24,pady=(0,8))
        body = tk.Frame(self.workbench, bg=BG); body.pack(fill='both', expand=True, padx=24)
        self.nav_scroll = ScrollFrame(body, width=self.px(210), fill_height=True)
        self.nav_scroll.pack(side='left', fill='y', padx=(0,16)); self.nav_scroll.pack_propagate(False)
        nav = self.nav_scroll.inner
        nav.configure(bg=BG)
        nav.columnconfigure(0,weight=1)
        for row in (1,3):nav.rowconfigure(row,weight=1,uniform='nav_spacing',minsize=self.px(16))
        self.nav_sections=[]
        def nav_section(text):
            section=tk.Frame(nav,bg=BG)
            section.grid(row=2*len(self.nav_sections),column=0,sticky='ew')
            self.nav_sections.append(section)
            frame=tk.Frame(section,bg='#20354d',highlightbackground='#486c91',highlightthickness=1)
            frame.pack(fill='x',pady=(0,8))
            self.label(frame,text,fg='#a9dcff',font=('Microsoft YaHei UI',11,'bold'),anchor='center',pady=8).pack(fill='x')
            return section
        adda_nav=nav_section('ADDA 仪器控制')
        SidebarArt(adda_nav, 'adda', self.px).pack(fill='x',pady=(0,6))
        self.nav_buttons['tx'] = self.button(adda_nav, 'TX1 / TX2 / TX3', lambda:self.show_page('tx'), color=PANEL)
        self.nav_buttons['tx'].pack(fill='x',pady=3)
        instrument_row = tk.Frame(adda_nav,bg=BG);instrument_row.pack(fill='x',pady=3)
        for col,(name,label) in enumerate((('scope','示波器'),('meter','电压表'))):
            instrument_row.columnconfigure(col,weight=1,uniform='instrument')
            self.nav_buttons[name] = self.button(instrument_row,label,lambda n=name:self.show_page(n),color=PANEL)
            self.nav_buttons[name].grid(row=0,column=col,sticky='ew',padx=(0,3) if col==0 else (3,0))
        self.nav_buttons['gpio'] = self.button(adda_nav, '七路 IO / 继电器', lambda:self.show_page('gpio'), color=PANEL)
        self.nav_buttons['gpio'].pack(fill='x',pady=3)
        bjt_nav=nav_section('BJT 测量工作台')
        SidebarArt(bjt_nav, 'bjt', self.px).pack(fill='x',pady=(0,6))
        for name, label in NAMES.items():
            self.nav_buttons[name] = self.button(bjt_nav, label, lambda n=name: self.show_page(n), color=PANEL)
            self.nav_buttons[name].pack(fill='x', pady=3)
        utilities_nav=nav_section('设置与数据管理')
        self.utility_grid=tk.Frame(utilities_nav,bg=BG);self.utility_grid.pack(fill='x')
        for col in (0,1):self.utility_grid.columnconfigure(col,weight=1,uniform='utility')
        for i,(title,command) in enumerate((('参数依据 / 设置',lambda:self.show_page('settings')),
                ('打开数据目录',lambda:os.startfile(self.results)),('取回板端记录',self.retrieve),('停止 / 取消',self.stop))):
            button=self.button(self.utility_grid,title,command,color='#974643' if i==3 else PANEL,tracked=i==2)
            button.config(font=('Microsoft YaHei UI',9),padx=3,pady=6)
            button.grid(row=i//2,column=i%2,sticky='ew',padx=2,pady=2)
            if i==3:self.stop_button=button
        self.main = tk.Frame(body, bg=BG); self.main.pack(side='left', fill='both', expand=True)
        self.page_title = self.label(self.main, '', font=('Microsoft YaHei UI', 18, 'bold'),anchor='center',justify='center')
        self.page_title.pack(fill='x', pady=(0, 8))
        self.page_separator=tk.Frame(self.main,bg='#496684',height=self.px(1))
        self.page_separator.pack(fill='x',pady=(0,10))
        self.page_host = tk.Frame(self.main, bg=BG); self.page_host.pack(fill='both', expand=True)
        self.pages = {}
        self._tx_page(); self._scope_page()
        self.meter = MeterPanel(self,self._new_page('meter'))
        self._gpio_page(); self._measurement_page(); self._settings_page()
        logrow = tk.Frame(self.workbench, bg='white'); logrow.pack(fill='x', padx=24, pady=(10, 4))
        self.progress_text = tk.StringVar(value='就绪')
        self.label(logrow, textvariable=self.progress_text, fg='#1463ad',bg='white',font=('Microsoft YaHei UI',11,'bold')).pack(side='left',pady=4)
        ttk.Style().configure('Bjt.Horizontal.TProgressbar',background='#147df5',lightcolor='#54acff',darkcolor='#147df5',
                              troughcolor='#d5e4f5',bordercolor='#8eb7df',thickness=self.px(20),barsize=self.px(80))
        self.progress = ttk.Progressbar(logrow,style='Bjt.Horizontal.TProgressbar',mode='indeterminate',length=self.px(320))
        self.progress.pack(side='right',padx=(16,0),pady=4)
        self.logbox = tk.Text(self.workbench, height=4, bg='white', fg='#26364a', insertbackground='#26364a', relief='flat', wrap='word', state='disabled', font=('Consolas', 9))
        self.logbox.pack(fill='x', padx=24, pady=(0, 14))
        # Reserve the footer before the expanding page, including on high-DPI
        # displays where Matplotlib requests a larger natural widget height.
        body.pack_forget(); logrow.pack_forget(); self.logbox.pack_forget()
        self.logbox.pack(side='bottom', fill='x', padx=24, pady=(0, 14))
        logrow.pack(side='bottom', fill='x', padx=24, pady=(10, 4))
        body.pack(fill='both', expand=True, padx=24)
        self.show_page('input'); self.controls()
        self.show_login()
        self.log('来源：自制板 ADDA 控制界面 + 原仪器 BJT 综合工作台。当前连接方式：PYNQ / SSH。')

    def show_login(self):
        self.workbench.pack_forget()
        self.login_view.pack(fill='both',expand=True)
        self.password.set('')
        self.fixture.set(False); self.confirmed.set(False)

    def enter_workbench(self):
        self.login_view.pack_forget()
        self.workbench.pack(fill='both',expand=True)

    def _new_page(self, name):
        frame = tk.Frame(self.page_host, bg=BG); self.pages[name] = frame; return frame

    def confirmation_button(self, parent, variable, label):
        button=tk.Button(parent,command=lambda:variable.set(not variable.get()),
            font=('Microsoft YaHei UI',10,'bold'),padx=10,pady=4,
            relief='solid',bd=1,cursor='hand2',anchor='w',wraplength=self.px(360))
        def refresh(*args):
            selected=variable.get()
            button.config(text=('✓ 已确认：' if selected else '□ 点击确认：')+label,
                bg='#216657' if selected else '#a33232',fg=FG,
                activebackground='#2b806b' if selected else '#c34242',activeforeground=FG)
        token=variable.trace_add('write',refresh)
        button.bind('<Destroy>',lambda e:variable.trace_remove('write',token) if e.widget==button else None)
        refresh()
        return button

    def _entry(self, parent, label, variable, row, width=17):
        self.label(parent, label, fg=MUTED, anchor='w').grid(row=row, column=0, sticky='w', padx=12, pady=6)
        ttk.Entry(parent, textvariable=variable, width=width).grid(row=row, column=1, sticky='ew', padx=12, pady=6)

    def _plot(self, parent):
        figure = Figure(figsize=(6, 4), dpi=100, facecolor='#f4f7fb')
        ax = figure.add_subplot(111); ax.grid(alpha=.2)
        figure.subplots_adjust(left=.13, right=.96, bottom=.15, top=.9)
        canvas = FigureCanvasTkAgg(figure, parent)
        toolbar = NavigationToolbar2Tk(canvas, parent, pack_toolbar=False); toolbar.pack(side='bottom', fill='x')
        canvas.get_tk_widget().pack(fill='both', expand=True)
        return figure, ax, canvas

    def _tx_page(self):
        page = self._new_page('tx')
        scroll = ScrollFrame(page, width=self.px(425)); scroll.pack(side='left', fill='y', padx=(0, 12)); scroll.pack_propagate(False)
        left = scroll.inner
        left.columnconfigure(1,weight=1)
        self.tx_channel = tk.StringVar(value='TX1')
        self.tx_mode = tk.StringVar(value='直流')
        self.tx_unit = tk.StringVar(value='voltage')
        self.tx_drafts = {}; self._tx_context = None; self._editing_tx = False
        for row, label, variable, options in [(0, '输出通道', self.tx_channel, ['TX1', 'TX2', 'TX3']),
                                               (1, '波形', self.tx_mode, list(WAVES))]:
            self.label(left, label, fg=MUTED).grid(row=row, column=0, sticky='w', padx=12, pady=8)
            combo = ttk.Combobox(left, textvariable=variable, values=options, state='readonly', width=23)
            combo.grid(row=row, column=1, padx=12, pady=8,sticky='ew'); combo.bind('<<ComboboxSelected>>', self.tx_changed)
            if row==1:self.tx_wave_combo=combo
        self.label(left,'设定单位',fg=MUTED).grid(row=2,column=0,sticky='w',padx=12,pady=8)
        units=tk.Frame(left,bg=PANEL);units.grid(row=2,column=1,sticky='ew',padx=12,pady=8)
        self.tx_unit_buttons={}
        for text,value in [('电压 / V','voltage'),('码','code')]:
            button=tk.Radiobutton(units,text=text,variable=self.tx_unit,value=value,indicatoron=False,
                                  command=self.tx_changed,bg='#354b6d',fg=FG,selectcolor=BLUE,
                                  activebackground=BLUE,activeforeground=FG,relief='flat',bd=0,padx=16,pady=7,cursor='hand2')
            button.pack(side='left',fill='x',expand=True,padx=(0,4));self.tx_unit_buttons[value]=button
        self.tx_vars = {key:tk.StringVar(value=value) for key,value in tx_defaults(0,'dc','voltage',self.scope_calibration).items()}
        self.tx_labels={};self.tx_entries={}
        for row,(key,label) in enumerate([('offset','直流电压 / V'),('peak','峰值幅度 / V'),('frequency_hz','频率 / Hz'),
                                           ('duty_percent','方波占空比 / %'),('phase_degrees','相位 / °')],3):
            self.tx_labels[key]=self.label(left,label,fg=MUTED,anchor='w')
            self.tx_labels[key].grid(row=row,column=0,sticky='w',padx=12,pady=6)
            entry=ttk.Entry(left,textvariable=self.tx_vars[key],width=17)
            entry.grid(row=row,column=1,sticky='ew',padx=12,pady=6);self.tx_entries[key]=entry
            entry.bind('<Return>', self.tx_enter)
        self.tx_amplitude_note=self.label(left,'',fg=GREEN,anchor='w',justify='left')
        self.tx_amplitude_note.grid(row=8,column=0,columnspan=2,sticky='ew',padx=12,pady=5)
        self.wave_import_button=self.button(left, '导入归一化 CSV', self.import_wave, color='#354b6d')
        self.wave_import_button.grid(row=9, column=0, columnspan=2, sticky='ew', padx=12, pady=5)
        self.wave_label = self.label(left, 'CSV：单列 value 或 index,value', fg=MUTED, wraplength=350,anchor='w',justify='left')
        self.wave_label.grid(row=10, column=0, columnspan=2, padx=12, pady=3,sticky='w')
        self.tx_confirmation=self.confirmation_button(left,self.confirmed,'已核对接线与负载')
        self.tx_confirmation.grid(row=11,column=0,columnspan=2,sticky='ew',padx=12,pady=5)
        actions = tk.Frame(left, bg=PANEL); actions.grid(row=12, column=0, columnspan=2, padx=10, pady=8)
        for label, action, color in [('应用', 'apply', BLUE), ('启动输出', 'start', '#285a57'), ('停止此路', 'stop', '#974643')]:
            self.button(actions, label, lambda a=action: self.tx_apply(a), color=color, tracked=True).pack(side='left', padx=3)
        self.tx_limit_note=self.label(left,'',fg=MUTED,justify='left',anchor='w',wraplength=350)
        self.tx_limit_note.grid(row=13,column=0,columnspan=2,padx=12,pady=10,sticky='ew')
        self.tx_limit_note.bind('<Configure>',lambda e:self.tx_limit_note.configure(wraplength=max(100,e.width-8)))
        right = tk.Frame(page, bg=BG); right.pack(side='left', fill='both', expand=True)
        self.tx_state = self.label(right, '输出状态未知', fg=AMBER, justify='left', anchor='w', wraplength=600)
        self.tx_state.pack(fill='x', pady=8)
        self.tx_clock_state=self.label(right,'DAC 采样时钟：连接后读取',fg=MUTED,anchor='w')
        self.tx_clock_state.pack(fill='x',pady=(0,6))
        self.tx_state.bind('<Configure>', lambda e: self.tx_state.configure(wraplength=max(100, e.width-8)))
        self.tx_preview_status=self.label(right,'设定预览',fg=MUTED,anchor='w',justify='left',wraplength=700)
        self.tx_preview_status.pack(fill='x',pady=(0,8))
        self.tx_preview_status.bind('<Configure>',lambda e:self.tx_preview_status.configure(wraplength=max(100,e.width-8)))
        self.tx_figure, self.tx_ax, self.tx_canvas = self._plot(right)
        for var in self.tx_vars.values(): var.trace_add('write', lambda *_: self.preview_wave())
        self.tx_changed()

    def tx_changed(self, _event=None):
        if self._tx_context is not None:
            self.tx_drafts[self._tx_context]={key:var.get() for key,var in self.tx_vars.items()}
        channel=int(self.tx_channel.get()[-1])-1
        if channel==0:self.tx_mode.set('直流')
        self.tx_wave_combo.config(values=['直流'] if channel==0 else list(WAVES))
        wave=WAVES[self.tx_mode.get()];unit=self.tx_unit.get();context=(channel,wave,unit)
        self._editing_tx=True
        values=dict(self.tx_drafts.get(context,tx_defaults(channel,wave,unit,self.scope_calibration)))
        if self._tx_context is not None and self._tx_context[:2]==context[:2]:
            # Unit selection changes amplitude/offset units only. Frequency,
            # duty and supported phase must not jump to the other draft.
            for key in ('frequency_hz','duty_percent','phase_degrees'):
                if key=='phase_degrees' and channel==2 and wave=='sine' and unit=='voltage':
                    values[key]='0'
                else:values[key]=self.tx_vars[key].get()
        for key,value in values.items():self.tx_vars[key].set(value)
        self._tx_context=context;self._editing_tx=False
        voltage=unit=='voltage';suffix='V' if voltage else '码'
        self.tx_labels['offset'].config(text=('直流电压' if voltage else '直流值')+' / '+suffix if wave=='dc' else '偏置 / '+suffix)
        self.tx_labels['peak'].config(text='峰值幅度 / '+suffix)
        active={'offset':True,'peak':wave!='dc','frequency_hz':wave!='dc','duty_percent':wave=='square',
                'phase_degrees':wave!='dc' and not(channel==2 and wave=='sine' and voltage)}
        for key,entry in self.tx_entries.items():entry.config(state='normal' if active[key] else 'disabled')
        self.wave_import_button.config(state='disabled' if channel==0 else 'normal')
        if wave=='custom':self.wave_label.grid()
        else:self.wave_label.grid_remove()
        if channel==0:note='TX1：0～2.499 V；0～4095 码。'
        elif channel==1:note='TX2：0～1.8 V；0～65535 码。'
        elif voltage and wave=='sine' and not self.scope_calibration.tx3_waveforms:
            note='TX3：10 kHz～6 MHz；0～65535 码。'
        elif voltage and wave not in ('sine','square','triangle'):
            profile=self.scope_calibration.dac['channels'][2]
            step=profile['reference_uv']/1e6/profile['reference_codes']
            note='TX3：{:.3g}～{:.3g} V；0～65535 码。'.format(-profile['zero_code']*step,(65535-profile['zero_code'])*step)
        else:note='TX3：0～65535 码。'
        if wave!='dc' and not(channel==2 and voltage and wave=='sine' and not self.scope_calibration.tx3_waveforms):note+=' 0＜频率≤10 MHz。'
        self.tx_limit_note.config(text=note)
        self.preview_wave()

    def tx_plan(self, action='apply'):
        return prepare_tx(int(self.tx_channel.get()[-1])-1,WAVES[self.tx_mode.get()],self.tx_unit.get(),
                          {key:var.get() for key,var in self.tx_vars.items()},self.scope_calibration,
                          normalized=self.custom_samples,confirmed=self.confirmed.get(),action=action)

    def tx_request(self, action):
        return self.tx_plan(action)['request']

    def preview_wave(self):
        if not hasattr(self,'tx_ax') or self._editing_tx:return
        self.tx_ax.clear()
        voltage=self.tx_unit.get()=='voltage'
        self.tx_ax.set(ylabel='电压 / V' if voltage else 'DAC 码',title=self.tx_channel.get()+' · '+self.tx_mode.get()+' · 设定预览')
        try:
            plan=self.tx_plan();frequency=plan['frequency_hz']
            if frequency:
                scale,label=(1e6,'时间 / μs') if frequency>=10000 else ((1000,'时间 / ms') if frequency>=1 else (1,'时间 / s'))
                x=[i/256/frequency*scale for i in range(257)]
                values=plan['preview']+[plan['preview'][0]]
            else:x=list(range(256));values=plan['preview'];label='采样点'
            self.tx_ax.plot(x,values,color=BLUE,drawstyle='steps-post' if self.tx_mode.get()=='方波' else 'default')
            self.tx_ax.set_xlabel(label)
            if not frequency:
                span=max(abs(plan['offset'])*.15,.1 if voltage else 100)
                self.tx_ax.set_ylim(plan['offset']-span,plan['offset']+span)
            self.tx_preview_status.config(text='',fg=MUTED)
            self.tx_amplitude_note.config(text=('' if not frequency else
                '峰值幅度 A = {:g} {}；峰峰值 = {:g} {}'.format(plan['peak'],'V' if voltage else '码',2*plan['peak'],'Vpp' if voltage else '码')))
        except (ValueError,KeyError,TypeError) as error:
            self.tx_ax.text(.5,.5,'请检查设定参数',ha='center',transform=self.tx_ax.transAxes)
            self.tx_preview_status.config(text=str(error),fg=AMBER)
            self.tx_amplitude_note.config(text='幅度按当前所选单位输入。')
        self.tx_ax.grid(alpha=.2);self.tx_canvas.draw_idle()

    def import_wave(self):
        path = filedialog.askopenfilename(filetypes=[('CSV', '*.csv'), ('All', '*.*')])
        if not path: return
        try:
            rows = list(csv.reader(Path(path).read_text(encoding='utf-8-sig').splitlines()))
            if rows and rows[0][-1].strip().lower() in ('value', 'amplitude'): rows = rows[1:]
            values = [float(r[-1]) for r in rows if r]
            waveform(dict(mode='custom_code', samples=values, offset=32768, peak=1000))
            self.custom_samples = values; self.tx_mode.set('CSV 波形')
            self.wave_label.config(text='{} · {} 点 → 256 点'.format(Path(path).name, len(values)))
            self.tx_changed()
        except Exception as error: self.error(error)

    def tx_apply(self, action):
        try: request = self.tx_request(action)
        except Exception as error: self.error(error); return
        self.submit('output', request)

    def tx_enter(self, event=None):
        channel=str(int(self.tx_channel.get()[-1])-1)
        if self.busy:
            self.error('正在处理，请完成后再按回车'); return 'break'
        if not self.transport or not self.last_status or channel not in self.last_status.get('output_settings', {}):
            self.error('此通道请先点击一次应用或启动输出，之后可按回车更新参数'); return 'break'
        if not self.confirmed.get():
            self.error('请先确认已核对接线与负载'); return 'break'
        # Applying updates the waveform while preserving the acknowledged enable
        # state. Enter must never silently re-enable a stopped output.
        self.tx_apply('apply')
        return 'break'

    def rx_calibration_note(self):
        parts=[]
        for channel,profile in enumerate((self.scope_calibration.rx1,self.scope_calibration.rx2),1):
            basis='发生器标称 DC 校准' if profile.get('validation_status')=='generator_nominal_validated' else '历史表参考'
            parts.append('RX{}：{}，{:g} MSPS，{:g}～{:g} V。'.format(channel,basis,profile['sample_rate_hz']/1e6,profile['valid_min_v'],profile['valid_max_v']))
        return ' '.join(parts)

    def _scope_page(self):
        self.scope = ScopePanel(self, self._new_page('scope'), ScrollFrame)
        self.scope_units = self.scope.units
        self.scope_figure, self.scope_ax, self.scope_canvas = self.scope.figure, self.scope.ax, self.scope.canvas

    def _gpio_page(self):
        page = self._new_page('gpio')
        scroll=ScrollFrame(page);scroll.pack(fill='both',expand=True)
        panel=scroll.inner
        self.gpio_labels = []
        self.gpio_buttons = []
        manual=tk.Frame(panel,bg=PANEL);manual.pack(fill='x',padx=8)
        for bit, pin in enumerate((87, 85, 83, 81, 79, 77, 48)):
            manual.columnconfigure(bit,weight=1,uniform='io')
            row = tk.Frame(manual, bg=BG, padx=4, pady=8); row.grid(row=0,column=bit,sticky='ew',padx=3)
            row.columnconfigure((0,1),weight=1)
            self.label(row, 'IN{} · X1.{}'.format(bit+1, pin)).grid(row=0,column=0,columnspan=2,pady=(0,8))
            buttons = []
            for value, label in [(0, '低 0'), (1, '高 1')]:
                button = self.button(row, label, lambda b=bit, v=value: self.submit('gpio', {'mask': 1<<b, 'value': v<<b}), color='#354b6d', tracked=True)
                button.config(padx=5,pady=5)
                button.grid(row=1,column=value,sticky='ew',padx=2); buttons.append(button)
            self.gpio_buttons.append(buttons)
            status = self.label(row, '设定 — / 回读 —', fg=MUTED,font=('Microsoft YaHei UI',9)); status.grid(row=2,column=0,columnspan=2,pady=(8,0)); self.gpio_labels.append(status)
        self.label(panel,'继电器组合对照 / 一键设置',font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',padx=12,pady=(22,5))
        table=tk.Frame(panel,bg=BG);table.pack(fill='x',padx=12,pady=(0,12))
        headings=('器件 / 功率','测量类型','恒流源档位','87','77 / 48','79 / 81','83 / 85','设置')
        for col,title in enumerate(headings):
            table.columnconfigure(col,weight=2 if col<3 else 1)
            self.label(table,title,bg='#304563',font=('Microsoft YaHei UI',10,'bold')).grid(row=0,column=col,sticky='nsew',padx=1,pady=1,ipady=7)
        self.route_buttons=[]
        groups={}
        for profile_key,profile_label in PROFILE_LABELS.items():
            for mode,title in (('input','输入特性'),('ac','交流特性'),('output','输出 / β 线性')):
                route=Profile(profile_key).route(mode)
                group=groups.setdefault(route['value'],dict(route=route,profiles=[],titles=[],profile=profile_key,mode=mode))
                if profile_label not in group['profiles']:group['profiles'].append(profile_label)
                if title not in group['titles']:group['titles'].append(title)
        for row_index,group in enumerate(groups.values(),1):
            route=group['route'];pins=route['pin_values']
            current='100 nA～10 μA' if group['mode']=='input' else ('10 μA～1 mA' if route['current_range_a'][1]==.001 else '400 μA～40 mA')
            values=(' / '.join(group['profiles']),' / '.join(group['titles']),current,str(pins[87]))+tuple('{}{}'.format(pins[a],pins[b]) for a,b in ((77,48),(79,81),(83,85)))
            labels=[]
            for col,value in enumerate(values):
                label=self.label(table,value,bg=PANEL)
                label.grid(row=row_index,column=col,sticky='nsew',padx=1,pady=1,ipadx=5,ipady=5);labels.append(label)
            button=self.button(table,'应用',lambda p=group['profile'],m=group['mode']:self.apply_relay_route(p,m),color='#354b6d',tracked=True)
            button.config(pady=4,padx=10);button.grid(row=row_index,column=7,sticky='nsew',padx=1,pady=1)
            self.route_buttons.append((route['value'],button,labels))
        self.render_gpio_selection(0, default=True)

    def apply_relay_route(self, profile_key, measurement):
        if self.busy or not self.transport:return
        route=Profile(profile_key).route(measurement)
        transport=self.transport
        self.fixture.set(False)
        def apply():
            status=transport.call('gpio',dict(mask=127,value=route['value']))
            gpio=status['gpio']
            if (gpio['output']&127)!=route['value'] or ((gpio['output']^gpio['sense'])&127):
                raise RuntimeError('继电器组合回读不一致，请检查 IO 状态')
            return status
        self.start_job('relay_route',apply)

    def render_gpio_selection(self, output=None, default=False):
        for bit, buttons in enumerate(self.gpio_buttons):
            for value, button in enumerate(buttons):
                selected = output is not None and ((output >> bit) & 1) == value
                button.config(bg=BLUE if selected else '#354b6d',
                    relief='sunken' if selected else 'flat',
                    text=('● ' if selected else '')+('低 0' if value == 0 else '高 1'))
            if default:
                self.gpio_labels[bit].config(text='默认低 0 / 尚未回读', fg=MUTED)
        for value,button,labels in getattr(self,'route_buttons',[]):
            # 85 is don't-care for output mode when 83=1.
            mask=125 if value&4 else 127
            selected=not default and output is not None and (output&mask)==(value&mask)
            button.config(text='✓ 当前' if selected else '应用',bg='#216657' if selected else '#354b6d')
            for label in labels:label.config(bg='#24483f' if selected else PANEL)

    def _measurement_page(self):
        page = self._new_page('measurement')
        row = tk.Frame(page, bg=BG); row.pack(fill='x', pady=(0, 9))
        self.label(row, '器件档位', fg=MUTED).pack(side='left')
        combo=ttk.Combobox(row, textvariable=self.profile, values=list(PROFILE_LABELS.values()), width=16, state='readonly')
        combo.pack(side='left', padx=8)
        combo.bind('<<ComboboxSelected>>', self.change_profile)
        self.profile_combo=combo
        self.button(row, '开始测量', self.start_scan, tracked=True).pack(side='right')
        overview=tk.Frame(page,bg=PANEL,padx=14,pady=10);overview.pack(fill='x',pady=(0,10))
        self.label(overview,textvariable=self.route_text,fg=GREEN,justify='left',anchor='w').pack(fill='x')
        split = tk.PanedWindow(page, orient='horizontal', bg=BG, sashwidth=9, bd=0); split.pack(fill='both', expand=True)
        left = tk.Frame(split, bg=PANEL); split.add(left, minsize=self.px(290), width=self.px(345))
        self.fixture_confirmation=self.confirmation_button(left,self.fixture,'BJT 接线与负载')
        self.fixture_confirmation.config(wraplength=self.px(290))
        self.fixture_confirmation.pack(fill='x',padx=10,pady=(5,4))
        self.param_tabs=ttk.Notebook(left);self.param_tabs.pack(fill='both',expand=True,padx=5,pady=5)
        actions = tk.Frame(left, bg=PANEL); actions.pack(fill='x', padx=8, pady=8)
        self.button(actions, '导入配置', self.import_config, color='#354b6d').pack(side='left', padx=2)
        self.button(actions, '保存配置', self.export_config, color='#354b6d').pack(side='left', padx=2)
        self.button(actions, '默认参数', self.reset_preset, color='#354b6d').pack(side='left', padx=2)
        self.button(actions, '设为默认', self.save_page_default, color='#285a57').pack(side='left', padx=2)
        right = tk.Frame(split, bg=BG); split.add(right, minsize=self.px(360))
        self.measure_tabs = ttk.Notebook(right); self.measure_tabs.pack(fill='both', expand=True)
        chart = tk.Frame(self.measure_tabs, bg=BG); self.measure_tabs.add(chart, text='曲线')
        self.beta_selector_bar=tk.Frame(chart,bg=BG)
        self.beta_selector_bar.pack(fill='x',pady=5)
        self.label(self.beta_selector_bar,'显示曲线',fg=MUTED).pack(side='left',padx=10)
        self.beta_selector=ttk.Combobox(self.beta_selector_bar,textvariable=self.beta_view,values=list(BETA_VIEWS),state='readonly',width=16)
        self.beta_selector.pack(side='left')
        self.beta_selector.bind('<<ComboboxSelected>>',self.change_beta_view)
        self.label(self.beta_selector_bar,'数据',fg=MUTED).pack(side='left',padx=(16,6))
        processing=ttk.Combobox(self.beta_selector_bar,textvariable=self.beta_processing,values=['参考处理','全部原始点'],state='readonly',width=13)
        processing.pack(side='left');processing.bind('<<ComboboxSelected>>',self.change_beta_view)
        self.figure, self.ax, self.canvas = self._plot(chart)
        self.reset_measurement_plot()
        table = tk.Frame(self.measure_tabs, bg=BG); self.measure_tabs.add(table, text='测点数据')
        column_bar=tk.Frame(table,bg=BG);column_bar.pack(fill='x',padx=6,pady=3)
        self.add_column_button=self.button(column_bar,'＋',self.show_add_column_menu,color='#285a57');self.add_column_button.pack(side='left',padx=2)
        self.remove_column_button=self.button(column_bar,'−',self.remove_measurement_column,color='#354b6d');self.remove_column_button.pack(side='left',padx=2)
        self.remove_column_button.config(state='disabled')
        self.column_selection_text=tk.StringVar(value='点击列标题选择；＋添加列，−隐藏所选列')
        self.label(column_bar,textvariable=self.column_selection_text,fg=MUTED,anchor='w').pack(side='left',padx=8,fill='x',expand=True)
        self.label(table,'ADC2=RX1；ADC1=RX2。隐藏列不删除测点，完整原始数据仍保存在本次记录中。',fg=MUTED,wraplength=self.px(850),justify='left').pack(fill='x',padx=8,pady=2)
        self.table = ttk.Treeview(table, show='headings', columns=tuple(c[0] for c in TABLE_COLUMNS),displaycolumns=self.measurement_table_columns(self.selected_profile()))
        for name,label,width in TABLE_COLUMNS:
            self.set_measurement_heading(name,label); self.table.column(name,width=self.px(width),stretch=False)
        self.table.bind('<ButtonRelease-1>',self.select_measurement_column,add='+')
        self.table.tag_configure('curve_even',background='#f6f8fc')
        self.table.tag_configure('curve_odd',background='#e3edf8')
        hbar=ttk.Scrollbar(table,orient='horizontal',command=self.table.xview);hbar.pack(side='bottom',fill='x')
        bar = ttk.Scrollbar(table, orient='vertical', command=self.table.yview); bar.pack(side='right', fill='y')
        self.table.configure(yscrollcommand=bar.set,xscrollcommand=hbar.set); self.table.pack(fill='both', expand=True)
        self.sync_measurement_columns()
        summary = tk.Frame(self.measure_tabs, bg=BG); self.measure_tabs.add(summary, text='分析 / 运行记录')
        self.summary = tk.Text(summary, bg=PANEL, fg=FG, relief='flat', wrap='word', width=30, state='disabled')
        self.summary.pack(fill='both', expand=True)
        from .measurement_views import DerivedPlots
        self.derived_plots=DerivedPlots(self)
        self.measure_tabs.pack_forget()
        foot = tk.Frame(right, bg=BG); foot.pack(side='bottom', fill='x', pady=8)
        self.measure_tabs.pack(fill='both', expand=True)
        tools=[self.button(foot,'打开本次数据',self.open_result,color='#354b6d'),
               self.button(foot,'保存曲线 PNG',self.save_plot,color='#354b6d'),
               self.button(foot,'全览测点',self.show_all_points,color='#354b6d')]
        self.restore_result_button=self.button(foot,'载入最新曲线与数据',self.load_latest_result,color='#285a57')
        tools.append(self.restore_result_button)
        def arrange_tools(event=None):
            columns=4 if foot.winfo_width()>=sum(b.winfo_reqwidth()+8 for b in tools) else 2
            for i,button in enumerate(tools):button.grid(row=i//columns,column=i%columns,padx=(0,8),pady=3,sticky='w')
        foot.bind('<Configure>',arrange_tools);arrange_tools()

    def build_parameters(self):
        previous=getattr(self,'parameter_tab_name','基本')
        for child in self.param_tabs.winfo_children():child.destroy()
        self.config_vars = {}
        self.config_entries = {}
        self.config_labels = {}
        self.frontend_entries = {}
        self.update_route_summary()
        basic={'scan_mode','pulse_frequency_hz','pulse_duty_percent','tx1_start_v','tx1_stop_v','uce_values_v','base_control_v','tx2_control_start_v','tx2_control_stop_v','target_uce_v','tx1_bias_v','tx2_vcc_control_v','tx3_input_vpp'}
        step={'tx1_step_v','tx1_fine_stop_v','tx1_fine_step_v','tx2_control_step_v','tx2_first_start_v','tx2_start_increment_v','tx2_step_v','tx2_min_v','tx2_stop_v'}
        timing={'pulse_noise_span_v','pulse_attempts_per_frame','settle_s','curve_settle_s','frames_per_point','discard_frames','frame_gap_s','adaptive_settle_v','max_node_drift_v','sample_count','repeat_count'}
        self.parameter_panels={}
        for name,title in [('基本','基本参数'),('步进','扫描区间 / 分段步进'),('采集','采集与稳定时间'),('换算','换算与分析参数')]:
            panel=ScrollFrame(self.param_tabs);self.param_tabs.add(panel,text=name);self.parameter_panels[name]=panel
            self.label(panel.inner,title,font=('Microsoft YaHei UI',11,'bold')).pack(fill='x',padx=12,pady=(10,5))
        def select_tab(event=None):
            if event is not None:self.segment_editor.sync(strict=False)
            selected=self.param_tabs.select()
            if not selected:return
            self.parameter_tab_name=self.param_tabs.tab(selected,'text')
            self.param_scroll=self.parameter_panels[self.parameter_tab_name]
            self.param_host=self.param_scroll.inner
        self.param_tabs.bind('<<NotebookTabChanged>>',select_tab)
        cfg=self.config_values[self.measurement]
        segment_key={'input':'tx1_segments_v','beta':'tx1_segments_v','output':'tx2_segments_v','ac':'frequency_segments_hz'}[self.measurement]
        if self.measurement=='input':
            lo,hi,cut=cfg['tx1_start_v'],cfg['tx1_stop_v'],cfg['tx1_fine_stop_v']
            seed='{}:{}:{}'.format(lo,hi,cfg['tx1_step_v'])
            if lo<cut and cfg['tx1_fine_step_v']<cfg['tx1_step_v']:
                seed='{}:{}:{}'.format(lo,min(cut,hi),cfg['tx1_fine_step_v'])
                if cut<hi:seed+=';{}:{}:{}'.format(cut,hi,cfg['tx1_step_v'])
            reference='.02:.74:.02;.74:2:.04'
        elif self.measurement=='beta':
            seed='{}:{}:{}'.format(cfg['tx1_start_v'],cfg['tx1_stop_v'],cfg['tx1_step_v']);reference='.02:1:.04'
        elif self.measurement=='output':
            seed='{}:{}:{}'.format(cfg['tx2_control_start_v'],cfg['tx2_control_stop_v'],cfg['tx2_control_step_v'])
            reference='0:.1:.01;.1:1.8:.05'
        else:
            from .ac import DEFAULT_FREQUENCY_SEGMENTS
            seed=reference=DEFAULT_FREQUENCY_SEGMENTS
        self.segment_editor=SegmentEditor(self.parameter_panels['步进'].inner,self,segment_key,cfg.get(segment_key,''),seed,reference,1000 if self.measurement=='ac' else 1)
        self.segment_editor.pack(fill='x',pady=(0,12))
        legacy_steps={'tx1_step_v','tx1_fine_stop_v','tx1_fine_step_v','tx2_control_step_v'}
        range_keys=({'output':('tx2_control_start_v','tx2_control_stop_v')}.get(self.measurement,
                    ('tx1_start_v','tx1_stop_v')) if self.measurement!='ac' else ())
        if self.measurement=='beta':
            self.label(self.parameter_panels['步进'].inner,'TX2 目标偏置搜索',font=('Microsoft YaHei UI',11,'bold')).pack(fill='x',padx=12,pady=(10,5))
        for row, (key, value) in enumerate(self.config_values[self.measurement].items()):
            # Persist canonical Vpp for existing configs; edit peak volts in UI.
            if key=='tx3_input_vpp':value=format(float(value)/2,'.12g')
            value = ', '.join(str(v) for v in value) if isinstance(value, (tuple, list)) else str(value)
            var = tk.StringVar(value=value); self.config_vars[key] = var
            if key in ('profile',segment_key,'relay_active_level') or key in legacy_steps:continue
            if (key=='scan_mode' or key.startswith('pulse_')) and not self.selected_profile().big:continue
            if key=='ve_conversion_mode' and not self.selected_profile().pnp:continue
            if self.measurement=='input' and self.selected_profile().pnp and key=='uce_tolerance_v':continue
            group='基本' if key in basic else '步进' if key in step else '采集' if key in timing else '换算'
            host=self.parameter_panels[group].inner
            label=LABELS.get(key,key)
            if key=='uce_values_v' and self.selected_profile().pnp:label='VCC 列表 / V（TX1 功放）'
            if self.measurement=='input' and self.selected_profile().pnp:label=label.replace('TX1','TX2') if key!='uce_values_v' else label
            caption=self.label(host,label,fg=MUTED,anchor='w',justify='left',wraplength=self.px(310))
            caption.pack(fill='x',padx=14,pady=(10,3))
            caption.bind('<Configure>',lambda e:e.widget.configure(wraplength=max(40,e.width-4)))
            self.config_labels[key]=caption
            entry=(ttk.Combobox(host,textvariable=var,values=['实测表优先','线性比例'],state='readonly')
                   if key=='ve_conversion_mode' else ttk.Combobox(host,textvariable=var,values=['步进','脉冲'],state='readonly')
                   if key=='scan_mode' else ttk.Entry(host, textvariable=var))
            entry.pack(fill='x', padx=14);self.config_entries[key]=entry
            if key=='scan_mode':
                self.label(host,'脉冲频率、占空比在本页可调；TX2低电平0 V',fg=MUTED,font=('Microsoft YaHei UI',9),anchor='w',wraplength=0).pack(fill='x',padx=14,pady=4)
            if key=='pulse_noise_span_v':
                self.label(host,'限制帧内中央90%的噪声跨度；实际限值取本值与预计VCC的3%中较大者。平台变化和漂移另行检查。',fg=MUTED,wraplength=self.px(300),justify='left').pack(fill='x',padx=14,pady=4)
            if key=='ve_conversion_mode' and self.selected_profile().pnp:
                self.ve_conversion_text=tk.StringVar()
                self.label(host,textvariable=self.ve_conversion_text,fg=AMBER,wraplength=self.px(300),
                           justify='left',anchor='w').pack(fill='x',padx=14,pady=4)
                self.button(host,'查看 VE 实测表',self.show_ve_table,color='#354b6d').pack(anchor='w',padx=14,pady=2)
            if key=='base_resistance_ohm' and self.measurement in ('output','beta'):
                self.base_conversion_text=tk.StringVar()
                self.label(host,textvariable=self.base_conversion_text,fg=AMBER,
                           wraplength=self.px(300),justify='left',anchor='w').pack(fill='x',padx=14,pady=(4,2))
                self.button(host,'恢复本档 IB 换算',self.reset_base_conversion,color='#354b6d').pack(anchor='w',padx=14,pady=2)
            if key=='tx3_input_vpp':
                self.label(host,'峰峰值 = 2 × 峰值',fg=MUTED,font=('Microsoft YaHei UI',9),anchor='w').pack(fill='x',padx=14,pady=(3,0))
            if key in range_keys:
                entry.bind('<FocusOut>',lambda e:self.segment_editor.sync(strict=False))
                entry.bind('<Return>',lambda e:self.segment_editor.sync(strict=False))
        if range_keys:self.segment_editor.bind_range(*(self.config_vars[key] for key in range_keys))
        self.frontend_entries={}
        shared=('collector_amplifier_gain',)
        if self.measurement=='input':shared+=('rx1_per_vc','base_equivalent_resistance_ohm','max_uce_v')
        for key in shared:
            host=self.parameter_panels['换算'].inner
            label=('VE 线性比例（仅在线性比例模式生效）' if key=='rx1_per_vc' and self.selected_profile().pnp else LABELS[key]+'（共用前端）')
            self.label(host,label,fg=MUTED,wraplength=self.px(310),justify='left').pack(fill='x',padx=14,pady=(10,3))
            entry=ttk.Entry(host,textvariable=self.front_vars[key]);entry.pack(fill='x',padx=14)
            self.frontend_entries[key]=entry
        if self.measurement=='input' and self.selected_profile().pnp:
            self.label(self.parameter_panels['换算'].inner,'实测表优先：VE 使用已保存的表；线性比例：VE = RX 接口电压 / 反馈比例。',fg=MUTED,wraplength=self.px(310),justify='left').pack(fill='x',padx=14,pady=6)
        for var in self.config_vars.values():var.trace_add('write',lambda *_:self.update_route_summary())
        self.param_tabs.select(self.parameter_panels[previous]);select_tab()
        self.update_route_summary()

    def reset_base_conversion(self):
        if self.busy or self.queue_reserved():return
        self.config_vars['base_resistance_ohm'].set(format(self.selected_profile().base_ohm(self.measurement),'g'))

    def show_ve_table(self):
        try:channel=int(self.config_vars['collector_channel'].get())
        except ValueError:return
        table=self.scope_calibration.ve_conversion(self.selected_profile().key,channel)
        if not table:self.error('当前档位 / RX 通道没有匹配的 VE 实测表');return
        window=tk.Toplevel(self.root);window.title('VE 实测表 · '+self.selected_profile().label)
        window.geometry('{}x{}'.format(self.px(630),self.px(570)))
        ttk.Label(window,text='RX{} 接口电压 → VE；分段线性插值，表外按端点段外推。\n原始示波器实测点；PNP 输入档 87=0 共用。'.format(channel+1),padding=10).pack(fill='x')
        tree=ttk.Treeview(window,columns=('adc','ve'),show='headings')
        tree.heading('adc',text='ADC 接口电压 / V');tree.heading('ve',text='VE 实测电压 / V')
        bar=ttk.Scrollbar(window,orient='vertical',command=tree.yview);bar.pack(side='right',fill='y')
        tree.configure(yscrollcommand=bar.set);tree.pack(fill='both',expand=True,padx=10,pady=10)
        for point in table['points']:tree.insert('','end',values=('{:.9g}'.format(point['adc_v']),'{:.9g}'.format(point['ve_v'])))
        self.ve_table_window=window;self.ve_table_tree=tree

    def selected_profile(self):
        return Profile(next(k for k,v in PROFILE_LABELS.items() if v==self.profile.get()))

    def change_profile(self, event=None):
        if self.queue_reserved(): return
        if self.busy:return
        if self.config_vars:
            try:self.config_values[self.measurement]=self.read_config()
            except ValueError:pass
        self.cache_measurement_view()
        self.profile_configs[self._parameter_profile]=self.config_values
        profile=self.selected_profile()
        self._parameter_profile=profile.key
        self.config_values=self.profile_configs.get(profile.key) or self.saved_defaults_for(profile.key)
        self.restore_measurement_view()
        self.build_parameters()

    def update_route_summary(self):
        self.refresh_settings_summary()
        p=self.selected_profile();r=p.route(self.measurement)
        low,high=r['current_range_a']
        def current(v):return '{:g} mA'.format(v*1000) if v>=.001 else ('{:g} μA'.format(v*1e6) if v>=1e-6 else '{:g} nA'.format(v*1e9))
        cfg=dict(self.config_values.get(self.measurement,{}))
        for key,var in self.config_vars.items():
            if key not in cfg:continue
            try:
                old=cfg[key]
                if isinstance(old,(int,float)):cfg[key]=type(old)(var.get())
                elif isinstance(old,str):cfg[key]=var.get()
            except (ValueError,tk.TclError):pass
        try:front=self.read_frontend()
        except ValueError:front=Frontend.load(self.data/'frontend.json')
        rc=cfg.get('collector_resistor_ohm',p.collector_ohm)
        if self.measurement in ('output','beta'):
            resistance=float(cfg.get('base_resistance_ohm',p.base_ohm(self.measurement)))
            if math.isfinite(resistance) and resistance>0:
                low,high=(v/resistance for v in (.02,2.0))
                conversion='IB = TX1 / {:g} Ω；0.5 V → {:g} mA'.format(resistance,500/resistance)
            else:conversion='基极等效电阻须为正数'
            if hasattr(self,'base_conversion_text'):self.base_conversion_text.set(conversion)
        ratio=cfg.get('output_adc_per_v',.206) if self.measurement=='ac' else cfg.get('collector_adc_per_v',front.rx1_per_vc)
        collector=cfg.get('output_channel',1) if self.measurement=='ac' else cfg.get('collector_channel',1)
        other=cfg.get('input_channel',0) if self.measurement=='ac' else cfg.get('base_channel',0) if self.measurement=='input' else cfg.get('source_channel',0)
        if p.pnp:
            if self.measurement=='input':
                use_table=cfg.get('ve_conversion_mode','实测表优先')=='实测表优先'
                table=self.scope_calibration.ve_conversion(p.key,collector)
                ve_basis=('VE 实测表换算（{} 点）'.format(len(table['points'])) if table else 'VE 实测表缺失，禁止测量') if use_table else 'VE×{:g}'.format(ratio)
                if hasattr(self,'ve_conversion_text'):
                    self.ve_conversion_text.set(('RX{} → VE：{} 点实测表；87=0 共用，分段插值。'.format(collector+1,len(table['points'])) if table else '当前通道没有匹配实测表，不自动回退固定比例。') if use_table else 'VE = RX{} 接口电压 / {:g}；采用线性比例。'.format(collector+1,ratio))
                if 'rx1_per_vc' in getattr(self,'frontend_entries',{}):
                    self.frontend_entries['rx1_per_vc'].configure(state='disabled' if use_table or self.busy else 'normal')
                self.route_text.set('{} · TX1→功放 · TX2→恒流源 · RX{}={}；RX{}=VB×{:g} · C接地'.format(p.label,collector+1,ve_basis,other+1,cfg.get('base_adc_per_v',.25)))
                return
            feedback = 'VCC×{:g}'.format(cfg.get('source_adc_per_v',.206)) if self.measurement in ('output','beta') else 'VB×{:g}'.format(cfg.get('input_adc_per_v',9.78) if self.measurement=='ac' else cfg.get('base_adc_per_v',.25))
            self.route_text.set('{} · R {:g} Ω · RX{}=VE×{:g}；RX{}={}；C接地{}'.format(
                p.label,rc,collector+1,ratio,other+1,feedback,
                ' · IC≈IE，同相幅值近似' if self.measurement=='ac' else ' · IC≈IE' if self.measurement!='input' else ''))
            return
        self.route_text.set('{}  ·  档位 {}～{}  ·  RC {:g} Ω  |  RX{}={}×{:g}；RX{}={}'.format(
            p.label,current(low),current(high),rc,collector+1,'VC',ratio,other+1,
            'VCC×{:g}'.format(cfg.get('source_adc_per_v',.206)) if self.measurement in ('output','beta') else 'VB×{:g}'.format(cfg.get('input_adc_per_v',9.78) if self.measurement=='ac' else cfg.get('base_adc_per_v',.25))))

    def saved_defaults_for(self,profile):
        from .page_defaults import load_defaults
        return load_defaults(self.base/'measurement_defaults.json',profile,MEASUREMENTS)

    def load_frontend_defaults(self):
        values=asdict(Frontend.load(self.data/'frontend.json'))
        try:
            saved=json.loads((self.base/'frontend_defaults.json').read_text(encoding='utf-8'))
            values.update({k:v for k,v in saved.items() if k in values and k!='transfer_basis'})
            return Frontend(**values)
        except (OSError,ValueError,TypeError):return Frontend.load(self.data/'frontend.json')

    def read_frontend(self):
        values=asdict(Frontend.load(self.data/'frontend.json'))
        custom={key:float(var.get()) for key,var in self.front_vars.items()}
        if any(custom[key]!=values[key] for key in custom):values['transfer_basis']='desktop_user_parameters_unverified'
        values.update(custom)
        return Frontend(**values)

    def save_frontend_default(self):
        try:
            values=asdict(self.read_frontend())
            target=self.base/'frontend_defaults.json';temp=target.with_suffix('.tmp')
            temp.write_text(json.dumps(values,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temp.replace(target)
            self.notice.set('共用前端换算参数已保存为默认。')
        except Exception as error:self.error(error)

    def save_page_default(self):
        try:
            from .page_defaults import save_default
            config=self.read_config()
            MEASUREMENTS[self.measurement][0](**config).validate(self.scope_calibration,self.read_frontend())
            save_default(self.base/'measurement_defaults.json',self.selected_profile().key,self.measurement,config)
            self.config_values[self.measurement]=config
            self.save_frontend_default()
            self.log('已设为默认：'+self.selected_profile().label+' / '+NAMES[self.measurement])
            self.notice.set('本页参数已保存为默认，下次启动及切换回来仍保留。')
        except Exception as error:self.error(error)

    def reset_preset(self):
        if self.busy or self.queue_reserved():return
        self.config_values[self.measurement]=self.saved_defaults_for(self.selected_profile().key)[self.measurement]
        self.build_parameters()

    def read_config(self):
        spec=self.segment_editor.value()
        cls = MEASUREMENTS[self.measurement][0]
        defaults = asdict(cls())
        result = {}
        for key, variable in self.config_vars.items():
            value = spec if key==self.segment_editor.key else variable.get().strip()
            old = defaults[key]
            if isinstance(old, tuple): result[key] = tuple(float(v.strip()) for v in value.replace('，', ',').split(','))
            elif isinstance(old, int): result[key] = int(value)
            elif isinstance(old,str):result[key]=value
            else: result[key] = float(value)
            if key=='tx3_input_vpp':result[key]*=2
        # Legacy serialized fields are derived compatibility values, never a
        # second editable plan. Actual acquisition consumes the interval table.
        step=float(spec.split(';')[-1].split(':')[2])
        if 'tx1_step_v' in result:result['tx1_step_v']=step
        if 'tx2_control_step_v' in result:result['tx2_control_step_v']=step
        if 'tx1_fine_stop_v' in result:
            result['tx1_fine_stop_v']=0.0;result['tx1_fine_step_v']=step
        return result

    def _settings_page(self):
        page = self._new_page('settings')
        scroll = ScrollFrame(page); scroll.pack(fill='both', expand=True)
        content=scroll.inner;content.columnconfigure(0,weight=1)
        panel=tk.Frame(content,bg=PANEL);panel.grid(row=0,column=0)
        self.settings_form=panel
        self.label(panel, '模拟前端参数', font=('Microsoft YaHei UI', 14, 'bold'),anchor='center').grid(row=0, column=0, columnspan=3, sticky='ew', padx=12, pady=12)
        for row,(key,var) in enumerate(self.front_vars.items(),1):
            self._entry(panel, LABELS.get(key, key), var, row)
            var.trace_add('write',lambda *_:self.update_route_summary())
        self.button(panel, '加载本板校准复核记录 JSON', self.load_qualification, color='#354b6d').grid(row=6, column=0, columnspan=2, sticky='w', padx=12, pady=12)
        self.button(panel,'保存前端为默认',self.save_frontend_default,color='#285a57').grid(row=6,column=2,sticky='w',padx=12,pady=12)
        self.qual_label = self.label(panel, 'RX 接口的标称 DC 校准不代替 BJT 测试电路换算、恒流源和交流链路复核。', fg=AMBER,
                                     wraplength=self.px(950), justify='left')
        self.qual_label.grid(row=7, column=0, columnspan=2, sticky='w', padx=12, pady=6)
        self.confirmation_button(panel,self.fixture,'BJT 测试板、接线和负载').grid(row=8,column=0,columnspan=2,sticky='ew',padx=12,pady=8)
        self.settings_summary=tk.StringVar()
        self.settings_summary_label=self.label(content,textvariable=self.settings_summary,fg=MUTED,justify='center',anchor='center',wraplength=self.px(950))
        self.settings_summary_label.grid(row=1,column=0,sticky='ew',padx=14,pady=18)
        self.settings_summary_label.bind('<Configure>',lambda e:e.widget.configure(wraplength=max(100,e.width-16)))
        self.refresh_settings_summary()

    def refresh_settings_summary(self):
        if not hasattr(self,'settings_summary'):return
        lines=['当前功能与参数','',
               'TX1 直流；TX2 / TX3 直流与波形；双路 ADC；七路 IO；LCD 联动。',
               'NPN / PNP × 小功率 / 大功率：输入、输出 / Early、β 线性、交流 / fβ / fT。','',
               '交流测量：同一极性的大小功率共用小功率继电器档位；87=0，77/48=00，83/85=01。',
               'NPN：79/81=00；PNP：79/81=11。','']
        for key,label in PROFILE_LABELS.items():
            configs=self.config_values if key==self._parameter_profile else self.profile_configs.get(key) or self.saved_defaults_for(key)
            output=dict(configs['output']);ac=dict(configs['ac'])
            if key==self._parameter_profile and self.measurement in ('output','ac'):
                cfg=output if self.measurement=='output' else ac
                for field,var in self.config_vars.items():
                    if field in cfg:
                        try:cfg[field]=float(var.get()) if isinstance(cfg[field],(int,float)) else var.get()
                        except ValueError:pass
            lines.append('{}：输出 RC={} Ω；交流 RC={} Ω，RB={} Ω。'.format(label,output['collector_resistor_ohm'],ac['collector_resistor_ohm'],ac['base_resistance_ohm']))
            lines.append('交流 VB 反馈比例={}，输出反馈比例={}，串联测试电阻={} Ω，缓冲增益={}。'.format(ac['input_adc_per_v'],ac['output_adc_per_v'],ac['input_test_resistor_ohm'],ac['source_buffer_gain']))
        gain=self.front_vars['collector_amplifier_gain'].get()
        lines+=['','功放增益：{} 倍；各测量页的实时参数随记录保存。'.format(gain),
                'PNP 输入：C 接地；ADC1/RX2 测 VE，ADC2/RX1 测 VB；UEB=VE−VB；TX1=VCC/功放增益。',
                'PNP 输出 / β：ADC1/RX2 测 VE，ADC2/RX1 测 VCC；IC≈IE=(VCC−VE)/RC。',
                'PNP 交流：β≈(RB/RC)×VE/(Vin−VB)；采用 Vin、VB 同相的幅值近似。','',
                '自动识别统一使用小功率档、RC=50 Ω；判别极性后保留所选功率类别。',
                'NPN / PNP 大功率输出 / β 支持可调频率、占空比的脉冲；步进与脉冲分目录保存。',
                'PNP 交流可切换曲线一与曲线二；输入电阻随采集逐点显示。',
                'ADC 每路 256～4096 点，抽取 1～256 倍；时钟按板端支持档位选择。',
                '停止 / 断开关闭输出并复位 IO；断网后板端按心跳超时清理。','',
                '电脑数据目录：'+str(self.results)]
        self.settings_summary.set('\n'.join(lines))

    def show_page(self, name):
        if self.queue_reserved(): return
        if self.busy and name in NAMES: return
        if name != 'meter' and self.meter.running: self.meter.stop()
        if name != 'scope' and self.scope.accepting: self.scope.stop()
        if self.config_vars:
            try: self.config_values[self.measurement] = self.read_config()
            except ValueError: pass
        if name in NAMES and self.measurement != name:self.cache_measurement_view()
        for frame in self.pages.values(): frame.pack_forget()
        if name in NAMES:
            changed = self.measurement != name
            self.measurement = name; self.build_parameters()
            self.pages['measurement'].pack(fill='both', expand=True)
            self.page_title.config(text='BJT  /  '+NAMES[name])
            if changed:
                self.restore_measurement_view()
        else:
            self.pages[name].pack(fill='both', expand=True)
            self.page_title.config(text={'tx': 'TX  /  激励输出', 'scope': 'RX  /  双通道采集', 'meter':'RX  /  双通道电压表', 'gpio': 'IO  /  七路数字控制', 'settings': '设置与参数'}[name])
        if name=='settings':self.refresh_settings_summary()
        for key, button in self.nav_buttons.items(): button.config(bg=BLUE if key == name else PANEL)
        if hasattr(self,'lcd'):self.lcd.page(name)

    def connect(self):
        self.scope.history.clear()
        if self.busy or self.transport is not None: return
        source, host, user, password = self.source.get(), self.host.get().strip(), self.user.get().strip(), self.password.get()
        if source == 'PYNQ 实板' and not password:
            self.error('请输入 PYNQ 登录密码'); return
        def task():
            emit = lambda k, v: self.events.put(('event', k, v))
            if source == '离线模拟':
                transport = LocalTransport(self.data, self.results, emit)
                result = transport.call('status')
            else:
                transport = SshTransport(emit)
                bundle = assets()/'agent.pyz'
                archive = bundle.read_bytes() if bundle.exists() else agent_archive(Path(__file__).parent)
                selected_bitfile=getattr(self,'board_bitfile',None)
                options=dict(bitfile=selected_bitfile) if selected_bitfile else {}
                result = transport.connect(host, user, password, self.base/'known_hosts', self.data, archive,**options)
            self.transport = transport if transport.simulated else SharedTransport(transport)
            return result
        self.notice.set('正在验证账户并读取板端状态…' if source=='PYNQ 实板' else '正在打开离线模拟…')
        self.start_job('connect', task)

    def submit(self, op, args=None):
        if self.queue_reserved() and op not in ('stop','disconnect'): return
        if self.busy or not self.transport: return
        transport = self.transport
        transport.prepare()
        self.start_job(op, lambda: transport.call(op, args, timeout=7200 if op=='scan' else 120))

    def start_job(self, op, function):
        if self.queue_reserved() and op not in ('scan','stop','disconnect'): return
        if op != 'capture' and self.scope.accepting: self.scope.stop()
        if op != 'meter' and self.meter.running: self.meter.stop()
        self.busy = True; self.controls(); self.progress.start(12)
        self.active_job=op
        self.progress_text.set('处理中：'+op)
        lcd_packet=None
        if hasattr(self,'lcd'):
            try:lcd_packet=self.lcd.before_job(op)
            except Exception as error:self.log('LCD 画面暂未更新：'+str(error))
        transport=self.transport
        def work():
            if lcd_packet and transport:
                try:transport.call('lcd',lcd_packet,timeout=30)
                except Exception as error:self.events.put(('event','log','LCD 画面暂未更新：'+str(error)))
            try: self.events.put(('done', op, function()))
            except Exception as error: self.events.put(('error', op, str(error)))
        threading.Thread(target=work, daemon=True).start()

    def controls(self):
        connected = self.transport is not None and self.transport.alive
        reserved = self.queue_reserved()
        for button in self.actions: button.config(state='normal' if connected and not self.busy and not reserved else 'disabled')
        if self.last_status and self.last_status.get('initialized'): self.init_button.config(state='disabled')
        self.connect_button.config(state='normal' if not connected and not self.busy else 'disabled')
        self.source_combo.config(state='readonly' if not connected and not self.busy else 'disabled')
        for entry in self.login_entries: entry.config(state='normal' if not connected and not self.busy else 'disabled')
        self.disconnect_button.config(state='normal' if connected else 'disabled')
        self.stop_button.config(state='normal' if connected else 'disabled')
        self.profile_combo.config(state='disabled' if self.busy or reserved else 'readonly')
        self.scope.controls()
        self.meter.controls()

    def queue_reserved(self):
        tools=getattr(self,'tools',None)
        return bool(tools and tools.queue_running and not tools.internal)

    def scan_request(self, validate=True):
        profile=self.selected_profile()
        config=self.read_config() if validate else {}
        front=asdict(self.read_frontend())
        if validate:
            MEASUREMENTS[self.measurement][0](**config).validate(Calibration(self.data),Frontend(**front))
            self.config_values[self.measurement]=config
        reference=self.reference_mode.get().startswith('参考换算')
        if self.transport and not self.transport.simulated and not reference and self.qualification is None:
            raise ValueError('已复核标定模式需要相应测量链路的真实复核记录')
        return dict(measurement=self.measurement,config=config,frontend=front,
                    qualification=self.qualification,fixture_confirmed=self.fixture.get(),profile=profile.key,
                    method='pulse' if config.get('scan_mode')=='脉冲' else 'step',allow_reference=reference,prepare_outputs=True,analysis_on_host=self.measurement=='ac',
                    device=self.tools.device() if hasattr(self,'tools') else {})

    def start_scan(self):
        if self.busy or not self.transport or self.queue_reserved(): return
        try:self.execute_scan(self.scan_request())
        except Exception as error:self.error(error)

    def execute_scan(self,args):
        if self.busy or not self.transport:raise RuntimeError('仪器忙或已断开')
        args=dict(args)
        self.active_device=dict(args.get('device',{}))
        self.last_result=None
        self.rows=[];self.table.delete(*self.table.get_children());self.reset_measurement_plot()
        if hasattr(self,'lcd'):self.lcd.begin_scan(args)
        transport=self.transport;transport.prepare()
        def scan():
            result=transport.call('scan',args,timeout=7200)
            try:
                result['local_directory']=str(transport.fetch(result,self.results))
                if result['state'].get('status')=='acquired':
                    from .ac import finish_host_analysis
                    result['state']=finish_host_analysis(Path(result['local_directory']))
            except Exception as error:result['download_error']=str(error)
            return result
        self.start_job('scan',scan)

    def demo_preset(self):
        if self.busy or self.queue_reserved():return
        if not self.transport or not self.transport.simulated:
            self.error('“模拟参数”仅在已连接离线模拟时可用'); return
        config = defaults_for(self.measurement,MEASUREMENTS[self.measurement][0],self.selected_profile().key)
        config.update(settle_s=0)
        if self.measurement == 'input': config.update(tx1_stop_v=.3, tx1_step_v=.02, uce_values_v=(1, 2), curve_settle_s=0, frame_gap_s=0)
        self.config_values[self.measurement] = config; self.build_parameters()
        self.log('已填写离线模型参数；实板反馈比例必须另行核实。')

    def stop(self):
        if hasattr(self,'tools'):self.tools.cancel_queue()
        self.scope.stop()
        self.meter.stop()
        if not self.transport: return
        if self.busy:
            try:
                self.stop_after = True
                self.transport.cancel(); self.notice.set('已请求取消，等待任务退出后停止输出并将七路 IO 全部复位。')
            except Exception as error: self.error(error)
        else: self.submit('stop')

    def disconnect(self):
        if hasattr(self,'tools'):self.tools.cancel_queue()
        self.scope.stop('断开 · STOP')
        self.meter.stop('已断开 · 保留最近读数')
        if not self.transport: return
        if self.busy:
            self.close_after = True; self.stop(); return
        transport = self.transport
        self.start_job('disconnect', transport.close)

    def close(self):
        self.closing = True; self.live = False
        if self.transport: self.disconnect()
        elif self.busy: self.close_after = True
        else: self._finish_close()

    def _finish_close(self):
        if hasattr(self,'lcd'):self.lcd.close()
        if hasattr(self,'tools'):self.tools.close()
        self._save_settings(); self.root.destroy()

    def pump(self):
        try:
            for _ in range(100):
                kind, op, value = self.events.get_nowait()
                if kind == 'lcd_reply':
                    self.lcd.reply(value);continue
                if kind == 'event': self.handle_event(op, value); continue
                self.busy = False; self.progress.stop(); self.progress_text.set('就绪')
                self.active_job=None
                if kind == 'error':
                    self.scope.stop('采集/通信异常 · STOP'); self.error(value)
                    self.meter.stop('采集/通信异常 · 保留最近读数')
                    if op in ('output', 'initialize', 'adc_clock', 'stop', 'disconnect'):
                        self.tx_state.config(text='操作未确认，请重新读取状态')
                    if op == 'disconnect':
                        self.transport = None; self.last_status = None
                        self.status_var.set('已断开 · 清理未确认')
                    elif self.transport and not self.transport.alive:
                        self.transport = None; self.last_status = None
                        self.status_var.set('连接中断 · 输出状态未知')
                else: self.completed(op, value)
                if hasattr(self,'tools'):self.tools.on_job(kind,op,value)
                self.controls()
                if not self.transport: self.show_login()
                if self.close_after:
                    self.close_after = False
                    self.stop_after = False
                    if self.transport: self.disconnect()
                elif self.stop_after:
                    self.stop_after = False
                    if self.transport:
                        self.submit('stop')
                if self.closing and not self.busy and not self.transport:
                    self._finish_close(); return
                if not self.busy and not self.closing:self.lcd.drain_touch()
        except queue.Empty: pass
        self.root.after(30, self.pump)

    def completed(self, op, value):
        if op in ('connect', 'initialize', 'adc_clock', 'status', 'output', 'gpio', 'stop', 'relay_route'):
            self.render_status(value)
            self.log('{}：完成'.format(op))
            if op in ('initialize','adc_clock'):self.scope.clock_applied(value)
            if op == 'connect':
                self.lcd.connected()
                self.enter_workbench()
                self.password.set('')
                self._save_settings()
                (self.base/'last_connection.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
                if value.get('ssh_fingerprint'): self.log('SSH '+value['ssh_fingerprint'])
        elif op == 'capture':
            self.render_capture(value)
            self.scope.schedule()
        elif op == 'meter':
            self.meter.receive(value)
        elif op == 'scan':
            self.last_result = value
            self.result_by_measurement[(self._parameter_profile,self.measurement)] = value
            state = value['state']
            self.log('测量状态：{}，{} 点。'.format(state['status'], state['points']))
            if value.get('download_error'): self.log('数据仍在板端，取回失败：'+value['download_error'])
            self.set_summary(state)
            if value.get('local_directory'): self.read_result(Path(value['local_directory']))
            self.cache_measurement_view()
            self.progress_text.set('测量：'+state['status'])
            self.notice.set('模拟结果' if state['simulated'] else '实板记录：'+state['status'])
        elif op == 'retrieve':
            self.log('已取回 {} 个板端运行目录'.format(len(value)))
        elif op == 'disconnect':
            self.transport = None; self.last_status = None
            self.render_gpio_selection()
            for label in self.gpio_labels: label.config(text='已断开 / 回读未知', fg=MUTED)
            self.status_var.set('已断开 · 本会话清理已确认')
            self.notice.set('可重新连接；初始化不会自动开启输出。')
            self.tx_state.config(text='已断开 · 本会话输出已停止')
            self.log('退出清理已确认')
            self.show_login()
            self.lcd.connected()
        if op == 'stop':
            self.notice.set('三路输出已停止，七路 IO 已全部复位；器件关断不保证接口精确零伏。'
                            if value.get('initialized') else '七路 IO 已全部复位。')

    def handle_event(self, kind, value):
        if kind == 'instrument_status':
            self.render_status(value)
        elif kind == 'instrument_status_unknown':
            self.tx_state.config(text='输出状态未确认 · '+str(value))
        elif kind == 'connection_lost':
            self.show_login()
            if not self.closing:
                self.status_var.set('连接已断开 · 输出状态未知')
                self.notice.set('未收到板端确认。恢复连接后重新读取状态。')
            self.scope.stop('连接中断 · STOP')
            self.meter.stop('连接中断 · 保留最近读数')
            self.last_status = None
            self.tx_state.config(text='连接中断 · 输出状态未知')
            self.render_gpio_selection()
            for label in self.gpio_labels: label.config(text='设定 —  /  回读 —', fg=AMBER)
            if not self.busy: self.transport = None; self.controls()
        elif kind == 'point':
            self.rows.append(value)
            phase=('截止频率补测' if value.get('mode')=='refine' else '由低到高扫频') if self.measurement=='ac' else ''
            self.progress_text.set('{} · 已收到 {} 个测点'.format(phase,len(self.rows)) if phase else '已收到 {} 个测点'.format(len(self.rows)))
            self.append_table_row(value, len(self.rows))
            self.queue_plot()
        elif kind == 'curve': self.log('曲线 {}：{} 点'.format(value.get('index'), value.get('points')))
        elif kind == 'log': self.log(str(value))
        elif kind == 'session_closed' and value.get('cleanup_errors'):
            self.error('板端清理未确认：'+str(value['cleanup_errors']))

    def render_status(self, value):
        self.last_status = value
        if value.get('simulated') or 'identity' in value:
            self.scope_calibration.select_tx2_waveform_profile(None if value.get('simulated') else value['identity'])
        mode = '离线模拟' if value.get('simulated') else 'PYNQ 实板'
        suffix = '已初始化' if value.get('initialized') else ('IO 控制 · ADC/DAC 未初始化' if value.get('gpio_active') else '只读连接')
        self.status_var.set('{} · {}'.format(mode, suffix))
        self.notice.set('')
        if 'outputs' in value:
            self.tx_state.config(text=output_summary(value))
        identity=value.get('identity',{})
        divider=identity.get('dac_divider')
        clock=value.get('dac_rate_hz') or (1e9/divider if divider else None)
        rates=identity.get('measured_clock_hz',[])
        clock_text=('离线模拟，无硬件时钟' if value.get('simulated') else
                    ('DAC 采样时钟：{:g} MHz'.format(clock/1e6) if clock else 'DAC 采样时钟：尚未读取'))
        if not value.get('simulated') and len(rates)==3:
            clock_text+=' · 计数器实读 {:.3f} MHz'.format(rates[2]/1e6)
        self.tx_clock_state.config(text=clock_text)
        if 'gpio' in value:
            gpio = value['gpio']
            self.render_gpio_selection(gpio['output'])
            for i, label in enumerate(self.gpio_labels):
                out, sense = (gpio['output']>>i)&1, (gpio['sense']>>i)&1
                label.config(text='设定 {}  /  回读 {}'.format(out, sense), fg=GREEN if out==sense else AMBER)

    def start_live(self):
        self.scope.run()

    def render_capture(self, frame):
        self.scope.receive(frame)

    def save_frame(self):
        if not self.last_frame: self.error('尚无采样帧'); return
        try: self.scope.validate()
        except ValueError as error: self.error(error); return
        from .result_paths import create_run
        folder = create_run(self.results,'instrument','scope')
        frame = self.last_frame
        (folder/'frame.json').write_text(json.dumps(frame, indent=2), encoding='utf-8')
        converted = reference_channels(frame, self.scope_calibration)
        (folder/'voltage_reference.json').write_text(json.dumps(dict(voltage_qualified=False,
            basis='per_channel_reference_basis_not_transistor_terminal_voltage', channels=converted,
            calibration=self.scope_calibration.manifest()), indent=2), encoding='utf-8')
        with (folder/'samples.csv').open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f); writer.writerow(['index', 'rx1_time_s', 'rx1_code', 'rx1_or', 'rx2_time_s', 'rx2_code', 'rx2_or', 'simulated',
                'rx1_reference_v_unverified', 'rx2_reference_v_unverified', 'voltage_qualified'])
            for i, (a, b) in enumerate(zip(*frame['words'])):
                writer.writerow([i, i/frame['sample_rates_hz'][0], a&65535, a>>16, i/frame['sample_rates_hz'][1], b&65535, b>>16, int(frame['simulated']),
                    converted[0]['reference_volts'][i], converted[1]['reference_volts'][i], 0])
        (folder/'display_settings.json').write_text(json.dumps(self.scope.settings(), ensure_ascii=False, indent=2), encoding='utf-8')
        self.scope.export_png(folder/'waveform.png')
        if self.scope.display_mode.get() == 'FFT 频域':
            self.scope.export_spectrum(folder/'spectrum.csv')
        self.log('原始帧、CSV、显示参数及波形图已保存：'+str(folder))

    def queue_plot(self):
        if self._plot_job is None:
            delay = max(0, int(100 - (time.monotonic()-self._last_plot_time)*1000))
            self._plot_job = self.root.after(delay, self._flush_plot)

    def _flush_plot(self):
        self._plot_job = None
        self.plot_rows(self.rows)

    def input_plot_axes(self):
        self.ax.set(xlim=(.2, .8), ylim=(0, 10.5), xlabel=self.selected_profile().input_axis+' (V)',
                    ylabel='IB estimate (uA)')
        self.ax.set_autoscale_on(False)

    def reset_measurement_plot(self):
        if self._plot_job is not None:
            self.root.after_cancel(self._plot_job); self._plot_job = None
        self.figure.clear()
        if hasattr(self,'table'):
            self.table.config(displaycolumns=self.measurement_table_columns(self.selected_profile()))
        self.ax=self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=.13,right=.96,bottom=.15,top=.9)
        if self.measurement=='beta':
            self.beta_selector_bar.pack(fill='x',pady=5,before=self.canvas.get_tk_widget())
            self.ax.set(xlabel=BETA_VIEWS[self.beta_view.get()][4],ylabel=BETA_VIEWS[self.beta_view.get()][5])
        else:
            self.beta_selector_bar.pack_forget()
        self._ac_y_limits=None
        self._ac_artists=[]
        if self.measurement=='ac':
            self.ax.set_xscale('log'); self.ax.set_xlim(*self.ac_frequency_limits())
            self.ax.set_ylim(30,120); self.ax.set_autoscale_on(False)
        self._curve_lines = {}; self._plot_context = None
        if self.measurement == 'input':
            self.input_plot_axes()
            self.ax.set_title('Input characteristic / '+self.selected_profile().key.upper())
        self.ax.grid(alpha=.2); self.canvas.draw_idle()

    def change_beta_view(self, event=None):
        if self.measurement!='beta': return
        self.reset_measurement_plot()
        self.plot_rows(self.rows)

    def ac_plot_limits(self, rows):
        gains=[float(p['gain']) for p in rows if 'gain' in p and math.isfinite(float(p['gain']))]
        if not gains: return
        if self._ac_y_limits is None:
            self._ac_y_limits=(30.0,gains[0]+20.0)
        low,high=self._ac_y_limits
        if min(gains)<low: low=min(gains)-max(2.0,abs(min(gains))*.05)
        if max(gains)>high: high=max(gains)+20.0
        self._ac_y_limits=(low,high)
        self.ax.set_ylim(low,high)
        self.ax.set_xlim(*self.ac_frequency_limits())
        self.ax.set_autoscale_on(False)

    def ac_frequency_limits(self):
        cfg=self.last_result['state'].get('config',{}) if self.last_result and self.last_result['state'].get('measurement')=='ac' else self.config_values['ac']
        try:
            from .ac import DEFAULT_FREQUENCY_SEGMENTS
            values=segmented_values(cfg.get('frequency_segments_hz',DEFAULT_FREQUENCY_SEGMENTS),1000,5000000,500)
            return values[0],values[-1]
        except ValueError:return 10000,5000000

    def annotate_ac(self,rows):
        for artist in getattr(self,'_ac_artists',[]):
            try:artist.remove()
            except (ValueError,NotImplementedError):pass
        self._ac_artists=[]
        points=sorted((p for p in rows if float(p.get('gain',0))>0),key=lambda p:float(p['actual_freq_hz']))
        if not points:return
        first=points[0];f0,g0=float(first['actual_freq_hz']),float(first['gain'])
        self._ac_artists.append(self.ax.annotate('首点 {:.3g} kHz / β={:.2f}'.format(f0/1000,g0),(f0,g0),xytext=(12,12),textcoords='offset points',fontsize=8,color='#236646'))
        fit=self.last_result['state'].get('ac_analysis') if self.last_result else None
        if not fit:return
        au,fb,target=fit['au'],fit['f_beta_hz'],fit['target_gain']
        self._ac_artists.extend([self.ax.axhline(au,color='#288355',ls='--',lw=1,label='β0={:.2f}（拟合）'.format(au)),
            self.ax.axhline(target,color='#bd554a',ls='--',lw=1,label='0.707 β0={:.2f}'.format(target))])
        flo,fhi=min(float(p['actual_freq_hz']) for p in points),max(float(p['actual_freq_hz']) for p in points)
        if flo<=fb<=fhi:
            self._ac_artists.extend([self.ax.axvline(fb,color='#8266b5',ls=':',lw=1),
                self.ax.plot([fb],[target],'o',color='#8266b5',ms=6)[0],
                self.ax.annotate('fβ='+('{:.3f} MHz'.format(fb/1e6) if fb>=1e6 else '{:.1f} kHz'.format(fb/1000))+'（拟合）',(fb,target),xytext=(-12,20),ha='right',textcoords='offset points',fontsize=8,color='#7251a2')])
        last=points[-1];fe,ge=float(last['actual_freq_hz']),float(last['gain'])
        self._ac_artists.append(self.ax.annotate('终点 {:.3g} MHz / β={:.2f}'.format(fe/1e6,ge),(fe,ge),xytext=(-12,15),ha='right',textcoords='offset points',fontsize=8))
        extra='fT≈{:.3g} MHz（β0×fβ，估算）'.format(fit['ft_hz']/1e6)
        if not flo<=fb<=fhi:extra='fβ≈{:.3g} MHz（超出实测范围）\n'.format(fb/1e6)+extra
        self._ac_artists.append(self.ax.text(.98,.97,extra,ha='right',va='top',transform=self.ax.transAxes,fontsize=8,bbox=dict(facecolor='white',alpha=.8,edgecolor='#ccd5df')))
        self.ax.legend(fontsize=8,loc='lower left')

    def show_all_points(self):
        if not self.rows: return
        self.ax.relim(); self.ax.set_autoscale_on(True); self.ax.autoscale_view()
        if self.measurement == 'input': self.ax.set_autoscale_on(False)
        self.canvas.draw_idle()

    def plot_rows(self, rows):
        if self._plot_job is not None:
            self.root.after_cancel(self._plot_job)
            self._plot_job = None
        if hasattr(self,'derived_plots'):self.derived_plots.refresh(rows)
        if not rows:
            self.reset_measurement_plot()
            return
        self._last_plot_time = time.monotonic()
        name = self.measurement
        profile=Profile(self.last_result['state'].get('profile','npn_small')) if self.last_result else self.selected_profile()
        simulated = (self.last_result['state']['simulated'] if self.last_result else
                     bool(self.transport and self.transport.simulated))
        basis=self.last_result['state'].get('measurement_basis') if self.last_result else ('reference_parameters_unverified' if self.reference_mode.get().startswith('参考') else 'qualified_measurement')
        context = (name, profile.key, simulated, basis, self.beta_view.get() if name=='beta' else None,self.beta_processing.get() if name=='beta' else None)
        if context != self._plot_context or any(line not in self.ax.lines for line in self._curve_lines.values()):
            self.ax.clear()
            self._curve_lines = {}
            self._plot_context = context
            if name == 'input': self.input_plot_axes()
        xkey, ykey, xs, ys = {'input': ('ube_v', 'ib_estimated_a', 1, 1e6),
                              'output': ('uce_v', 'ic_a', 1, 1e3),
                              'beta': ('ib_estimated_a', 'ic_a', 1e6, 1e3),
                              'ac': ('actual_freq_hz', 'gain', 1, 1)}[name]
        if name=='beta':
            xkey,ykey,xs,ys,_,_=BETA_VIEWS[self.beta_view.get()]
            # Derive beta from the same measured IC / estimated IB for every view.
            rows=[dict(p,beta=float(p['ic_a'])/float(p['ib_estimated_a'])) for p in rows
                  if float(p.get('ib_estimated_a',0))>0 and 'ic_a' in p]
            cfg=self.last_result['state'].get('config',self.config_values['beta']) if self.last_result else self.config_values['beta']
            if self.beta_processing.get()=='参考处理':
                rows=sorted((p for p in rows if int(p.get('curve',0))>=cfg.get('drop_initial_points',2)),key=lambda p:float(p['ib_estimated_a']))
                window=cfg.get('moving_average_window',2)
                if window>1 and len(rows)>=window:
                    rows=[dict(rows[i],**{key:sum(float(p[key]) for p in rows[i:i+window])/window for key in ('ic_a','ib_estimated_a','beta')}) for i in range(len(rows)-window+1)]
        groups = {}
        for row in rows:
            if xkey in row and ykey in row: groups.setdefault(0 if name == 'beta' else (('refine' if row.get('mode')=='refine' else 'sweep') if name=='ac' else row.get('curve', 0)), []).append(row)
        legend_changed = False
        for key in set(self._curve_lines)-set(groups):
            self._curve_lines.pop(key).remove()
            legend_changed = True
        for key, points in groups.items():
            if name == 'beta': points = sorted(points, key=lambda p: float(p[xkey]))
            if name == 'ac': points = sorted(points, key=lambda p: float(p['actual_freq_hz']))
            first=points[0]
            legend=('IB = {:.3g} {}'.format(float(first['ib_estimated_a'])*(1e3 if profile.big else 1e6),'mA' if profile.big else 'uA') if name=='output' and 'ib_estimated_a' in first else
                    'VCC = {:.3g} V'.format(float(first['vcc_v'])) if name=='input' and profile.pnp and first.get('vcc_v') not in (None,'') else
                    'Bias = {:.3g} V'.format(float(first['uce_target_v'])) if name=='input' and 'uce_target_v' in first else
                    self.beta_view.get() if name=='beta' else ('二分补测' if key=='refine' else '顺序扫描') if name=='ac' else 'Curve '+str(key))
            if key not in self._curve_lines:
                self._curve_lines[key], = self.ax.plot([], [], 'D' if name=='ac' and key=='refine' else '.-', label=legend, linewidth=1.5, markersize=5 if key=='refine' else 4, **({'color':'#e88722'} if name=='ac' and key=='refine' else {'color':'#247bc1'} if name=='ac' else {}))
                legend_changed = True
            line = self._curve_lines[key]
            if line.get_label() != legend:
                line.set_label(legend); legend_changed = True
            line.set_data([float(p[xkey])*xs for p in points], [float(p[ykey])*ys for p in points])
        prior_fit = getattr(self, '_beta_fit_line', None)
        if prior_fit is not None and prior_fit in self.ax.lines: prior_fit.remove()
        self._beta_fit_line = None
        if name == 'beta' and self.beta_view.get()=='IC–IB' and self.last_result and self.last_result['state'].get('beta'):
            state = self.last_result['state']; fit = state['beta']
            dropped = state.get('config', {}).get('drop_initial_points', 0)
            fit_rows = [p for p in rows if int(p.get('curve', 0)) >= dropped]
            if fit_rows:
                ib = [float(p['ib_estimated_a']) for p in fit_rows]
                limits = (min(ib), max(ib))
                self._beta_fit_line, = self.ax.plot([v*1e6 for v in limits],
                    [(fit['fit_slope_beta']*v+fit['fit_intercept_a'])*1e3 for v in limits],
                    '--', color='#ff9755', label='Fit (initial {} excluded)'.format(dropped))
                legend_changed = True
        if name == 'ac': self.ax.set_xscale('log')
        else: self.ax.set_xscale('linear')
        labels = {'input': (profile.input_axis+' (V)', 'IB estimate (uA)'), 'output': (profile.voltage_axis+' (V)', 'IC (mA)'), 'beta': ('IB estimate (uA)', 'IC (mA)'), 'ac': ('Frequency (Hz)', 'Current gain |beta| (A/A)')}
        if name=='beta': labels['beta']=BETA_VIEWS[self.beta_view.get()][4:6]
        self.ax.set(xlabel=labels[name][0], ylabel=labels[name][1], title=('SIMULATED' if simulated else 'REFERENCE PARAMETERS' if basis=='reference_parameters_unverified' else 'HARDWARE')+' / '+profile.key.upper())
        if name=='beta':
            note='原始点' if self.beta_processing.get()=='全部原始点' else '排除前{}档 / {}点平均'.format(cfg.get('drop_initial_points',2),cfg.get('moving_average_window',2))
            source='SIMULATED' if simulated else '参考换算' if basis=='reference_parameters_unverified' else 'HARDWARE'
            self.ax.set_title('{} | {}={:g} V · {} · {}'.format(source,profile.voltage_axis,cfg.get('target_uce_v',5),self.beta_view.get(),note),fontsize=10)
        self.ax.grid(alpha=.2)
        if groups and legend_changed: self.ax.legend(fontsize=8)
        if name=='ac':
            self.ac_plot_limits(rows)
            self.annotate_ac(rows)
        elif name != 'input':
            self.ax.relim(); self.ax.autoscale_view()
        else:
            xlo,xhi=self.ax.get_xlim(); ylo,yhi=self.ax.get_ylim()
            clipped=sum(not (xlo <= float(p[xkey])*xs <= xhi and ylo <= float(p[ykey])*ys <= yhi)
                        for points in groups.values() for p in points)
            if clipped: self.progress_text.set('已收到 {} 点；{} 点在视图外，可点“全览测点”'.format(len(rows),clipped))
        device=self.last_result['state'].get('device',{}) if self.last_result else getattr(self,'active_device',{})
        title=' '.join(str(device.get(key,'')) for key in ('manufacturer','model')).strip()
        if title:self.ax.set_title(self.ax.get_title()+'\n'+title,fontsize=10)
        if name in ('output','beta'):
            cfg=self.last_result['state'].get('config',{}) if self.last_result else self.config_values[name]
            if cfg.get('scan_mode')=='脉冲':self.ax.set_title(self.ax.get_title()+' · 脉冲{:g} Hz / {:g}%'.format(cfg.get('pulse_frequency_hz',10),cfg.get('pulse_duty_percent',20)),fontsize=10)
        self.canvas.draw_idle()

    def available_measurement_columns(self, profile):
        common=('n','curve','condition','point','x','y')
        if self.measurement=='ac':return common+('rin','rx1_code','rx2_code','rx1_v','rx2_v','vin_peak','vb_peak','out_peak','predicted','tx1','tx2','extra')
        nodes=('vb','ve','vc') if self.measurement=='input' else ('vcc','ve','vc')
        return common+(('beta',) if self.measurement=='beta' else ())+('rx1_code','rx2_code','rx1_v','rx2_v')+nodes+('predicted','tx1','tx2')+(('sample_uce','adc_basis') if self.measurement=='beta' else ())+(('base_r',) if self.measurement in ('output','beta') else ())+('extra',)

    def measurement_table_columns(self, profile):
        available=self.available_measurement_columns(profile)
        columns=self.table_column_views.get(self.measurement,('n','curve','condition','point','x','y')+(('beta',) if self.measurement=='beta' else ()))
        return tuple(key for key in columns if key in available)

    def set_measurement_heading(self,key,title):
        self.table_column_titles[key]=title
        self.table.heading(key,text=('▶ ' if key==self.table_selected_column else '')+title)

    def select_measurement_column(self,event):
        if self.table.identify_region(event.x,event.y) not in ('heading','cell'):return
        column=self.table.identify_column(event.x)
        columns=tuple(self.table.cget('displaycolumns'))
        index=int(column[1:])-1 if column.startswith('#') else -1
        if 0<=index<len(columns):self.mark_measurement_column(columns[index])

    def mark_measurement_column(self,key):
        previous=self.table_selected_column;self.table_selected_column=key
        if previous:self.set_measurement_heading(previous,self.table_column_titles[previous])
        if key:
            self.set_measurement_heading(key,self.table_column_titles[key])
            self.column_selection_text.set('已选：'+self.table_column_titles[key])
        else:self.column_selection_text.set('点击列标题选择；＋添加列，−隐藏所选列')
        self.remove_column_button.config(state='normal' if key else 'disabled')

    def sync_measurement_columns(self):
        columns=self.measurement_table_columns(self.selected_profile())
        self.table.config(displaycolumns=columns)
        if self.table_selected_column not in columns:self.mark_measurement_column(None)
        profile=self.selected_profile()
        hx,hy={'input':(profile.input_axis+' / V','IB / μA'),'output':(profile.voltage_axis+' / V','IC / mA'),
               'beta':('IB 估算 / μA','IC / mA'),'ac':('频率 / kHz','|β| / A·A⁻¹')}[self.measurement]
        headings={'x':hx,'y':hy}
        for ch in (1,2):
            headings['rx{}_code'.format(ch)]='RX{} {} / 码'.format(ch,'AC RMS' if self.measurement=='ac' else '均值')
            headings['rx{}_v'.format(ch)]='ADC{} / RX{} {} / V'.format(3-ch,ch,'AC RMS' if self.measurement=='ac' else '接口实采')
        for key,title in headings.items():
            if self.table_column_titles[key]!=title:self.set_measurement_heading(key,title)
        if self.table_selected_column:self.column_selection_text.set('已选：'+self.table_column_titles[self.table_selected_column])

    def save_measurement_columns(self):
        try:
            path=self.base/'point_columns.json';temp=path.with_suffix('.tmp')
            temp.write_text(json.dumps(self.table_column_views,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
        except OSError as error:self.error('列显示设置保存失败：'+str(error))

    def hidden_measurement_columns(self):
        shown=self.measurement_table_columns(self.selected_profile())
        return tuple(key for key in self.available_measurement_columns(self.selected_profile()) if key not in shown)

    def show_add_column_menu(self):
        if getattr(self,'column_menu',None):self.column_menu.destroy()
        menu=tk.Menu(self.root,tearoff=False)
        hidden=self.hidden_measurement_columns()
        for key in hidden:menu.add_command(label=self.table_column_titles[key],command=lambda k=key:self.add_measurement_column(k))
        if not hidden:menu.add_command(label='本项目的列已全部显示',state='disabled')
        self.column_menu=menu
        try:menu.tk_popup(self.add_column_button.winfo_rootx(),self.add_column_button.winfo_rooty()+self.add_column_button.winfo_height())
        finally:menu.grab_release()

    def add_measurement_column(self,key):
        if key not in self.hidden_measurement_columns():return
        self.table_column_views[self.measurement]=list(self.measurement_table_columns(self.selected_profile()))+[key]
        self.sync_measurement_columns();self.mark_measurement_column(key);self.save_measurement_columns()

    def remove_measurement_column(self):
        key=self.table_selected_column
        if key is None:return
        self.table_column_views[self.measurement]=[c for c in self.measurement_table_columns(self.selected_profile()) if c!=key]
        self.mark_measurement_column(None);self.sync_measurement_columns();self.save_measurement_columns()

    def append_table_row(self, row, number):
        keys = {'input': ('ube_v', 'ib_estimated_a'), 'output': ('uce_v', 'ic_a'), 'beta': ('ib_estimated_a', 'ic_a'), 'ac': ('actual_freq_hz', 'gain')}[self.measurement]
        profile = Profile(self.last_result['state'].get('profile','npn_small')) if self.last_result else self.selected_profile()
        hx,hy,sx,sy = {'input':(profile.input_axis+' / V','IB / μA',1,1e6),'output':(profile.voltage_axis+' / V','IC / mA',1,1e3),
                      'beta':('IB 估算 / μA','IC / mA',1e6,1e3),'ac':('频率 / kHz','|β| / A·A⁻¹',.001,1)}[self.measurement]
        self.set_measurement_heading('x',hx); self.set_measurement_heading('y',hy)
        for ch in (1,2):
            self.set_measurement_heading('rx{}_code'.format(ch),'RX{} {} / 码'.format(ch,'AC RMS' if self.measurement=='ac' else '均值'))
            self.set_measurement_heading('rx{}_v'.format(ch),'ADC{} / RX{} {} / V'.format(3-ch,ch,'AC RMS' if self.measurement=='ac' else '接口实采'))
        self.sync_measurement_columns()
        basis='模拟' if str(row.get('simulated')).lower() in ('1','true') else '参考换算' if row.get('measurement_basis')=='reference_parameters_unverified' else '复核记录'
        beta='{:.6g}'.format(float(row['ic_a'])/float(row['ib_estimated_a'])) if self.measurement=='beta' and float(row.get('ib_estimated_a',0))>0 else '—'
        ve='{:.6g}'.format(float(row['ve_v'])) if row.get('ve_v') not in (None,'') else '—'
        values=point_details(row,self.measurement,profile)
        values.update(n=number,x='{:.6g}'.format(float(row[keys[0]])*sx),y='{:.6g}'.format(float(row[keys[1]])*sy),beta=beta,ve=ve,extra=basis)
        group=int(float(row.get('curve') or 0)) if self.measurement!='ac' else int(row.get('mode')=='refine')
        self.table.insert('', 'end', values=tuple(values.get(name,'—') for name,_,_ in TABLE_COLUMNS),tags=('curve_odd' if group%2 else 'curve_even',))

    def cache_measurement_view(self):
        key=(self._parameter_profile,self.measurement)
        if self.rows or self.last_result:
            self.measurement_views[key]=dict(rows=list(self.rows),result=self.last_result)

    def restore_measurement_view(self):
        self.sync_measurement_columns()
        key=(self._parameter_profile,self.measurement)
        view=self.measurement_views.get(key,{})
        self.last_result=view.get('result') or self.result_by_measurement.get(key)
        self.rows=list(view.get('rows',[]))
        self.table.delete(*self.table.get_children());self.reset_measurement_plot()
        if self.last_result:self.set_summary(self.last_result['state'])
        else:self.set_summary({'status':'尚无本项目数据'})
        if self.rows:
            self.plot_rows(self.rows)
            for i,row in enumerate(self.rows,1):self.append_table_row(row,i)
        elif self.last_result and self.last_result.get('local_directory'):
            self.read_result(Path(self.last_result['local_directory']))
        else:self.plot_rows([])

    def load_latest_result(self):
        if self.busy:
            self.notice.set('当前任务尚未结束，请结束后载入历史曲线。');return
        try:
            key=(self.selected_profile().key,self.measurement)
            from .result_paths import supports_pulse, run_method
            method=('pulse' if self.read_config().get('scan_mode')=='脉冲' else 'step') if supports_pulse(*key) else None
            result=latest_result(self.results,self.measurement,key[0],MEASUREMENTS,method=method)
            if result is None:
                view=self.measurement_views.get(key)
                if view and view.get('rows') and (method is None or run_method((view.get('result') or {}).get('state',{}))==method):
                    self.restore_measurement_view();self.notice.set('已恢复本次会话的曲线与测点。');return
                self.notice.set('当前器件档位、测量项目和扫描方式尚无已保存的测点。');return
            self.last_result=result;self.result_by_measurement[key]=result
            self.rows=[];self.table.delete(*self.table.get_children());self.reset_measurement_plot()
            self.set_summary(result['state']);self.read_result(Path(result['local_directory']))
            self.cache_measurement_view()
            self.notice.set('已载入 {} / {}：{}；使用记录内测量值，当前参数未覆盖。'.format(self.selected_profile().label,NAMES[self.measurement],result['run_id']))
        except Exception as error:self.error(error)

    def read_result(self, directory):
        csv_path = directory/MEASUREMENTS[self.measurement][2]
        if not csv_path.exists(): return
        with csv_path.open(encoding='utf-8-sig', newline='') as f: rows = list(csv.DictReader(f))
        for row in rows:
            row.setdefault('simulated', int(self.last_result['state']['simulated']))
        self.rows = rows; self.plot_rows(rows)
        self.table.delete(*self.table.get_children())
        for i,row in enumerate(rows):
            self.append_table_row(row, i+1)
        self.log('电脑数据：'+str(directory))
        try:
            from .curve_export import save_curves
            saved=save_curves(self,directory)
            if saved:self.log('曲线图片已自动保存：'+str(directory)+' / '+', '.join(saved))
        except Exception as error:self.log('曲线图片自动保存失败：'+str(error))
        try:
            from .measurement_views import export_derived
            derived=export_derived(directory,rows,self.last_result['state'])
            if derived:
                key='early_voltage' if self.measurement=='output' else 'input_resistance_analysis'
                self.last_result['state'][key]=derived['analysis'];self.set_summary(self.last_result['state'])
                self.derived_plots.save_rin(directory)
        except Exception as error:self.log('附加分析图未生成：'+str(error))
        if hasattr(self,'lcd'):self.lcd.bjt_current()

    def set_summary(self, state):
        labels={'complete':'完成','running':'采集中','cancelled':'已取消','failed':'运行异常','cleanup_failed':'清理未确认'}
        lines=['状态：'+labels.get(state.get('status'),state.get('status','—')),
               ('搜索采样点：' if state.get('measurement') == 'beta' else '测点：')+str(state.get('points',0)),
               '数据：'+('离线模拟' if state.get('simulated') else '真实 ADC / 参考参数换算' if state.get('measurement_basis')=='reference_parameters_unverified' else '按所加载复核记录')]
        if state.get('profile'):lines.append('器件：'+PROFILE_LABELS[state['profile']])
        if state.get('method')=='pulse':
            cfg=state.get('config',{});lines.append('集电极脉冲：{:g} Hz / {:g}%；高电平稳定帧换算'.format(cfg.get('pulse_frequency_hz',10),cfg.get('pulse_duty_percent',20)))
        if state.get('measurement')=='ac' and state.get('profile','').startswith('pnp'):
            lines+=['β≈(RB/RE)×VE/(Vin−VB)，按 IC≈IE。',
                    'Vin 为缓冲后 RB 前幅值；Vin/VB 同相近似。']
        if state.get('beta_selection'):
            sel=state['beta_selection']
            if 'planned_base_points' in sel:
                lines.append('计划基极档位 {}；未达到目标电压 {} 档'.format(sel['planned_base_points'],len(sel.get('skipped_points',[]))))
            lines.append('目标电压有效点 {}；剔除前档位后 {}；允许偏差 {:.3f} V'.format(
                sel['selected_points'],sel['fit_candidates'],sel['max_allowed_error_v']))
        if state.get('beta'):
            b=state['beta'];lines+=['','用于分析 {} 点；平滑后拟合 {} 点'.format(b['point_count'], b['fit_point_count']),'β 平均值：{:.3f}'.format(b['beta_mean']),
                'β 范围：{:.3f}～{:.3f}'.format(b['beta_min'],b['beta_max']),
                'IC–IB 线性拟合最大偏差 / IC 跨度：{:.3f}%'.format(b['linearity_error_pct']),
                'R²：{:.6f}；β 展宽：{:.3f}%'.format(b['r_squared'],b['beta_spread_pct']),
                'IB 由控制电压与档位系数推算；此指标不是仪器绝对测量精度。']
        if state.get('early_voltage'):
            v=state['early_voltage'].get('mean_va_v');lines+=['','Early 电压估计：'+('{:.3f} V'.format(v) if v is not None else '有效线性区数据不足')]
            e=state['early_voltage'];ro=e.get('ro_median_ohm')
            if ro is not None:lines.append('各曲线等效 ro 中位数：{:.3g} kΩ'.format(ro/1000))
            lines.append('ro = 1000/k（k 为 mA/V）；各档 IB 分别拟合，详见 Early / ro 图。')
        if state.get('ac_analysis'):
            a=state['ac_analysis'];lines+=['','低频电流增益：{:.3f}'.format(a['au']),
                'fβ 估计：{:.3f} kHz'.format(a['f_beta_hz']/1000),
                'fT 估计（β₀×fβ）：{:.3f} MHz'.format(a['ft_hz']/1e6),
                '模型拟合偏差：{:.3f}%'.format(a['rmse_percent']),
                '幅值按参考参数换算，电压差计算采用同相假设。']
        if state.get('input_resistance_analysis'):
            a=state['input_resistance_analysis'];rin=a.get('passband_median_ohm')
            lines+=['','本次输入电阻通带中位数：'+('{:.3g} Ω'.format(rin) if rin is not None else '有效数据不足'),
                    'Rin = Rtest×VB/(Vin−VB)，不含串联测试电阻；同相幅度近似。']
        if state.get('error'):lines+=['','原因：'+state['error']]
        if state.get('cleanup_errors'):lines+=['清理：'+str(state['cleanup_errors'])]
        if state.get('parameter_basis'):lines+=['','使用的替代参数随 run.json 保存；参数依据见“参数依据 / 设置”。']
        self.summary.config(state='normal'); self.summary.delete('1.0', 'end')
        self.summary.insert('end', '\n'.join(lines)); self.summary.config(state='disabled')

    def open_result(self):
        if self.last_result and self.last_result.get('local_directory'): os.startfile(self.last_result['local_directory'])
        else: self.error('本次尚无已取回的数据目录')

    def save_plot(self):
        directory=(self.last_result or {}).get('local_directory') or str(self.results)
        path = filedialog.asksaveasfilename(initialdir=directory, defaultextension='.png', filetypes=[('PNG', '*.png')])
        if path:
            selected=self.measure_tabs.select()
            derived=next((v[1] for v in self.derived_plots.tabs.values() if str(v[0])==selected),None)
            (derived or self.figure).savefig(path, dpi=180)
            self.log('曲线已保存：'+path)

    def retrieve(self):
        if not self.transport or self.busy: return
        transport = self.transport
        def work():
            runs = transport.call('runs')
            return [str(transport.fetch(run, self.results)) for run in runs]
        self.start_job('retrieve', work)

    def load_qualification(self):
        path = filedialog.askopenfilename(filetypes=[('JSON', '*.json')])
        if not path: return
        try:
            record = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if record.get('status') != 'validated': raise ValueError('记录未标记 validated；不能用于实板标定扫描')
            self.qualification = record
            self.qual_label.config(text='已加载：'+Path(path).name+'；开始时仍核对位流、系数及前端参数。')
        except Exception as error: self.error(error)

    def export_config(self):
        try: value = dict(measurement=self.measurement, config=self.read_config(),
                          frontend={k: float(v.get()) for k, v in self.front_vars.items()})
        except Exception as error: self.error(error); return
        path = filedialog.asksaveasfilename(initialdir=str(self.base), defaultextension='.json', filetypes=[('JSON', '*.json')])
        if path: Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    def import_config(self):
        if self.busy or self.queue_reserved():return
        path = filedialog.askopenfilename(filetypes=[('JSON', '*.json')])
        if not path: return
        try:
            value = json.loads(Path(path).read_text(encoding='utf-8-sig')); name = value['measurement']
            cls = MEASUREMENTS[name][0]; config = asdict(cls(**value['config']))
            profile=Profile(config['profile'])
            self.profile.set(profile.label);self.change_profile()
            self.show_page(name); self.config_values[name] = config; self.build_parameters()
            for key, val in value.get('frontend', {}).items():
                if key in self.front_vars: self.front_vars[key].set(str(float(val)))
        except Exception as error: self.error(error)

    def _load_settings(self):
        try:
            settings = json.loads((self.base/'settings.json').read_text(encoding='utf-8'))
            self.host.set(settings['host']); self.user.set(settings['user'])
        except (OSError, ValueError, KeyError): pass

    def _save_settings(self):
        (self.base/'settings.json').write_text(json.dumps({'host': self.host.get(), 'user': self.user.get()}, indent=2), encoding='utf-8')

    def log(self, text):
        line = time.strftime('%H:%M:%S')+'  '+str(text)
        self.logbox.config(state='normal'); self.logbox.insert('end', line+'\n'); self.logbox.see('end'); self.logbox.config(state='disabled')
        with (self.base/'desktop.log').open('a', encoding='utf-8') as f: f.write(line+'\n')

    def error(self, error):
        self.notice.set(str(error)); self.log('运行异常：'+str(error))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--scope-demo', action='store_true', help='Open and run the offline scope without hardware')
    parser.add_argument('--bitfile', help='Attach to this already-loaded board overlay; does not program FPGA')
    parser.add_argument('--verify', type=Path, help='Write packaged-runtime verification evidence and exit')
    parser.add_argument('--verify-host', help='Optional read-only board check using PYNQ_SSH_PASSWORD')
    parser.add_argument('--extract-datasheet',type=Path)
    parser.add_argument('--extract-output',type=Path)
    args = parser.parse_args()
    if args.extract_datasheet:
        if not args.extract_output:parser.error('--extract-output is required')
        from .datasheet_extract import cached_extract,export_csv
        result,target=cached_extract(args.extract_datasheet,args.extract_output)
        export_csv(result,target.with_suffix('.csv'))
        return
    if args.verify:
        from .desktop_verify import verify
        try:verify(assets(), args.verify, args.verify_host)
        except Exception:raise SystemExit(1)  # The detailed failure is in the requested report.
        return
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception: pass
    root = tk.Tk()
    app = App(root, workspace=args.workspace)
    app.board_bitfile=args.bitfile
    if args.bitfile:
        root.title('Zynq BJT · 指定候选位流')
        app.log('候选位流：'+args.bitfile+'；校准资格仍按实际位流核对')
    def report_error(kind, value, traceback): app.error('{}: {}'.format(kind.__name__, value))
    root.report_callback_exception = report_error
    if args.scope_demo:
        app.source.set('离线模拟'); app.show_page('scope'); app.connect()
        def demo_start():
            if app.busy:
                root.after(100, demo_start)
            elif app.transport and not app.last_status.get('initialized'):
                app.submit('initialize'); root.after(100, demo_start)
            elif app.transport:
                app.start_live()
        root.after(100, demo_start)
    root.mainloop()


if __name__ == '__main__': main()
