"""Desktop operations with independent GPIO and explicit ADC/DAC initialization."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import math
import platform
import threading
import time

from .frontend import Calibration, Frontend
from .scan import ScanConfig, run_scan, validate_measurement_board
from .characteristics import OutputScanConfig, BetaScanConfig, run_output_scan, run_beta_scan
from .ac import AcScanConfig, run_ac_scan
from .profiles import Profile, defaults_for, assumptions

MEASUREMENTS = {
    'input': (ScanConfig, run_scan, 'points.csv'),
    'output': (OutputScanConfig, run_output_scan, 'output_points.csv'),
    'beta': (BetaScanConfig, run_beta_scan, 'beta_points.csv'),
    'ac': (AcScanConfig, run_ac_scan, 'points.csv'),
}
DEFAULT_BIT = '/home/xilinx/jupyter_notebooks/zynq_bjt/overlay/bjt.bit'
EXPECTED_IDS = {0: 0x41444441, 0x20: 1024, 0x44: 0x54583101,
                0x48: 0x47504901, 0x80: 0x41574701}


def waveform(request, rate=50000000):
    """Validate the entire waveform before changing any output."""
    mode = request.get('mode', 'dc_code')
    offset = float(request.get('offset', 32768))
    peak = float(request.get('peak', 0))
    frequency = float(request.get('frequency_hz', 1000))
    phase = float(request.get('phase_degrees', 0))
    duty = float(request.get('duty_percent', 50))
    if not all(math.isfinite(v) for v in (offset, peak, frequency, phase, duty)):
        raise ValueError('参数必须是有限数值')
    if peak < 0 or not 0 <= frequency <= min(rate / 2, 10000000) or not 0 <= phase < 360:
        raise ValueError('幅度、频率或相位超出范围')
    if mode == 'dc_code':
        values = [offset] * 256
        frequency = 0
    elif mode == 'sine_code':
        values = [offset + peak * math.sin(2 * math.pi * i / 256) for i in range(256)]
    elif mode == 'square_code':
        if not 1 <= duty <= 99: raise ValueError('占空比范围为 1～99%')
        values = [offset + (peak if i < round(duty * 256 / 100) else -peak) for i in range(256)]
    elif mode == 'triangle_code':
        values = [offset + peak * (1 - 4 * abs(i / 256 - .5)) for i in range(256)]
    elif mode == 'custom_code':
        normalized = request.get('samples', [])
        if not 2 <= len(normalized) <= 65536 or any(
                not math.isfinite(float(v)) or not -1 <= float(v) <= 1 for v in normalized):
            raise ValueError('CSV 需要 2～65536 个 −1～1 的有限采样值')
        values = []
        for i in range(256):
            position = i * len(normalized) / 256
            index = int(position)
            f = position - index
            v = float(normalized[index]) * (1-f) + float(normalized[(index+1) % len(normalized)]) * f
            values.append(offset + peak * v)
    else:
        raise ValueError('未知波形类型')
    if min(values) < 0 or max(values) > 65535:
        raise ValueError('波形超出 16 位码值范围；请调整偏置或幅度')
    return [int(math.floor(v + .5)) for v in values], frequency, phase


class Session:
    def __init__(self, data, results, *, simulated=False, bitfile=DEFAULT_BIT):
        self.data, self.results = Path(data), Path(results)
        self.cal = Calibration(data)
        self.front = Frontend.load(self.data / 'frontend.json')
        self.simulated, self.bitfile = simulated, str(bitfile)
        self.board = None
        self.cancel = threading.Event()
        self.initial_gpio = None
        self.owned_lock = None
        self.last_result = None
        self.output_settings = {}
        self.standalone_gpio = 0
        self.gpio_active = False
        self.adc_divider = 20
        self.scan_display = None

    def _overlay_core(self):
        """Attach to GPIO registers without claiming MIO or initializing ADC/DAC."""
        from pynq import Overlay
        from .mmio import AddaCore
        overlay = Overlay(self.bitfile, download=False)
        info = overlay.ip_dict.get('adda_core_0', {})
        if info.get('phys_addr') != 0x43c00000 or info.get('addr_range') != 0x10000:
            raise ValueError('位流地址映射与桌面驱动不匹配')
        if not overlay.is_loaded():
            raise RuntimeError('所选位流尚未加载，请先完成板端 Overlay 启动')
        return AddaCore(overlay.adda_core_0.mmio)

    def _claim_lock(self):
        if self.simulated or self.owned_lock is not None: return
        import fcntl
        handle = open('/tmp/zynq_bjt_desktop.lock', 'a')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            handle.close()
            raise RuntimeError('另一桌面会话正在使用板卡')
        self.owned_lock = handle

    def status(self):
        result = dict(protocol=1, simulated=self.simulated, initialized=self.board is not None,
                      hostname=platform.node(), python=platform.python_version(),
                      analog_calibration_qualified=False, bitfile=self.bitfile,
                      gpio_active=self.gpio_active)
        if self.board is not None:
            result.update(identity=dict(self.board.identity), gpio=self.board.gpio(),
                          outputs=[asdict(self.board.output(c)) for c in range(3)],
                          sample_rates_hz=getattr(self.board, 'sample_rates_hz', None),
                          output_settings=dict(self.output_settings))
            core=None if self.simulated else self.board.core
            result['adc_max_rate_hz']=(125000000 if self.simulated else
                1000000000/int(core.io.read(0xd4)) if core.io.read(0xc)&0x10000000 else 50000000)
            if self.simulated:result['sample_rates_hz']=[1000000000/self.adc_divider]*2
        elif not self.simulated:
            # No GPIO export, PL programming, initialization or register write here.
            core = self._overlay_core()
            result['overlay_loaded'] = True
            io = core.io
            result['adc_max_rate_hz']=1000000000/int(io.read(0xd4)) if io.read(0xc)&0x10000000 else 50000000
            ids = {hex(a): int(io.read(a)) for a in EXPECTED_IDS}
            result['gpio'] = core.gpio()
            bit = Path(self.bitfile)
            result.update(registers=ids, dac_rate_hz=int(io.read(0x30)),
                          control=int(io.read(4)), dac_mode=int(io.read(0x10)),
                          identity={p.suffix[1:]+'_sha256': hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in (bit, bit.with_suffix('.hwh'))})
        else:
            result.update(identity={'kind': 'synthetic_bjt_model'}, dac_rate_hz=50000000,
                          gpio=dict(output=self.standalone_gpio, sense=self.standalone_gpio, sequence=0))
        result['lcd_native']=not self.simulated and bool(core.io.read(0x0c)&0x08000000)
        result['lcd_rgb565']=not self.simulated and bool(core.io.read(0x0c)&0x04000000)
        return result

    def initialize(self, request=None):
        if self.board is not None: raise RuntimeError('会话已初始化')
        divider=(request or {}).get('adc_divider',20)
        if type(divider) is not int or divider not in (8,10,12,16,20):raise ValueError('不支持的ADC时钟档位')
        if self.simulated:
            from .simulation import SimulatedBoard
            self.board = SimulatedBoard(self.cal, self.front)
            self.board.gpio(127, self.standalone_gpio)
        else:
            from .runtime import Board
            self._claim_lock()
            try:
                self.board = Board.from_pynq(self.bitfile, program=False)
                self.initial_gpio = self.board.gpio()['output']
                self.board.initialize(adc_divider=(request or {}).get('adc_divider',20), dac_divider=None)
            except BaseException as exc:
                try: self.close()
                except Exception as cleanup: raise RuntimeError('{}；退出清理未确认：{}'.format(exc, cleanup)) from exc
                raise
        self.initial_gpio = self.board.gpio()['output']
        self.adc_divider=divider
        self.cal.select_tx2_waveform_profile(None if self.simulated else self.board.identity)
        return self.status()

    def adc_clock(self,request):
        divider=request.get('adc_divider')
        if type(divider) is not int or divider not in (8,10,12,16,20):raise ValueError('不支持的ADC时钟档位')
        if self.board is not None:
            if any(self.board.output(c).enabled for c in range(3)):raise ValueError('切换ADC时钟前请停止TX输出')
            if 1e9/divider>self.status()['adc_max_rate_hz']+1:raise ValueError('此时钟高于当前位流通过的时序上限')
            self.initial_gpio=self.board.gpio()['output']
            self.close();self.cancel.clear();self.output_settings.clear()
        return self.initialize(request)

    def require_board(self):
        if self.board is None: raise RuntimeError('请先点击“初始化”')
        return self.board

    def stop(self):
        # Stop is explicit: mute owned DACs and reset all seven user GPIOs.
        # GPIO-only use must not initialize analog hardware to perform it.
        errors = []
        if self.board is not None:
            for c in range(3):
                try: self.board.enable(c, False)
                except Exception as error: errors.append('TX{}: {}'.format(c+1, error))
        try:
            self._write_gpio(127, 0)
            # A later disconnect must not restore pre-initialization HIGHs.
            self.initial_gpio = 0
        except Exception as error: errors.append('GPIO: {}'.format(error))
        if errors: raise RuntimeError('停止未确认：' + '; '.join(errors))
        return self.status()

    def output(self, request):
        board = self.require_board()
        channel = request['channel']
        if type(channel) is not int or channel not in (0, 1, 2): raise ValueError('无效 TX 通道')
        action = request.get('action', 'apply')
        if action == 'stop':
            board.enable(channel, False)
            return self.status()
        if action not in ('apply', 'start'): raise ValueError('未知输出操作')
        if request.get('wiring_confirmed') is not True:
            raise ValueError('请核对当前输出的接线和负载')
        if request.get('tx2_waveform_calibration_id'):
            profile=self.cal.tx2_waveforms
            if channel!=1 or not profile or request['tx2_waveform_calibration_id']!=profile['calibration_id']:
                raise ValueError('TX2 waveform calibration does not match the board agent')
            shape=request['display_waveform']
            if shape=='square' and float(request.get('duty_percent',50))!=50:
                raise ValueError('TX2 calibrated square requires 50% duty')
            plan=self.cal.tx2_waveform_parameters(shape,float(request['frequency_hz']),
                 2*float(request['display_peak']),float(request['display_offset']))
            if plan is None:
                raise ValueError('TX2 setting is outside its measured AC reference region')
            phase=float(request['display_phase_degrees'])
            if not math.isfinite(phase) or not 0<=phase<360:
                raise ValueError('TX2 phase is outside 0..360 degrees')
            if not self.simulated:
                self.cal.validate_tx2_waveform_identity(board.identity)
                if board.core.io.read(0x30)!=plan['dac_sample_rate_hz']:
                    raise ValueError('TX2 waveform reference targets a different DAC sample rate')
            request=dict(request,mode=shape+'_code',offset=plan['zero_code'],peak=plan['peak_codes'],
                         phase_degrees=(phase+180)%360,sine_amplitude_basis=plan['amplitude_basis'])
        if request.get('waveform_calibration_id'):
            if channel!=2 or not self.cal.tx3_waveforms or request['waveform_calibration_id']!=self.cal.tx3_waveforms['calibration_id']:
                raise ValueError('TX3 waveform calibration does not match the board agent')
            shape=request['display_waveform']
            if float(request['display_offset'])!=0 or (shape=='square' and float(request.get('duty_percent',50))!=50):
                raise ValueError('TX3 calibrated waveform requires zero offset and 50% square duty')
            plan=self.cal.waveform_parameters(shape,float(request['frequency_hz']),2*float(request['display_peak']))
            if not self.simulated:plan=self.cal.bind_waveform_plan(plan,board.identity)
            if not self.simulated and board.core.io.read(0x30)!=plan['dac_sample_rate_hz']:
                raise ValueError('TX3 waveform reference targets a different DAC sample rate')
            request=dict(request,mode=shape+'_code',offset=plan['zero_code'],peak=plan['peak_codes'],
                         sine_amplitude_basis=plan['amplitude_basis'],
                         tx3_bitstream_reference=plan.get('bitstream_reference'),
                         tx3_reference_amplitude_basis=plan.get('reference_amplitude_basis',plan['amplitude_basis']))
        mode = request.get('mode', 'dc_code')
        # A failure during a table write/start can leave a partially changed
        # output. Do not keep describing the previous setting as current.
        self.output_settings.pop(str(channel), None)
        if channel == 0:
            if mode not in ('dc_code', 'dc_voltage'): raise ValueError('当前 PYNQ TX1 支持直流输出，请选择直流模式')
            if mode == 'dc_voltage': code = self.cal.dac_code(0, float(request['offset']))[0]
            else:
                value = float(request['offset'])
                if not math.isfinite(value) or not value.is_integer() or not 0 <= value <= 4095:
                    raise ValueError('TX1 码值须为 0～4095 的整数')
                code = int(value)
            board.set_code(channel, code)
        elif mode == 'dc_voltage':
            code = self.cal.dac_code(channel, float(request['offset']))[0]
            board.set_code(channel, code)
        elif mode == 'sine_voltage':
            if float(request.get('offset', 0)) != 0: raise ValueError('TX3 频率补偿表仅支持零偏置')
            plan = self.cal.sine_parameters(float(request['frequency_hz']), float(request['vpp']))
            if not self.simulated:plan=self.cal.bind_waveform_plan(plan,board.identity)
            request = dict(request, sine_amplitude_basis=plan['amplitude_basis'],
                           tx3_bitstream_reference=plan.get('bitstream_reference'),
                           tx3_reference_amplitude_basis=plan.get('reference_amplitude_basis',plan['amplitude_basis']))
            board.set_sine(channel, self.cal, float(request['frequency_hz']), float(request['vpp']))
        else:
            samples, frequency, phase = waveform(request)
            if self.simulated:
                board.codes[channel] = samples[0]
            else:
                board.core.awg(channel-1, samples, frequency_hz=frequency, phase_degrees=phase)
                board.codes[channel] = samples[0]
        if action == 'start': board.enable(channel, True)
        self.output_settings[str(channel)] = {k: v for k, v in request.items() if k != 'samples'}
        return self.status()

    def gpio(self, request):
        mask, value = request.get('mask'), request.get('value')
        if type(mask) is not int or type(value) is not int or not 0 <= mask <= 127 or not 0 <= value <= 127:
            raise ValueError('GPIO 掩码与数据须为 7 位整数')
        self._write_gpio(mask, value)
        return self.status()

    def _write_gpio(self, mask, value):
        if self.board is not None:
            self.board.gpio(mask, value)
        elif self.simulated:
            self.standalone_gpio = (self.standalone_gpio & ~mask) | (value & mask)
        else:
            self._claim_lock()
            self._overlay_core().gpio(mask, value)
        self.gpio_active = True

    def meter(self, request=None):
        from .meter import readings
        board = self.require_board()
        count = 50000
        if self.simulated:
            # Explicit synthetic 1 kHz signal: DC=0.3 V and peak=0.1 V.
            stats = dict(sample_count=count, completed_at=time.time(), simulated=True,
                channels=[dict(mean_code=p['zero_code_q16']/65536+.3/(p['slope_nv_per_code']/1e9),
                               rms_code=.1/math.sqrt(2)/abs(p['slope_nv_per_code']/1e9), fault_count=0)
                          for p in (self.cal.rx1,self.cal.rx2)])
            rates = (50000000,)*2
        else:
            stats = board.capture_statistics(count)
            rates = board.sample_rates_hz
        return readings(stats, self.cal, rates)

    def capture(self, request=None):
        board = self.require_board()
        request = request or {}
        count = request.get('sample_count',1024)
        if type(count) is not int or not 8<=count<=4096: raise ValueError('采集点数须为8..4096整数')
        window_us = float(request.get('window_us', 0))
        if not math.isfinite(window_us) or not 0 <= window_us <= 20000:
            raise ValueError('实采窗口须为 0..20000 µs')
        adc_rates = (1000000000/self.adc_divider,)*2 if self.simulated else board.sample_rates_hz
        stride = request.get('sample_stride')
        if stride is None:
            stride = max(1,math.ceil(window_us*1e-6*max(adc_rates)/(count-1)))
            if stride>256: raise ValueError('此窗口超出当前点数范围，请增加点数或缩短窗口')
        if type(stride) is not int or not 1<=stride<=256: raise ValueError('抽取倍率须为1..256整数')
        if self.simulated:
            from .mmio import Frame
            board.sequence += 1
            # Moving phase exercises software trigger stability in the offline UI.
            words = tuple(tuple(round(32768+8000*math.sin(2*math.pi*10000*i*stride/adc_rates[c]+board.sequence*.17+c))
                                for i in range(count)) for c in range(2))
            frame = Frame(board.sequence, words, tuple(r/stride for r in adc_rates), time.time(), simulated=True,
                          adc_sample_rates_hz=adc_rates, sample_stride=stride)
        else:
            frame = board.capture(sample_stride=stride, sample_count=count)
        return frame.as_record()

    def scan(self, request, emit=lambda kind, value: None):
        if not self.simulated and self.board is not None and self.adc_divider!=20:
            raise ValueError('高速档用于示波器原始采样；BJT测量请切回50 MHz校准档')
        prepare_outputs = request.get('prepare_outputs') is True
        if not prepare_outputs:
            self.require_board()
        name = request['measurement']
        if name not in MEASUREMENTS: raise ValueError('未迁移此测量项目')
        profile_key = request.get('profile', request.get('config', {}).get('profile','npn_small'))
        Profile(profile_key)
        method = request.get('method', 'step')
        from .result_paths import supports_pulse
        if method not in ('step','pulse') or (method=='pulse' and not supports_pulse(profile_key,name)):
            raise ValueError('脉冲仅支持NPN/PNP大功率输出与β线性精度')
        if not self.simulated and request.get('fixture_confirmed') is not True:
            raise ValueError('实板扫描需要确认 BJT 测试板、接线与负载')
        front = Frontend(**request.get('frontend', asdict(self.front)))
        cls, runner, _ = MEASUREMENTS[name]
        values = defaults_for(name, cls, profile_key)
        supplied = request.get('config', {})
        if supplied.get('profile', profile_key) != profile_key:
            raise ValueError('器件档位与参数中的档位不一致')
        values.update(supplied)
        if name in ('output','beta'):
            mode = '脉冲' if method=='pulse' else '步进'
            if 'scan_mode' in supplied and supplied['scan_mode'] != mode:
                raise ValueError('扫描方式与配置不一致')
            values['scan_mode'] = mode
        config = cls(**values)
        config.validate(self.cal, front)
        # Qualification is checked by the engine BEFORE any output/GPIO change.
        qualification = request.get('qualification')
        if request.get('allow_reference') is True:
            qualification = dict(status='reference_only', explicit_reference_mode=True,
                sample_rate_hz=50000000, parameter_basis=assumptions(profile_key,name),
                calibration_sha256={k:v['sha256'] for k,v in self.cal.manifest().items()},
                statement='Reference conversion with provisional constants; not a qualified accuracy result')

        def report_status():
            try: status = self.status()
            except Exception as error:
                emit('instrument_status_unknown', str(error))
            else: emit('instrument_status', status)

        if prepare_outputs:
            if self.cancel.is_set(): raise InterruptedError('Scan cancelled before preparation')
            if self.board is None:
                if not self.simulated and not (qualification and qualification.get('status') in ('validated', 'reference_only')):
                    raise ValueError('Real measurements require qualified calibration or explicit reference mode')
                emit('log', '测量准备：自动初始化 ADC 与三路 TX，保持输出关闭。')
                self.initialize()
            board = self.require_board()
            validate_measurement_board(board, self.cal, front, qualification)
            emit('log', '测量准备：统一关闭 TX1 / TX2 / TX3，并检查关闭状态。')
            errors = []
            # Always attempt every channel, including when one mute fails.
            for channel in range(3):
                try: board.enable(channel, False)
                except Exception as error: errors.append('TX{}: {}'.format(channel+1, error))
            for channel in range(3):
                try:
                    if board.output(channel).enabled:
                        raise RuntimeError('输出仍启用')
                except Exception as error: errors.append('TX{}: {}'.format(channel+1, error))
            report_status()
            if errors:
                raise RuntimeError('测量准备检查：'+'; '.join(errors))
            if self.cancel.is_set(): raise InterruptedError('Scan cancelled during preparation')
        board = self.require_board()
        if self.simulated: board.front = front
        # Measurement engines set outputs directly, replacing manual settings.
        self.output_settings.clear()
        display = None
        scan_cancel = self.cancel
        scan_emit = emit
        stream = request.get('lcd_stream')
        if stream and not self.simulated:
            from .lcd_stream import ScanDisplay, DisplayCancel
            if (not isinstance(stream, dict) or not isinstance(stream.get('id'), str)
                    or not 1 <= len(stream['id']) <= 100
                    or (stream.get('native') is not None and type(stream['native']) is not bool)):
                raise ValueError('Invalid scan LCD stream')
            native=bool(board.core.io.read(0x0c)&0x08000000) if stream.get('native') is None else stream['native']
            display = ScanDisplay(board.core, stream['id'], native, emit)
            self.scan_display = display
            board.scan_lcd_managed = True
            scan_cancel = DisplayCancel(self.cancel, display)
            def scan_emit(kind, value):
                emit(kind, value)
                if not self.cancel.is_set():
                    display.pump()
        try:
            directory, state = runner(board, self.cal, front, config, self.results,
                                      cancel=scan_cancel, qualification=qualification, emit=scan_emit,
                                      **({'defer_analysis':bool(request.get('analysis_on_host'))} if name=='ac' else {}))
        finally:
            if display is not None:
                display.close()
                self.scan_display = None
                board.scan_lcd_managed = False
            report_status()
        self.last_result = directory
        state['device'] = {k: str(request.get('device', {}).get(k, ''))[:200] for k in ('manufacturer', 'model')}
        if name=='ac' and profile_key.startswith('pnp') and request.get('display_reference'):
            state['display_reference'] = {k:str(v)[:1000] for k,v in request['display_reference'].items()
                if k in ('id','profile','manufacturer','model','source_archive','source_member','source_sha256','source_kind')}
        (directory/'run.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        return dict(directory=str(directory), relative_directory=directory.relative_to(self.results).as_posix(), run_id=directory.name, state=state,
                    files=[p.name for p in directory.iterdir() if p.is_file()])

    def detect(self, request, emit=lambda kind, value: None):
        if not self.simulated and self.board is not None and self.adc_divider!=20:
            raise ValueError('器件识别请先切回50 MHz校准档')
        from .polarity import ProbeConfig, run_probe, PROBE_RC_OHM
        front = Frontend(**request.get('frontend', asdict(self.front)))
        config = ProbeConfig(**dict(request.get('config', {}), collector_resistor_ohm=PROBE_RC_OHM)).validate(self.cal, front)
        if not self.simulated and request.get('fixture_confirmed') is not True:
            raise ValueError('请先确认 BJT 接线、功率档位与负载')
        qualification = request.get('qualification')
        if request.get('allow_reference') is True:
            qualification = dict(status='reference_only', sample_rate_hz=50000000,
                                 explicit_reference_mode=True)
        if not self.simulated and not (qualification and qualification.get('status') in ('validated','reference_only')):
            raise ValueError('识别需要标定复核记录或明确选择参考换算')
        if self.cancel.is_set(): raise InterruptedError('识别已取消')
        if self.board is None: self.initialize()
        board = self.require_board()
        validate_measurement_board(board, self.cal, front, qualification)
        if self.simulated:
            board.front = front
            device = request.get('simulated_device', 'npn')
            if device not in ('npn','pnp','open','ambiguous'): raise ValueError('未知模拟器件')
            board.probe_device_polarity = device
        self.output_settings.clear()
        result = run_probe(board, self.cal, front, config, self.results, self.cancel, emit)
        self.initial_gpio = 0
        self.last_result = Path(result['directory'])
        emit('instrument_status', self.status())
        return result

    def runs(self):
        if not self.results.exists(): return []
        paths = sorted((p.parent for p in self.results.rglob('run.json')), key=lambda p:p.name, reverse=True)[:50]
        return [{'run_id': p.name, 'directory': str(p), 'relative_directory':p.relative_to(self.results).as_posix(),
                 'files': [f.name for f in p.iterdir() if f.is_file()]}
                for p in paths]

    def queue_scan_lcd(self, request):
        display = self.scan_display
        return display.offer(request) if display is not None else dict(stream=True, accepted=False)

    def lcd(self, request):
        from .lcd_stream import decode_pixels
        if self.simulated:raise ValueError('LCD hardware endpoint requires a real board')
        core=self.require_board().core
        pixels,native=decode_pixels(request)
        if pixels is not None and not request.get('incremental'):core.display_pixels(pixels)
        update=core.display_update(pixels,request.get('max_writes',8192),native=native) if request.get('incremental') else {}
        return dict(touch=core.display_touch(),**update)

    def close(self):
        self.cancel.set()
        board, self.board = self.board, None
        errors = []
        if board is not None:
            for c in range(3):
                try:
                    if self.simulated or getattr(board, 'initialized', False): board.enable(c, False)
                except Exception as exc: errors.append('TX{} stop: {}'.format(c+1, exc))
            if self.initial_gpio is not None:
                try: board.gpio(127, self.initial_gpio)
                except Exception as exc: errors.append('GPIO restore: '+str(exc))
            if self.simulated: self.standalone_gpio = board.gpio()['output']
            if not self.simulated:
                try: board.close()
                except Exception as exc: errors.append(str(exc))
        if self.owned_lock is not None:
            self.owned_lock.close()
            self.owned_lock = None
        if errors: raise RuntimeError('清理未确认：' + '; '.join(errors))
        return {'closed': True, 'cleanup_confirmed': True}

    def dispatch(self, operation, request=None, emit=lambda kind, value: None):
        request = request or {}
        if operation=='initialize':return self.initialize(request)
        if operation=='adc_clock':return self.adc_clock(request)
        if operation in ('capture', 'meter'): return getattr(self, operation)(request)
        if operation in ('status', 'initialize', 'stop', 'runs', 'close'):
            return getattr(self, operation)()
        if operation in ('output', 'gpio', 'lcd'): return getattr(self, operation)(request)
        if operation == 'scan': return self.scan(request, emit)
        if operation == 'detect': return self.detect(request, emit)
        raise ValueError('不支持的桌面命令')
