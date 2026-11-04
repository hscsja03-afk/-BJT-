"""NPN small-signal frequency-response scan using the streaming ADC statistics path."""
from dataclasses import asdict, dataclass
from pathlib import Path
import csv
import json
import math
import statistics
import threading
import time
import uuid

from .analysis import fit_ac_response, input_resistance_summary
from .scan import validate_measurement_board, measurement_basis
from .profiles import Profile, validate_profile_config, assumptions
from .sweep import segmented_values

DEFAULT_FREQUENCY_SEGMENTS = '10000:150000:10000;200000:5000000:100000'


@dataclass(frozen=True)
class AcScanConfig:
    profile: str = 'npn_small'
    tx1_bias_v: float = 0.2
    tx2_vcc_control_v: float = 1.5
    tx3_input_vpp: float = 0.05
    source_buffer_gain: float = 0.84
    adc_amplitude_multiplier: float = 1.0
    input_channel: int = 0
    output_channel: int = 1
    input_adc_per_v: float = 9.78
    output_adc_per_v: float = 0.206
    input_sample_gain: float = 1.0
    input_test_resistor_ohm: float = 100.0  # User-confirmed series resistor, 2026-11-02.
    collector_resistor_ohm: float = 100.0
    base_resistance_ohm: float = 2000.0
    sample_count: int = 50000
    repeat_count: int = 3
    settle_s: float = 0.1
    passband_stop_hz: float = 150000.0
    target_ratio: float = 0.707
    final_tolerance_hz: float = 10000.0
    max_bisection_iterations: int = 16
    frequency_segments_hz: str = DEFAULT_FREQUENCY_SEGMENTS

    def validate(self, calibration, frontend):
        validate_profile_config(self, 'ac')
        if not .02 <= self.tx1_bias_v <= 2: raise ValueError('Base control must be 20 mV..2 V')
        calibration.dac_code(0, self.tx1_bias_v)
        calibration.dac_code(1, self.tx2_vcc_control_v)
        calibration.sine_samples(10000.0, self.tx3_input_vpp)
        if self.input_channel not in (0, 1) or self.output_channel not in (0, 1) or \
                self.input_channel == self.output_channel:
            raise ValueError("AC input/output must map to distinct ADC channels")
        for value in (self.adc_amplitude_multiplier, self.source_buffer_gain, self.input_adc_per_v, self.output_adc_per_v,
                      self.input_sample_gain, self.input_test_resistor_ohm,
                      self.collector_resistor_ohm, self.passband_stop_hz,
                      self.target_ratio, self.final_tolerance_hz):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("AC transfer values must be finite and positive")
        if self.target_ratio >= 1:
            raise ValueError("AC cutoff ratio must be below one")
        if type(self.sample_count) is not int or not 8 <= self.sample_count <= 50000:
            raise ValueError("AC capture must contain 8..50000 samples per ADC channel")
        if type(self.repeat_count) is not int or not 2 <= self.repeat_count <= 10:
            raise ValueError("Use 2..10 independent AC captures per frequency")
        if type(self.max_bisection_iterations) is not int or not 0 <= self.max_bisection_iterations <= 24:
            raise ValueError("Invalid f-beta refinement limit")
        if not math.isfinite(self.settle_s) or not 0 <= self.settle_s <= 60:
            raise ValueError("Invalid AC settling time")
        frequencies=segmented_values(self.frequency_segments_hz,1000,5000000,500)
        if len(frequencies)<6 or not frequencies[0]<=self.passband_stop_hz<frequencies[-1]:
            raise ValueError('交流至少需要6个频点，且须覆盖通带分析上限的两侧')
        for frequency in (frequencies[0],frequencies[-1]):calibration.sine_samples(frequency,self.tx3_input_vpp)
        return frequencies


