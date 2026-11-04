"""Jupyter workbench for the shared input, output, beta and AC scan engines."""
from dataclasses import asdict
from pathlib import Path
import csv
import json
import os
import threading

from .ac import AcScanConfig, run_ac_scan
from .characteristics import BetaScanConfig, OutputScanConfig, run_beta_scan, run_output_scan
from .frontend import Frontend
from .scan import ScanConfig, run_scan
from .simulation import SimulatedBoard


class NpnNotebook:
    def __init__(self, calibration, frontend, *, output_root='results', board=None, qualification=None):
        import ipywidgets as w
        self.w = w
        self.calibration, self.frontend = calibration, frontend
        self.board, self.qualification = board, qualification
        self.output_root = Path(output_root)
        self.cancel_event = threading.Event()
        self.worker = None
        self.last_result = None
        self.last_error = None

        board_label = '裸机串口实板' if getattr(board, 'identity', {}).get('transport') == 'baremetal_uart' else 'PYNQ 实板'
        self.source = w.ToggleButtons(options=['离线模拟'] + ([board_label] if board is not None else []),
                                      description='数据源')
        self.fixture_attached = w.Checkbox(value=False, description='已连接 BJT 测试板与安全负载')
        self.tabs = w.Tab()
        self.progress = w.IntProgress(value=0, min=0, max=1, description='进度')
        self.run_button = w.Button(description='开始测量', button_style='primary', icon='play')
        self.stop_button = w.Button(description='停止', button_style='warning', icon='stop', disabled=True)
        self.question_button = w.Button(description='待确认问题', icon='question-circle')
        self.output = w.Output()

        self.input_start = w.FloatText(value=.02, description='TX1 起点/V')
        self.input_stop = w.FloatText(value=2.0, description='TX1 终点/V')
        self.input_step = w.FloatText(value=.04, description='步长/V')
        self.input_biases = w.Text(value='0,1,3', description='UCE 列表/V')
        self.input_attenuation = w.FloatText(value=frontend.rx1_per_vc, description='集电极/VC')
        self.input_gain = w.FloatText(value=frontend.collector_amplifier_gain, description='功放增益')
        self.input_resistance = w.FloatText(value=frontend.base_equivalent_resistance_ohm,
                                            description='恒流等效电阻/Ω')
        self.input_settle = w.FloatText(value=.05, description='稳定等待/s')
        self.input_frames = w.BoundedIntText(value=3, min=2, max=20, description='独立帧数')
        input_panel = w.VBox([
            w.HBox([self.input_start, self.input_stop, self.input_step]),
            self.input_biases,
            w.HBox([self.input_attenuation, self.input_gain, self.input_resistance]),
            w.HBox([self.input_settle, self.input_frames]),
        ])

        self.output_bases = w.Text(value='0.05,0.15,0.25', description='TX1 曲线/V')
        self.output_tx2_start = w.FloatText(value=0.0, description='TX2 起点/V')
        self.output_tx2_stop = w.FloatText(value=1.8, description='TX2 终点/V')
        self.output_tx2_step = w.FloatText(value=.05, description='TX2 步长/V')
        self.output_channels = w.Dropdown(options=[
            ('RX1 集电极，RX2 VCC', 0),
            ('RX2 集电极，RX1 VCC', 1)], value=1, description='ADC 接线')
        self.output_collector_scale = w.FloatText(value=.206, description='集电极比例')
        self.output_source_scale = w.FloatText(value=.206, description='VCC反馈/VCC')
        self.output_settle = w.FloatText(value=.1, description='稳定等待/s')
        self.output_frames = w.BoundedIntText(value=3, min=2, max=20, description='独立帧数')
        output_panel = w.VBox([
            self.output_bases,
            w.HBox([self.output_tx2_start, self.output_tx2_stop, self.output_tx2_step]),
            self.output_channels,
            w.HBox([self.output_collector_scale, self.output_source_scale]),
            w.HBox([self.output_settle, self.output_frames]),
        ])

        self.beta_tx1_start = w.FloatText(value=.02, description='TX1 起点/V')
        self.beta_tx1_stop = w.FloatText(value=1.0, description='TX1 终点/V')
        self.beta_tx1_step = w.FloatText(value=.04, description='TX1 步长/V')
        self.beta_target = w.FloatText(value=5.0, description='目标 UCE/V')
        self.beta_tx2_start = w.FloatText(value=.95, description='TX2 搜索起点/V')
        self.beta_tx2_stop = w.FloatText(value=1.25, description='TX2 搜索上限/V')
        self.beta_channels = w.Dropdown(options=[
            ('RX1 集电极，RX2 VCC', 0),
            ('RX2 集电极，RX1 VCC', 1)], value=1, description='ADC 接线')
        self.beta_collector_scale = w.FloatText(value=.206, description='集电极比例')
        self.beta_source_scale = w.FloatText(value=.206, description='VCC反馈/VCC')
        self.beta_settle = w.FloatText(value=.05, description='稳定等待/s')
        beta_panel = w.VBox([
            w.HBox([self.beta_tx1_start, self.beta_tx1_stop, self.beta_tx1_step]),
            w.HBox([self.beta_target, self.beta_tx2_start, self.beta_tx2_stop]),
            self.beta_channels,
            w.HBox([self.beta_collector_scale, self.beta_source_scale, self.beta_settle]),
            w.HTML('输出 β 线性精度：固定 UCE≈5 V，扫描 TX1 并以 TX1/2 kΩ 估算 IB；仅用 UCE>1 V 且 IC>0 的放大区点，以双 ADC 与 100 Ω 采样电阻计算 IC；舍弃前 2 组后做相邻两点平均并拟合 IC-IB。'),
        ])

        self.ac_tx1 = w.FloatText(value=.2, description='TX1 偏置/V')
        self.ac_tx2 = w.FloatText(value=1.5, description='TX2 VCC 控制/V')
        self.ac_amplitude = w.FloatText(value=.05, description='TX3 正弦/Vpp')
        self.ac_buffer_gain = w.FloatText(value=.84, description='缓冲幅度比')
        self.ac_adc_multiplier = w.FloatText(value=1.0, description='交流幅度系数')
        self.ac_input_channel = w.Dropdown(options=[('RX1/测试板ADC2 输入', 0), ('RX2/测试板ADC1 输入', 1)],
                                           value=0, description='输入通道')
        self.ac_output_channel = w.Dropdown(options=[('RX2/测试板ADC1 输出', 1), ('RX1/测试板ADC2 输出', 0)],
                                            value=1, description='输出通道')
        self.ac_input_scale = w.FloatText(value=9.78, description='采集/VB比例')
        self.ac_output_scale = w.FloatText(value=.206, description='输出比例')
        self.ac_settle = w.FloatText(value=.1, description='稳定等待/s')
        ac_panel = w.VBox([
            w.HBox([self.ac_tx1, self.ac_tx2, self.ac_amplitude, self.ac_buffer_gain]),
            w.HBox([self.ac_input_channel, self.ac_output_channel, self.ac_adc_multiplier]),
            w.HBox([self.ac_input_scale, self.ac_output_scale, self.ac_settle]),
            w.HTML('默认扫频 10–150 kHz/10 kHz 步进、200 kHz–2 MHz/100 kHz 步进；50,000 点统计窗。'),
        ])

        self.tabs.children = (input_panel, output_panel, beta_panel, ac_panel)
        for index, title in enumerate(('输入特性', '输出 / Early', '输出 β线性精度', '交流 fβ / fT')):
            self.tabs.set_title(index, title)
        self.controls = [self.source, self.tabs, self.input_start, self.input_stop,
                         self.fixture_attached,
                         self.input_step, self.input_biases, self.input_attenuation,
                         self.input_gain, self.input_resistance, self.input_settle,
                         self.input_frames, self.output_bases, self.output_tx2_start,
                         self.output_tx2_stop, self.output_tx2_step, self.output_channels,
                         self.output_collector_scale, self.output_source_scale,
                         self.output_settle, self.output_frames, self.beta_tx1_start,
                         self.beta_tx1_stop, self.beta_tx1_step, self.beta_target,
                         self.beta_tx2_start, self.beta_tx2_stop, self.beta_channels,
                         self.beta_collector_scale, self.beta_source_scale, self.beta_settle,
                         self.ac_tx1, self.ac_tx2, self.ac_amplitude, self.ac_buffer_gain, self.ac_adc_multiplier, self.ac_input_channel,
                         self.ac_output_channel, self.ac_input_scale, self.ac_output_scale,
                         self.ac_settle]
        self.run_button.on_click(lambda _: self.start_scan())
        self.stop_button.on_click(lambda _: self.cancel_event.set())
        self.question_button.on_click(self._show_pending_questions)
        note = w.HTML(
            '<span>输出和 β 扫描的 VCC 反馈比例默认 0.206（用户确认），VCC=RX1接口电压/0.206。实板扫描需要本版校准资格和已连接测试板/安全负载。</span>')
        self.view = w.VBox([
            w.HTML('<h3>Zynq-7020 · NPN BJT 测试</h3>'),
            w.HBox([self.source, self.question_button]),
            self.fixture_attached, self.tabs, note,
            w.HBox([self.run_button, self.stop_button]),
            self.progress, self.output,
        ])

    def _show_pending_questions(self, _button):
        message = (
            '待填写参数：\n'
            '1. 输出特性和 β 线性页默认 VCC 反馈比例为 0.206（RX1端电压/VCC，用户确认）。\n'
            '2. BJT测试板与安全负载未接入；实板扫描会保持锁止，直到完成接线和本板模拟校准。\n'
            '交流测量已按确认值设置为 RX1 集电极、RX2 基极，83=0、85=1；TX2=1.5 V 为六倍功放的控制输入。'
        )
        try:
            from IPython.display import Javascript, display
            display(Javascript('window.alert(' + json.dumps(message, ensure_ascii=True) + ')'))
        except Exception:
            self.output.append_stdout(message + '\n')

    def start_scan(self):
        if self.worker is not None and self.worker.is_alive():
            return
        self.output.clear_output()
        self.last_result = self.last_error = None
        measurement = self.tabs.selected_index
        simulated = self.source.value == '离线模拟'
        try:
            if not simulated and not self.fixture_attached.value:
                raise ValueError('实板扫描已锁止：请先连接 BJT 测试板与安全负载并确认。')
            frontend = Frontend(**{**asdict(self.frontend),
                'rx1_per_vc': self.input_attenuation.value,
                'collector_amplifier_gain': self.input_gain.value,
                'base_equivalent_resistance_ohm': self.input_resistance.value})
            board = SimulatedBoard(self.calibration, frontend) if simulated else self.board
            if measurement == 0:
                config = ScanConfig(
                    tx1_start_v=self.input_start.value, tx1_stop_v=self.input_stop.value,
                    tx1_step_v=self.input_step.value,
                    uce_values_v=tuple(float(value.strip()) for value in self.input_biases.value.split(',')),
                    settle_s=0 if simulated else self.input_settle.value,
                    curve_settle_s=0 if simulated else .5,
                    frame_gap_s=0 if simulated else .05, frames_per_point=self.input_frames.value,
                    relay_active_level=1)
                points = len(config.validate(self.calibration, frontend)) * len(config.uce_values_v)
                runner = run_scan
                args = (board, self.calibration, frontend, config, self.output_root)
            elif measurement == 1:
                config = OutputScanConfig(
                    base_control_v=tuple(float(value.strip()) for value in self.output_bases.value.split(',')),
                    tx2_control_start_v=self.output_tx2_start.value,
                    tx2_control_stop_v=self.output_tx2_stop.value,
                    tx2_control_step_v=self.output_tx2_step.value,
                    collector_channel=self.output_channels.value,
                    source_channel=1-self.output_channels.value,
                    collector_adc_per_v=self.output_collector_scale.value,
                    source_adc_per_v=self.output_source_scale.value,
                    settle_s=0 if simulated else self.output_settle.value,
                    frames_per_point=self.output_frames.value)
                tx2_values = config.validate(self.calibration, frontend)
                points = len(config.base_control_v) * len(tx2_values)
                runner = run_output_scan
                args = (board, self.calibration, frontend, config, self.output_root)
            elif measurement == 2:
                config = BetaScanConfig(
                    tx1_start_v=self.beta_tx1_start.value, tx1_stop_v=self.beta_tx1_stop.value,
                    tx1_step_v=self.beta_tx1_step.value, target_uce_v=self.beta_target.value,
                    tx2_first_start_v=self.beta_tx2_start.value, tx2_stop_v=self.beta_tx2_stop.value,
                    collector_channel=self.beta_channels.value,
                    source_channel=1-self.beta_channels.value,
                    collector_adc_per_v=self.beta_collector_scale.value,
                    source_adc_per_v=self.beta_source_scale.value,
                    settle_s=0 if simulated else self.beta_settle.value,
                    frames_per_point=self.output_frames.value)
                points = len(config.validate(self.calibration, frontend))
                runner = run_beta_scan
                args = (board, self.calibration, frontend, config, self.output_root)
            else:
                config = AcScanConfig(
                    tx1_bias_v=self.ac_tx1.value, tx2_vcc_control_v=self.ac_tx2.value,
                    tx3_input_vpp=self.ac_amplitude.value,
                    source_buffer_gain=self.ac_buffer_gain.value,
                    adc_amplitude_multiplier=self.ac_adc_multiplier.value,
                    input_channel=self.ac_input_channel.value,
                    output_channel=self.ac_output_channel.value,
                    input_adc_per_v=self.ac_input_scale.value,
                    output_adc_per_v=self.ac_output_scale.value,
                    settle_s=0 if simulated else self.ac_settle.value)
                points = len(config.validate(self.calibration, frontend)) + config.max_bisection_iterations
                runner = run_ac_scan
                args = (board, self.calibration, frontend, config, self.output_root)
        except Exception as error:
            self.last_error = str(error)
            self.output.append_stdout('未开始：{}\n'.format(error))
            return

        self.progress.max = max(1, points)
        self.progress.value = 0
        self.cancel_event.clear()
        for control in self.controls:
            control.disabled = True
        self.run_button.disabled = True
        self.stop_button.disabled = False
        self.output.append_stdout(('离线模拟' if simulated else self.source.value) + ' / ' +
                                  self.tabs.get_title(measurement) + '\n')

        def emit(kind, value):
            if kind in ('point', 'curve'):
                self.progress.value = min(self.progress.value + 1, self.progress.max)

        def work():
            try:
                directory, state = runner(*args, cancel=self.cancel_event,
                    qualification=self.qualification, emit=emit)
                self.last_result = (directory, state)
                self.output.append_stdout('状态：{}；测点：{}\n目录：{}\n'.format(
                    state['status'], state['points'], directory))
                if state.get('error'):
                    self.output.append_stdout(state['error'] + '\n')
                if state.get('cleanup_errors'):
                    self.output.append_stdout('清理未确认：{}\n'.format(state['cleanup_errors']))
                if state.get('display_errors'):
                    self.output.append_stdout('TFT 更新异常：{}\n'.format(state['display_errors']))
                summary = state.get('early_voltage') or state.get('beta') or state.get('ac_analysis')
                if summary:
                    self.output.append_stdout(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
                if state.get('points'):
                    self._display_plot(directory, measurement, state)
                self._display_links(directory, measurement)
            except Exception as error:
                self.last_error = str(error)
                self.output.append_stdout('运行异常：{}\n'.format(error))
            finally:
                for control in self.controls:
                    control.disabled = False
                self.run_button.disabled = False
                self.stop_button.disabled = True

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _display_plot(self, directory, measurement, state):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from IPython.display import Image, display
        directory = Path(directory)
        if measurement == 2:
            figure, axes = plt.subplots(1, 3, figsize=(14, 4.8), constrained_layout=True)
        else:
            figure, axes = plt.subplots(figsize=(8.5, 5.2), constrained_layout=True)
        if measurement == 0:
            with (directory / 'points.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            for curve in sorted({int(row['curve']) for row in rows}):
                curve_rows = [row for row in rows if int(row['curve']) == curve]
                axes.plot([float(row['ube_v']) for row in curve_rows],
                          [float(row['ib_estimated_a']) * 1e6 for row in curve_rows], '.-',
                          label='UCE target {} V'.format(curve_rows[0]['uce_target_v']))
            axes.set(xlabel='UBE (V)', ylabel='IB estimate (uA)', title='NPN input characteristic')
        elif measurement == 1:
            with (directory / 'output_points.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            for curve in sorted({int(row['curve']) for row in rows}):
                curve_rows = [row for row in rows if int(row['curve']) == curve]
                axes.plot([float(row['uce_v']) for row in curve_rows],
                          [float(row['ic_a']) * 1e3 for row in curve_rows], '.-',
                          label='TX1 {} V'.format(curve_rows[0]['tx1_request_v']))
            axes.set(xlabel='UCE (V)', ylabel='IC (mA)', title='NPN output characteristic')
        elif measurement == 2:
            with (directory / 'beta_points.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            beta = state['beta']
            dropped = beta['dropped_initial_base_curves']
            included = [row for row in rows if int(row['curve']) >= dropped]
            excluded = [row for row in rows if int(row['curve']) < dropped]
            window = beta['moving_average_window']
            ib_raw = [float(row['ib_estimated_a']) * 1e6 for row in included]
            ic_raw = [float(row['ic_a']) * 1e3 for row in included]
            beta_raw = [float(row['beta']) for row in included]
            fit_ib = [sum(ib_raw[index:index + window]) / window
                      for index in range(len(ib_raw) - window + 1)]
            fit_ic = [sum(ic_raw[index:index + window]) / window
                      for index in range(len(ic_raw) - window + 1)]
            fit_beta = [sum(beta_raw[index:index + window]) / window
                        for index in range(len(beta_raw) - window + 1)]
            inliers = beta['fit_inlier_mask']
            fit_indices = list(range(len(fit_ib)))
            fit_used = [index for index in fit_indices if inliers[index]]
            fit_ignored = [index for index in fit_indices if not inliers[index]]
            axes[0].scatter(ib_raw, ic_raw, color='0.65', alpha=.35, s=20,
                            label='included raw points')
            if excluded:
                axes[0].scatter([float(row['ib_estimated_a']) * 1e6 for row in excluded],
                                [float(row['ic_a']) * 1e3 for row in excluded],
                                marker='x', color='0.55', label='first 2 excluded')
            axes[0].scatter([fit_ib[index] for index in fit_used],
                            [fit_ic[index] for index in fit_used],
                            color='tab:blue', label='averaged fit points')
            if fit_ignored:
                axes[0].scatter([fit_ib[index] for index in fit_ignored],
                                [fit_ic[index] for index in fit_ignored],
                                facecolors='none', edgecolors='tab:red',
                                label='robust-fit outliers')
            if fit_ib:
                line_x = [min(fit_ib), max(fit_ib)]
                line_y = [beta['fit_slope_beta'] * value * 1e-3 +
                          beta['fit_intercept_a'] * 1e3 for value in line_x]
                axes[0].plot(line_x, line_y, '--', color='tab:red',
                             label='fit β={:.1f}'.format(beta['fit_slope_beta']))
            axes[0].set(xlabel='IB estimate (uA)', ylabel='IC (mA)',
                        title='Ic-Ib linearity')
            axes[0].text(.04, .96,
                         'Error {:.2f}%\nR2 {:.5f}\nBeta {:.1f} +/- {:.2f}%'.format(
                             beta['linearity_error_pct'], beta['r_squared'],
                             beta['beta_mean'], beta['beta_spread_pct']),
                         transform=axes[0].transAxes, va='top', fontsize=9)
            axes[1].plot(ib_raw, beta_raw, 'o', color='0.65', alpha=.35,
                         label='included raw β')
            if excluded:
                axes[1].scatter([float(row['ib_estimated_a']) * 1e6 for row in excluded],
                                [float(row['beta']) for row in excluded],
                                marker='x', color='0.55', label='first 2 excluded')
            axes[1].plot(fit_ib, fit_beta, 'o-', color='tab:green',
                         label='two-point average')
            axes[1].axhline(beta['beta_mean'], color='tab:red', linestyle='--',
                            label='mean β')
            axes[1].ticklabel_format(axis='y', style='plain', useOffset=False)
            axes[1].set(xlabel='IB estimate (uA)', ylabel='hFE / β', title='β vs IB')
            order = sorted(range(len(fit_ic)), key=lambda index: fit_ic[index])
            axes[2].plot([fit_ic[index] for index in order],
                         [fit_beta[index] for index in order], 'o-', color='tab:purple',
                         label='two-point average')
            axes[2].axhline(beta['beta_mean'], color='tab:red', linestyle='--',
                            label='mean β')
            axes[2].ticklabel_format(axis='y', style='plain', useOffset=False)
            axes[2].set(xlabel='IC (mA)', ylabel='hFE / β', title='β vs IC')
            axes[2].text(.98, .04, 'target UCE {:.2f} V'.format(
                             state['linearity_method']['target_uce_v']), transform=axes[2].transAxes,
                         ha='right', fontsize=8)
        else:
            with (directory / 'points.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            axes.semilogx([float(row['actual_freq_hz']) for row in rows],
                          [float(row['gain']) for row in rows], 'o-', label='gain')
            analysis = state.get('ac_analysis', {})
            if analysis:
                axes.axhline(analysis['target_gain'], color='tab:red', linestyle='--', label='0.707 Au')
                axes.axvline(analysis['f_beta_hz'], color='tab:green', linestyle=':', label='f-beta')
            axes.set(xlabel='Frequency (Hz)', ylabel='Voltage gain (V/V)', title='NPN frequency response')
        plot_axes = axes if measurement == 2 else [axes]
        for axis in plot_axes:
            axis.grid(alpha=.25)
            axis.legend(loc='best', fontsize=8)
        if state.get('simulated'):
            plot_axes[0].text(.98, .02, 'SIMULATED', transform=plot_axes[0].transAxes,
                      ha='right', color='#ad3e2e', weight='bold')
        image_path = directory / 'curves.png'
        figure.savefig(str(image_path), dpi=160)
        plt.close(figure)
        self.output.append_display_data(Image(filename=str(image_path)))

    def _display_links(self, directory, measurement):
        from IPython.display import FileLink
        directory = Path(directory)
        names = ['run.json']
        names += {0: ['points.csv', 'frames.jsonl'],
                  1: ['output_points.csv', 'frames.jsonl'],
                  2: ['beta_points.csv', 'beta_trace.csv', 'frames.jsonl'],
                  3: ['points.csv', 'statistics.jsonl']}[measurement]
        names.append('curves.png')
        for name in names:
            path = directory / name
            if not path.is_file():
                self.output.append_stdout('{}: {}\n'.format(name, path))
                continue
            try:
                relative = os.path.relpath(str(path), str(Path.cwd()))
            except ValueError:
                self.output.append_stdout('{}: {}\n'.format(name, path))
            else:
                self.output.append_display_data(FileLink(relative))

    def display(self):
        from IPython.display import display
        display(self.view)
        return self