def run_ac_scan(board, calibration, frontend, config, output_root, cancel=None,
                qualification=None, emit=lambda event, value: None, defer_analysis=False):
    frequencies = config.validate(calibration, frontend)
    simulated = validate_measurement_board(board, calibration, frontend, qualification)
    source_plan = calibration.sine_parameters(frequencies[0], config.tx3_input_vpp)
    if not simulated:
        source_plan = calibration.bind_waveform_plan(source_plan, board.identity)
    if (not simulated and qualification and qualification.get('status') == 'validated'
            and source_plan['amplitude_basis'] != 'scope_verified_reference'):
        raise ValueError('本次 TX3 扫频范围尚未完整校准，预热单点记录不代表全部频点已校准；请使用参考参数换算模式')
    profile = Profile(config.profile)
    route = profile.route('ac')
    cancel = cancel or threading.Event()
    outputs_before = [board.output(channel) for channel in (0, 1, 2)]
    if any(output.enabled for output in outputs_before):
        raise RuntimeError("All analog outputs must be idle before an AC scan")
    original_gpio = board.gpio()
    if (original_gpio["output"] ^ original_gpio["sense"]) & 0x7f:
        raise RuntimeError("GPIO pin feedback is inconsistent before scanning")
    gpio_pin_by_bit = {0: 87, 1: 85, 2: 83, 3: 81, 4: 79, 5: 77, 6: 48}
    gpio_mask = 0x7f
    gpio_value = route['value']
    gpio_pin_values = route['pin_values']
    if cancel.is_set():
        raise InterruptedError("AC scan cancelled before starting")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    from .result_paths import create_run
    directory = create_run(output_root, config.profile, 'ac')
    state = {"schema_version": 1, "measurement": "ac", "status": "running",
             "profile":config.profile, "measurement_basis":measurement_basis(simulated,qualification),
             "parameter_basis":assumptions(config.profile,'ac'),
             "simulated": simulated, "config": asdict(config), "frontend": asdict(frontend),
             "calibration": calibration.manifest(), "qualification": qualification,
             "board_identity": dict(board.identity), "initial_gpio": original_gpio,
             "initial_outputs": [asdict(output) for output in outputs_before],
             "points": 0, "cleanup_errors": [], "started_at": time.time(),
             "source_parameters": {
                 "project_source": "text5.21_52mv_curve_fit.py",
                 "legacy_source": "TX1/CH0=0.2 V DC; TX2/CH1=1.4 V DC; Digital IO0 square sweep; 52 mVpp fundamental",
                 "migration_assumption": "TX3 sine replaces the legacy Digital IO0 square source; amplitude qualification follows the active calibration profile and source amplitude basis",
                 "tx3_profile_validation_status": calibration.dac['channels'][2]['sine_50mv'].get('validation_status'),
                 "tx1_nominal_current_a": config.tx1_bias_v / config.base_resistance_ohm,
                 "tx2_nominal_vcc_v": config.tx2_vcc_control_v * frontend.collector_amplifier_gain,
                 "tx3_input_vpp": config.tx3_input_vpp,
                 "tx3_amplitude_basis": source_plan['amplitude_basis'],
                 "tx3_bitstream_reference": source_plan.get('bitstream_reference'),
                 "tx3_reference_amplitude_basis": source_plan.get('reference_amplitude_basis',source_plan['amplitude_basis']),
                 "tx3_reference_vpp": source_plan['reference_vpp'],
                 "tx3_amplitude_scale": source_plan['scale'],
                 "source_buffer_gain": config.source_buffer_gain,
                 "adc_amplitude_multiplier": config.adc_amplitude_multiplier,
                 "effective_source_vpp": config.tx3_input_vpp * config.source_buffer_gain,
                 "input_sample_gain": config.input_sample_gain,
                 "input_test_resistor_ohm": config.input_test_resistor_ohm,
                 "collector_resistor_ohm": config.collector_resistor_ohm,
                 "beta_gain_equation": "beta ~= (RB/RE)*VE_peak/(Vin_peak-VB_peak); IC ~= IE; RB=input_test_resistor_ohm; RE=collector_resistor_ohm" if profile.pnp else "(output_rms*sqrt(2)/Rcollector) / ((tx3_vpp*source_buffer_gain/2-input_rms*sqrt(2)/sample_gain)/Rinput)",
                 "amplitude_convention": "All formula voltages are AC peak amplitudes; measured RMS is multiplied by sqrt(2), TX3 Vpp by source_buffer_gain/2",
                 "input_current_equation": "IB_peak=(Vin_peak-VB_peak)/RB; Vin is buffer output before RB; VB=input_rms*sqrt(2)/input_sample_gain",
                 "formula_assumptions": "Vin and VB assumed in phase with Vin_peak>VB_peak; VCC assumed AC ground; phase is not measured",
                 "output_node": "VE" if profile.pnp else "VC",
                 "gpio_mask": gpio_mask,
                 "gpio_value": gpio_value,
                 "gpio_pin_by_bit": gpio_pin_by_bit,
                 "gpio_pin_values": gpio_pin_values,
                 "capture_window_seconds_at_50msps": config.sample_count / 50000000.0,
                 "low_frequency_cycles_at_50msps": config.sample_count * frequencies[0] / 50000000.0,
                 "outputs_enabled_during_scan": [0, 1, 2],
                 "outputs_disabled_on_exit": [0, 1, 2],
             }}

    def save():
        temp = directory / "run.json.tmp"
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(directory / "run.json")

    def pause(seconds):
        if cancel.wait(seconds):
            raise InterruptedError("AC scan cancelled")

    def measure_frequency(frequency_hz, mode, raw):
        if cancel.is_set():
            raise InterruptedError("AC scan cancelled")
        gpio = board.gpio()
        if gpio['output'] & gpio_mask != gpio_value or (gpio['output'] ^ gpio['sense']) & gpio_mask:
            raise RuntimeError('AC relay state changed during measurement')
        if not all(board.output(i).enabled for i in (0,1,2)):
            raise RuntimeError('AC output state changed during measurement')
        board.set_sine(2, calibration, frequency_hz, config.tx3_input_vpp)
        pause(config.settle_s)
        input_values, output_values, captures = [], [], []
        for repeat in range(config.repeat_count):
            capture = board.capture_statistics(config.sample_count)
            captures.append(capture)
            raw.write(json.dumps({"frequency_hz": frequency_hz, "mode": mode,
                                  "repeat": repeat, "statistics": capture}, ensure_ascii=False) + "\n")
            raw.flush()
            if bool(capture.get("simulated", simulated)) != simulated:
                raise ValueError("Mixed simulated and real AC statistics")
            input_stats = capture["channels"][config.input_channel]
            output_stats = capture["channels"][config.output_channel]
            if input_stats["fault_count"] or output_stats["fault_count"]:
                raise ValueError("AC ADC overrange or clipped samples")
            input_v_rms = _rms_voltage(calibration, config.input_channel,
                                       input_stats["rms_code"], config.input_adc_per_v) * config.adc_amplitude_multiplier
            output_v_rms = _rms_voltage(calibration, config.output_channel,
                                        output_stats["rms_code"], config.output_adc_per_v) * config.adc_amplitude_multiplier
            if input_v_rms <= 0:
                raise ValueError("AC reference input is below the calibrated noise floor")
            input_values.append(input_v_rms)
            output_values.append(output_v_rms)
            pause(0)
        input_rms = statistics.fmean(input_values)
        output_rms = statistics.fmean(output_values)
        input_node_peak = input_rms * math.sqrt(2.0) / config.input_sample_gain
        source_peak = config.tx3_input_vpp * config.source_buffer_gain / 2.0
        input_resistor_peak = source_peak - input_node_peak
        if input_resistor_peak <= 1e-9:
            raise ValueError("交流幅度不一致：补偿后 VB={:.3f} mVpp，缓冲后激励={:.3f} mVpp；激励减 VB 不为正，无法按当前幅度相减法计算基极电流和 β。请核实激励幅度、反馈比例及相位。".format(input_node_peak * 2000, source_peak * 2000))
        input_current_peak = input_resistor_peak / config.input_test_resistor_ohm
        output_node_peak = output_rms * math.sqrt(2.0)
        sensed_current_peak = output_node_peak / config.collector_resistor_ohm
        # User requested IC ~= IE for PNP; do not subtract IB magnitudes.
        output_current_peak = sensed_current_peak
        if output_current_peak <= 0:
            raise ValueError('交流电流换算非正：请核对输出反馈及幅度')
        # PNP emitter follower: beta ~= (RB/RE)*VE/(Vin-VB).
        # This is algebraically the same IE/IB approximation; no coefficient
        # changes and no subtraction of unrelated node amplitudes VE-VB.
        gain = ((config.input_test_resistor_ohm / config.collector_resistor_ohm)
                * output_node_peak / input_resistor_peak) if profile.pnp else output_current_peak / input_current_peak
        adc = {}
        for ch, name in enumerate(('rx1', 'rx2')):
            samples = [capture['channels'][ch] for capture in captures]
            rms_code = statistics.fmean(sample['rms_code'] for sample in samples)
            means = [sample['mean_code'] for sample in samples if sample.get('mean_code') is not None]
            mean_code = statistics.fmean(means) if len(means) == len(samples) else None
            adc.update({name+'_rms_code':rms_code, name+'_mean_code':mean_code,
                        name+'_port_ac_rms_v':_rms_voltage(calibration, ch, rms_code, 1.0),
                        name+'_port_v':calibration.port_v(mean_code, ch) if mean_code is not None else None})
        return dict(adc, **{"actual_freq_hz": frequency_hz, "mode": mode,
                "tx1_bias_v":config.tx1_bias_v, "tx2_vcc_control_v":config.tx2_vcc_control_v,
                "vcc_predicted_v":config.tx2_vcc_control_v*frontend.collector_amplifier_gain,
                "profile":config.profile, "measurement_basis":state['measurement_basis'],
                "input_rms_v": input_rms, "output_rms_v": output_rms,
                "input_vpp_sine_estimate": 2.0 * math.sqrt(2.0) * input_rms,
                "output_vpp_sine_estimate": 2.0 * math.sqrt(2.0) * output_rms,
                "input_node_v_peak": input_node_peak,
                "source_node_v_peak": source_peak,
                "input_resistor_v_peak": input_resistor_peak,
                "output_node_v_peak": output_node_peak,
                "phase_basis": "Vin_VB_in_phase_assumed_not_measured",
                "input_current_a_peak": input_current_peak,
                "output_current_a_peak": output_current_peak,
                "emitter_current_a_peak": sensed_current_peak if profile.pnp else output_current_peak + input_current_peak,
                "current_basis": "IC_equals_IE_approximation" if profile.pnp else "collector_resistor_magnitude",
                "input_resistance_ohm": input_node_peak / input_current_peak,
                "gain": gain,
                "input_repeat_std_v": statistics.pstdev(input_values),
                "output_repeat_std_v": statistics.pstdev(output_values)})

    previous_transfer = None
    if simulated and hasattr(board, "set_ac_transfer"):
        previous_transfer = board.set_ac_transfer({
            "input_channel": config.input_channel, "output_channel": config.output_channel,
            "source_buffer_gain": config.source_buffer_gain,
                 "adc_amplitude_multiplier": config.adc_amplitude_multiplier,
            "input_adc_per_v": config.input_adc_per_v,
            "output_adc_per_v": config.output_adc_per_v,
            "input_sample_gain": config.input_sample_gain,
            "input_test_resistor_ohm": config.input_test_resistor_ohm,
            "output_resistor_ohm": config.collector_resistor_ohm,
            "pnp_emitter_sense": profile.pnp,
        })
    changed = False
    points = []
    def release_hardware():
        nonlocal changed
        if not changed: return
        started=time.monotonic()
        for channel in (0,1,2):
            try:
                if board.enable(channel,False).enabled: raise RuntimeError('Output still enabled')
            except Exception as error:
                state['cleanup_errors'].append('TX{}: {}'.format(channel+1,error))
        try: state['final_gpio']=board.gpio(0x7f,original_gpio['output'])
        except Exception as error: state['cleanup_errors'].append('GPIO restore: {}'.format(error))
        changed=False
        state['hardware_released_at']=time.time()
        state['hardware_release_seconds']=time.monotonic()-started
        emit('log','采样结束：三路输出关闭、IO 恢复已确认；正在计算拟合。' if not state['cleanup_errors'] else '输出/IO 清理未确认，请查看运行记录。')
    if hasattr(board, "display_status"):
        _display(board, [profile.key.upper(), "AC FREQUENCY SWEEP", "OUTPUTS OFF"], state)
    save()
    try:
        with (directory / "statistics.jsonl").open("w", encoding="utf-8") as raw:
            changed = True
            for channel in (0, 1, 2):
                board.enable(channel, False)
            board.gpio(gpio_mask, gpio_value)
            pause(.05)
            gpio = board.gpio()
            if (gpio["output"] & gpio_mask) != (gpio_value & gpio_mask) or \
                    (gpio["output"] ^ gpio["sense"]) & gpio_mask:
                raise RuntimeError("BJT AC GPIO state did not latch")
            board.set_code(0, calibration.dac_code(0, config.tx1_bias_v)[0])
            board.set_code(1, calibration.dac_code(1, config.tx2_vcc_control_v)[0])
            board.set_sine(2, calibration, frequencies[0], config.tx3_input_vpp)
            changed = True
            for channel in (0, 1, 2):
                board.enable(channel, True)
            for index, frequency in enumerate(frequencies):
                points.append(measure_frequency(frequency, "coarse", raw))
                state["points"] = len(points)
                if index % 3 == 2:
                    _display(board, [profile.key.upper(), "AC FREQUENCY SWEEP",
                                     "POINT {}/{}".format(index + 1, len(frequencies)),
                                     "{} kHz".format(int(frequency / 1000)),
                                     "TX1 {:.2f}; TX2 {:.2f}; TX3 {:.0f}mVpp".format(
                                         config.tx1_bias_v, config.tx2_vcc_control_v,
                                         config.tx3_input_vpp * 1000)], state)
                emit("point", points[-1])
            valid_passband = [point["gain"] for point in points
                              if point["actual_freq_hz"] <= config.passband_stop_hz and point["gain"] > 0]
            if not valid_passband:
                raise ValueError("No valid passband points; cannot estimate Au")
            preliminary_au = statistics.fmean(valid_passband)
            target_gain = preliminary_au * config.target_ratio
            below = sorted((point for point in points
                            if point["actual_freq_hz"] > config.passband_stop_hz and point["gain"] <= target_gain),
                           key=lambda point: point["actual_freq_hz"])
            above = sorted((point for point in points
                            if point["actual_freq_hz"] > config.passband_stop_hz and point["gain"] > target_gain),
                           key=lambda point: point["actual_freq_hz"])
            if above and below:
                emit('log','进入截止频率补测：频率会返回截止点附近；图线始终按频率从低到高排列。')
                low = max(above, key=lambda point: point["actual_freq_hz"])
                high = min((point for point in below if point["actual_freq_hz"] > low["actual_freq_hz"]),
                           key=lambda point: point["actual_freq_hz"], default=None)
                for iteration in range(config.max_bisection_iterations):
                    if high is None or high["actual_freq_hz"] - low["actual_freq_hz"] <= config.final_tolerance_hz:
                        break
                    middle_hz = (low["actual_freq_hz"] + high["actual_freq_hz"]) / 2.0
                    middle = measure_frequency(middle_hz, "refine", raw)
                    points.append(middle)
                    state["points"] = len(points)
                    if middle["gain"] > target_gain:
                        low = middle
                    else:
                        high = middle
                    emit("point", middle)
            state['acquisition_finished_at']=time.time()
            release_hardware()
            if state['cleanup_errors']: raise RuntimeError('Hardware cleanup not confirmed')
            state['fit_context']=dict(preliminary_passband_au=preliminary_au,preliminary_target_gain=target_gain,refinement_tolerance_hz=config.final_tolerance_hz)
            if defer_analysis:
                state['status']='acquired';state['analysis_location']='pending_desktop_python'
                emit('log','采集完成、输出已关闭，数据取回后由电脑 Python 拟合。')
            else:
                _analyze_points(state,points,'board_python' if not simulated else 'simulation_python')
    except BaseException as error:
        state["status"] = "cancelled" if isinstance(error, InterruptedError) else "failed"
        state["error"] = "{}: {}".format(type(error).__name__, error)
    finally:
        release_hardware()
        if simulated and hasattr(board, "set_ac_transfer"):
            board.set_ac_transfer(previous_transfer)
        if state["status"] == "complete":
            fit = state["ac_analysis"]
            final_lines = ["AC COMPLETE",
                           "fB {:.1f} kHz".format(fit["f_beta_hz"] / 1000),
                           "fT {:.2f} MHz".format(fit["ft_hz"] / 1e6),
                           "OUTPUTS MUTED"]
        elif state["status"]=="acquired":
            final_lines=["AC ACQUIRED","FIT ON DESKTOP","OUTPUTS MUTED"]
        else:
            final_lines = ["AC STOPPED", "POINTS {}".format(state["points"]),
                           "OUTPUTS MUTED"]
        _display(board, [profile.key.upper()] + final_lines, state)
        if state["cleanup_errors"]:
            state["status"] = "cleanup_failed"
        with (directory / "points.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=("actual_freq_hz", "mode", "input_rms_v",
                "output_rms_v", "input_vpp_sine_estimate", "output_vpp_sine_estimate", "gain",
                "input_node_v_peak", "source_node_v_peak", "input_resistor_v_peak", "output_node_v_peak", "phase_basis",
                "input_current_a_peak", "output_current_a_peak", "emitter_current_a_peak", "current_basis",
                "input_resistance_ohm", "input_repeat_std_v", "output_repeat_std_v", "simulated", "profile", "measurement_basis",
                "rx1_mean_code", "rx2_mean_code", "rx1_rms_code", "rx2_rms_code", "rx1_port_v", "rx2_port_v",
                "rx1_port_ac_rms_v", "rx2_port_ac_rms_v", "tx1_bias_v", "tx2_vcc_control_v", "vcc_predicted_v"))
            writer.writeheader()
            writer.writerows(dict(point, simulated=int(simulated)) for point in
                             sorted(points, key=lambda point: point["actual_freq_hz"]))
        state["finished_at"] = time.time()
        save()
    emit("finished", state)
    return directory, state


def _legacy_frequency_list():
    return tuple(list(range(10000, 150001, 10000)) + list(range(200000, 2000001, 100000)))


def _rms_voltage(calibration, channel, rms_code, adc_per_v):
    profile = (calibration.rx1, calibration.rx2)[channel]
    return float(rms_code) * abs(profile["slope_nv_per_code"]) / 1e9 / adc_per_v


def _display(board, lines, state):
    if not hasattr(board, "display_status"):
        return
    try:
        board.display_status(lines)
    except Exception as error:
        state.setdefault("display_errors", []).append(str(error))


def _analyze_points(state,points,location):
    started=time.monotonic()
    state['input_resistance_analysis']=input_resistance_summary(points,state['config']['passband_stop_hz'])
    state['input_resistance_analysis']['test_resistor_ohm']=state['config']['input_test_resistor_ohm']
    state['ac_analysis']=fit_ac_response(points,state['config']['passband_stop_hz'])
    state['ac_analysis'].update(state.get('fit_context',{}))
    state['analysis_seconds']=time.monotonic()-started
    state['analysis_location']=location;state['status']='complete'


def finish_host_analysis(directory):
    directory=Path(directory);path=directory/'run.json'
    state=json.loads(path.read_text(encoding='utf-8'))
    if state.get('status')!='acquired' or state.get('measurement')!='ac':return state
    if state.get('cleanup_errors'):raise RuntimeError('输出清理未确认')
    with (directory/'points.csv').open(encoding='utf-8-sig',newline='') as stream:points=list(csv.DictReader(stream))
    try:_analyze_points(state,points,'desktop_python')
    except Exception as error:state.update(status='analysis_failed',error=str(error))
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
    return state
