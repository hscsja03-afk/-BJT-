"""NPN output curves and beta-linearity scans on the shared board interface."""
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
import csv
import json
import math
import statistics
import threading
import time
import uuid

from .analysis import (BETA_ACTIVE_UCE_MIN_V, analyze_beta_linearity, collector_current_a,
                       fit_early_voltage, pick_at_target_uce)
from .scan import validate_measurement_board, measurement_basis
from .profiles import Profile, validate_profile_config, assumptions
from .pulse import default_noise_span_v

ADC_DETAILS = ('rx1_mean_code', 'rx2_mean_code', 'rx1_port_v', 'rx2_port_v', 'vcc_predicted_v',
               'base_resistance_ohm', 'tx1_table_v', 'scan_mode')
BETA_DETAILS = ADC_DETAILS + ('sample_index', 'sample_uce_v', 'sample_ic_a', 'adc_basis',
                              'vcc_v', 'vc_v', 've_v', 'tx2_request_v')
from .sweep import segmented_values


@dataclass(frozen=True)
class OutputScanConfig:
    profile: str = 'npn_small'
    scan_mode: str = '步进'
    pulse_frequency_hz: float = 10.0
    pulse_duty_percent: float = 20.0
    pulse_attempts_per_frame: int = 30
    pulse_noise_span_v: float = None
    base_control_v: tuple = (0.05, 0.15, 0.25)
    tx2_control_start_v: float = 0.0
    tx2_control_stop_v: float = 0.25
    tx2_control_step_v: float = 0.01
    tx2_segments_v: str = ''
    base_resistance_ohm: float = None
    collector_resistor_ohm: float = 100.0
    collector_channel: int = 1
    source_channel: int = 0
    collector_adc_per_v: float = 0.206
    source_adc_per_v: float = .206
    settle_s: float = 0.1
    frames_per_point: int = 3

    def __post_init__(self):
        if self.pulse_noise_span_v is None:
            object.__setattr__(self, 'pulse_noise_span_v', default_noise_span_v(self.profile))
        if self.base_resistance_ohm is None:
            object.__setattr__(self, 'base_resistance_ohm', Profile(self.profile).base_ohm('output'))

    def validate(self, calibration, frontend):
        validate_profile_config(self, 'output')
        controls = (segmented_values(self.tx2_segments_v,0,1.8) if self.tx2_segments_v else
                    _decimal_range(self.tx2_control_start_v, self.tx2_control_stop_v,self.tx2_control_step_v,maximum=1.8))
        if not self.base_control_v or len(self.base_control_v) > 64:
            raise ValueError("Expected 1..64 base-control values")
        for value in self.base_control_v:
            if not .02 <= float(value) <= 2: raise ValueError('Base control must be 20 mV..2 V')
            calibration.dac_code(0, float(value))
        for value in controls:
            calibration.dac_code(1, value)
        _validate_common(self, frontend)
        _validate_source_range(self, calibration, frontend, max(controls))
        if self.collector_channel not in (0, 1) or self.source_channel not in (0, 1):
            raise ValueError("ADC channel mapping must select RX1 or RX2")
        if self.collector_channel == self.source_channel:
            raise ValueError("Collector and source feedback must use different ADC channels")
        return controls


@dataclass(frozen=True)
class BetaScanConfig:
    profile: str = 'npn_small'
    scan_mode: str = '步进'
    pulse_frequency_hz: float = 10.0
    pulse_duty_percent: float = 20.0
    pulse_attempts_per_frame: int = 30
    pulse_noise_span_v: float = None
    tx1_start_v: float = 0.02
    tx1_stop_v: float = 0.50
    tx1_step_v: float = 0.01
    tx1_segments_v: str = ''
    target_uce_v: float = 5.0
    target_window_v: float = 0.12
    max_target_error_v: float = 0.03
    tx2_first_start_v: float = 0.95
    tx2_start_increment_v: float = 0.0
    tx2_step_v: float = 0.01
    tx2_min_v: float = 0.0
    tx2_stop_v: float = 1.25
    base_resistance_ohm: float = None
    collector_resistor_ohm: float = 100.0
    collector_channel: int = 1
    source_channel: int = 0
    collector_adc_per_v: float = 0.206
    source_adc_per_v: float = .206
    drop_initial_points: int = 2
    moving_average_window: int = 2
    settle_s: float = 0.05
    frames_per_point: int = 3

    def __post_init__(self):
        if self.pulse_noise_span_v is None:
            object.__setattr__(self, 'pulse_noise_span_v', default_noise_span_v(self.profile))
        if self.base_resistance_ohm is None:
            object.__setattr__(self, 'base_resistance_ohm', Profile(self.profile).base_ohm('beta'))

    def validate(self, calibration, frontend):
        validate_profile_config(self, 'beta')
        if not self.tx1_segments_v and self.tx1_start_v < .02: raise ValueError('Base control must start at or above 20 mV')
        base_values = _base_values(self,True)
        tx2_max = min(self.tx2_stop_v, 1.8)
        if not 0 <= self.tx2_min_v <= self.tx2_first_start_v <= tx2_max:
            raise ValueError("TX2 beta-search interval is outside the calibrated 0..1.8 V range")
        if self.target_uce_v <= BETA_ACTIVE_UCE_MIN_V or \
                not 0 < self.target_window_v <= self.target_uce_v:
            raise ValueError("Invalid beta target UCE or target window")
        if not 0 < self.max_target_error_v <= 5:
            raise ValueError("Invalid maximum target-UCE error")
        if self.drop_initial_points < 0 or self.moving_average_window < 1:
            raise ValueError("Invalid beta post-processing settings")
        for value in base_values:
            calibration.dac_code(0, value)
        for value in (self.tx2_min_v, self.tx2_first_start_v, tx2_max):
            calibration.dac_code(1, value)
        _validate_common(self, frontend)
        _validate_source_range(self, calibration, frontend, tx2_max)
        _validate_channels(self)
        return base_values


def run_output_scan(board, calibration, frontend, config, output_root, cancel=None,
                    qualification=None, emit=lambda event, value: None):
    controls = config.validate(calibration, frontend)
    return _run_scan(board, calibration, frontend, config, output_root, controls,
                     cancel, qualification, beta_mode=False, emit=emit)


def run_beta_scan(board, calibration, frontend, config, output_root, cancel=None,
                  qualification=None, emit=lambda event, value: None):
    base_values = config.validate(calibration, frontend)
    controls = {i: _beta_tx2_values(config, i, calibration) for i in range(len(base_values))}
    return _run_scan(board, calibration, frontend, config, output_root, controls,
                     cancel, qualification, beta_mode=True, emit=emit)


def _run_scan(board, calibration, frontend, config, output_root, scan_values, cancel,
              qualification, beta_mode, emit):
    simulated = validate_measurement_board(board, calibration, frontend, qualification)
    profile = Profile(config.profile)
    pulsed = config.scan_mode == '脉冲'
    if pulsed and not callable(getattr(board, 'set_pulse', None)):
        raise ValueError('当前板端不支持集电极脉冲')
    if pulsed and not simulated and not board.core.io.read(0x0c) & 0x80000000:
        raise ValueError('脉冲扫描需要支持长窗口采集的位流')
    route = profile.route('beta' if beta_mode else 'output')
    cancel = cancel or threading.Event()
    initial_outputs = [board.output(ch) for ch in (0, 1, 2)]
    if any(output.enabled for output in initial_outputs):
        raise RuntimeError("All analog outputs must be idle before a BJT scan")
    original_gpio = board.gpio()
    if (original_gpio["output"] ^ original_gpio["sense"]) & 0x7f:
        raise RuntimeError("GPIO pin feedback is inconsistent before scanning")
    if cancel.is_set():
        raise InterruptedError("Scan cancelled before starting")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    from .result_paths import create_run
    directory = create_run(output_root, config.profile, 'beta' if beta_mode else 'output', 'pulse' if pulsed else 'step')
    state = {"schema_version": 1, "measurement": "beta" if beta_mode else "output",
             "measurement_name": ("PNP" if profile.pnp else "NPN") + (" output beta linearity" if beta_mode else " output characteristics and Early voltage"),
             "status": "running", "simulated": simulated, "config": asdict(config),
             "method": 'pulse' if pulsed else 'step',
             "frontend": asdict(frontend), "calibration": calibration.manifest(),
             "qualification": qualification, "board_identity": dict(board.identity),
             "initial_outputs": [asdict(output) for output in initial_outputs],
             "initial_gpio": original_gpio, "started_at": time.time(), "points": 0,
             "cleanup_errors": [], "current_basis": "TX1 nominal voltage / {} ohm; not measured current".format(config.base_resistance_ohm),
             "profile":config.profile, "measurement_basis":measurement_basis(simulated,qualification),
             "parameter_basis":assumptions(config.profile,'beta' if beta_mode else 'output'),
             "source_basis": "RX feedback voltage converted with the selected calibration channel",
             "gpio_pin_by_bit": {0: 87, 1: 85, 2: 83, 3: 81, 4: 79, 5: 77, 6: 48},
             "linearity_method": ({
                 "project_source": {"npn_small":"text.4.1.10_NST.py", "npn_big":"text.4.1.13_NBT.py", "pnp_small":"text.4.1.15_PST.py", "pnp_big":"text.4.1.16_PBT.py"}[profile.key],
                 "base_current": "IB_est = TX1 / {} ohm; command-derived estimate".format(config.base_resistance_ohm),
                 "collector_current": ("IC ~= IE = (VCC-VE)/R; user requested approximation" if profile.pnp else "IC = (VCC - VC) / RC"),
                 "active_region_min_uce_v": BETA_ACTIVE_UCE_MIN_V,
                 "point_selection": "Sweep TX2 around target UCE; use only positive-IC points above 1 V UCE, interpolate at the target, and reject distant nearest points",
                 "target_uce_v": config.target_uce_v,
                 "dropped_initial_base_points": config.drop_initial_points,
                 "reported_metrics": ["max_abs_fit_error / IC_span", "R_squared", "beta_spread_percent"],
             } if beta_mode else None)}

    def save():
        target = directory / "run.json"
        temp = directory / "run.json.tmp"
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(target)

    def pause(seconds):
        if cancel.wait(seconds):
            raise InterruptedError("Scan cancelled")

    def record_point(row):
        writer.writerow(row)
        stream.flush()
        state['points'] += 1
        emit('progress' if beta_mode else 'point', row)

    gpio_mask, gpio_value = route['mask'], route['value']
    previous_transfer = None
    if simulated and hasattr(board, "set_measurement_transfer"):
        previous_transfer = board.set_measurement_transfer({
            "profile":config.profile, "measurement":"output",
            "pulsed": pulsed,
            "base_resistance_ohm": config.base_resistance_ohm,
            "collector_resistor_ohm": config.collector_resistor_ohm,
            "collector_channel": config.collector_channel,
            "source_channel": config.source_channel,
            "collector_adc_per_v": config.collector_adc_per_v,
            "source_adc_per_v": config.source_adc_per_v,
        })
    changed = False
    frame_sequences = set()
    all_curve_rows = []
    beta_rows = []
    skipped_beta = []
    previous_beta_control = None
    state["source_parameters"] = {
        "gpio_mask": gpio_mask, "gpio_value": gpio_value,
        "gpio_pin_values": route['pin_values'],
        "collector_current_equation": "IC ~= IE = (VCC-VE)/R" if profile.pnp else "(VCC-VC)/RC",
        "project_source": ({"npn_small":"text.4.1.10_NST.py", "npn_big":"text.4.1.13_NBT.py", "pnp_small":"text.4.1.15_PST.py", "pnp_big":"text.4.1.16_PBT.py"}[profile.key] if beta_mode else
                           {"npn_small":"text.4.1.11_NS.py", "npn_big":"text.4.1.12_NB.py", "pnp_small":"text.4.1.14_PS.py", "pnp_big":"text.4.1.8_PB.py"}[profile.key]),
        "collector_adc_per_v": config.collector_adc_per_v,
        "source_adc_per_v": config.source_adc_per_v,
        "source_adc_ratio_note": "User-confirmed VCC * 0.206 at RX1; VCC is derived from measured feedback, not TX2 setpoint",
        "beta_search_start": "Previous accepted TX2, bounded secant prediction and bracket refinement; up to 32 measurements" if beta_mode else None,
        "analog_outputs_enabled_during_scan": [0, 1],
        "analog_outputs_disabled_on_exit": [0, 1, 2],
    }
    if pulsed:
        pulse_source='zynq_bjt.characteristics PNP pulse extension' if profile.pnp else ('pulseNBT.py' if beta_mode else 'pulseNB.py')
        state['source_parameters'].update(project_source=pulse_source,
            pulse_frequency_hz=config.pulse_frequency_hz, pulse_duty_percent=config.pulse_duty_percent, pulse_low_v=0,
            capture_method='stride256, complete stable plateau fragments, independent trimmed means',
            migration_note='1024 points / stride<=256; no full-cycle or paired-sample cancellation claim',
            resistor_note='Current fixture RC is retained; legacy pulse scripts used 0.5 ohm')
        if profile.pnp:
            state['source_parameters'].update(pulse_supply='TX2 amplified VCC; C grounded; emitter feedback RX2',
                                              pulse_hardware_validation='pending',pulse_current_basis='IC approximately IE = (VCC - VE) / RC')
        if beta_mode: state['linearity_method']['project_source']=pulse_source
    _display_status(board, [profile.key.upper(), "OUTPUT / EARLY" if not beta_mode else "BETA LINEARITY",
                            "Starting; outputs idle"], state)
    save()
    try:
        csv_name = "beta_trace.csv" if beta_mode else "output_points.csv"
        with (directory / "frames.jsonl").open("w", encoding="utf-8") as raw, \
                (directory / csv_name).open("w", newline="", encoding="utf-8-sig") as stream:
            fields = ("curve", "index", "tx1_request_v", "ib_estimated_a", "tx2_request_v",
                      "tx2_code", "tx2_table_v", "vcc_v", "vc_v", "ve_v", "ie_a", "uce_v", "ic_a",
                      "frame_sequences", "simulated", "profile", "measurement_basis") + ADC_DETAILS
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            changed = True
            for channel in (0, 1, 2):
                board.enable(channel, False)
            board.gpio(gpio_mask, gpio_value)
            pause(.05)
            gpio = board.gpio()
            if (gpio["output"] & gpio_mask) != (gpio_value & gpio_mask) or \
                    (gpio["output"] ^ gpio["sense"]) & gpio_mask:
                raise RuntimeError("BJT output GPIO state did not latch")
            for curve_index, tx1_request in enumerate(_base_values(config, beta_mode)):
                if cancel.is_set():
                    raise InterruptedError("Scan cancelled")
                tx1_code, tx1_table = calibration.dac_code(0, tx1_request)
                first_tx2 = scan_values[curve_index][0] if beta_mode else controls_first(scan_values)
                if beta_mode and previous_beta_control is not None and config.tx2_start_increment_v==0:
                    first_tx2 = max(config.tx2_min_v, min(previous_beta_control, config.tx2_stop_v))
                tx2_code, tx2_table = calibration.dac_code(1, first_tx2)
                board.set_code(0, tx1_code)
                if pulsed: state['pulse_actual'] = board.set_pulse(calibration, first_tx2,config.pulse_frequency_hz,config.pulse_duty_percent)
                else: board.set_code(1, tx2_code)
                board.enable(0, True)
                board.enable(1, True)
                pause(config.settle_s)
                curve_points = []
                if beta_mode:
                    candidate=first_tx2
                    for local_index in range(32):
                        point=_measure_point(board,calibration,frontend,config,curve_index,local_index,
                            tx1_request,tx1_table,candidate,frame_sequences,raw,simulated,pause,cancel,qualification,record_point)
                        curve_points.append(point)
                        candidate=_beta_next_control(curve_points,config)
                        if candidate is None:break
                    picked = pick_at_target_uce(curve_points, config.target_uce_v,
                                                config.max_target_error_v,
                                                BETA_ACTIVE_UCE_MIN_V)
                    if picked is not None:
                        previous_beta_control = min(curve_points,key=lambda p:abs(p['uce_v']-config.target_uce_v))['tx2_request_v']
                        beta_rows.append({"curve": curve_index, "tx1_v": tx1_table,
                                          "uce_v": picked["uce_v"],
                                          "ic_a": picked["ic_a"], "pick_method": picked["method"],
                                          "target_error_v": picked["error_v"],
                                          "ib_estimated_a": tx1_table / config.base_resistance_ohm})
                        # ADC diagnostics must remain an actual acquired sample,
                        # not values invented by interpolating the beta result.
                        sample = min((p for p in curve_points if p['uce_v'] > BETA_ACTIVE_UCE_MIN_V and p['ic_a'] > 0),
                                     key=lambda p: abs(p['uce_v']-picked['uce_v']))
                        beta_rows[-1].update({key:sample[key] for key in ADC_DETAILS + ('vcc_v','vc_v','ve_v','tx2_request_v')})
                        beta_rows[-1].update(sample_index=sample['index'],sample_uce_v=sample['uce_v'],sample_ic_a=sample['ic_a'],
                                             adc_basis='nearest_acquired_sample_for_'+picked['method']+'_beta')
                        live_point = dict(beta_rows[-1], beta=beta_rows[-1]["ic_a"] / beta_rows[-1]["ib_estimated_a"], simulated=int(simulated), profile=config.profile, measurement_basis=state["measurement_basis"])
                        emit("point", live_point)
                    else:
                        closest=min(curve_points,key=lambda p:abs(p['uce_v']-config.target_uce_v)) if curve_points else None
                        skipped_beta.append(dict(curve=curve_index,tx1_request_v=tx1_request,
                            nearest_uce_v=closest['uce_v'] if closest else None,
                            reason='No positive-current active-region point within target tolerance'))
                        emit('log','β 第 {} 档未达到目标电压，保留搜索记录，不作为有效 β 点。'.format(curve_index+1))
                else:
                    for local_index, tx2_request in enumerate(scan_values):
                        point = _measure_point(board, calibration, frontend, config, curve_index,
                                               local_index, tx1_request, tx1_table, tx2_request,
                                               frame_sequences, raw, simulated, pause, cancel,
                                               qualification, record_point)
                        curve_points.append(point)
                all_curve_rows.extend(curve_points)
                if pulsed:
                    board.enable(1, False)
                    pause(.1)
                state["points"] = len(all_curve_rows)
                emit("curve", {"index": curve_index, "points": len(curve_points)})
                _display_status(board, [profile.key.upper(), "BETA LINEARITY" if beta_mode else "OUTPUT / EARLY",
                                        "CURVE {}/{}".format(curve_index + 1, len(_base_values(config, beta_mode))),
                                        "POINTS {}".format(state["points"]),
                                        "RX{} {}; RX{} VCC".format(config.collector_channel+1, "VE" if profile.pnp else "VC", config.source_channel+1)], state)
            if beta_mode:
                beta_for_fit = [point for point in beta_rows
                                if point["curve"] >= config.drop_initial_points]
                state["beta_selection"] = dict(search_points=state["points"], selected_points=len(beta_rows),
                    planned_base_points=len(_base_values(config,True)), skipped_points=skipped_beta,
                    fit_candidates=len(beta_for_fit), max_allowed_error_v=config.max_target_error_v,
                    actual_max_error_v=max((p["target_error_v"] for p in beta_rows), default=None))
                if len(beta_for_fit) < 2 or (len(beta_for_fit) >= config.moving_average_window and
                        len(beta_for_fit)-config.moving_average_window+1 < 2):
                    raise ValueError("β有效点不足：搜索{}点，目标电压附近选中{}点，剔除前{}档后剩{}点；目标{:.3f} V，允许误差{:.3f} V。请检查电源搜索范围与基极电流范围。".format(
                        state["points"],len(beta_rows),config.drop_initial_points,len(beta_for_fit),
                        config.target_uce_v,config.max_target_error_v))
                state["beta"] = analyze_beta_linearity(beta_for_fit,
                    base_resistance_ohm=config.base_resistance_ohm,
                    drop_initial=0,
                    moving_average_window=config.moving_average_window)
                state["beta"]["dropped_initial_base_curves"] = config.drop_initial_points
            else:
                state["early_voltage"] = _early_summary(all_curve_rows)
            stream.flush()
            state["status"] = "complete"
    except BaseException as error:
        state["status"] = "cancelled" if isinstance(error, InterruptedError) else "failed"
        state["error"] = "{}: {}".format(type(error).__name__, error)
    finally:
        if changed:
            for channel in (0, 1, 2):
                try:
                    output = board.enable(channel, False)
                    if output.enabled:
                        raise RuntimeError("Output still enabled")
                except Exception as error:
                    state["cleanup_errors"].append("TX{}: {}".format(channel + 1, error))
            try:
                state["final_gpio"] = board.gpio(0x7f, original_gpio["output"])
            except Exception as error:
                state["cleanup_errors"].append("GPIO restore: {}".format(error))
            if state["status"] == "complete" and beta_mode:
                beta = state["beta"]
                final_lines = ["BETA COMPLETE",
                               "LIN {:.2f}%".format(beta["linearity_error_pct"]),
                               "R2 {:.4f}".format(beta["r_squared"]),
                               "BETA {:.1f}".format(beta["beta_mean"]),
                               "OUTPUTS MUTED"]
            elif state["status"] == "complete":
                early = state["early_voltage"].get("mean_va_v")
                va_line = "EARLY VA {:.2f} V".format(early) if early is not None else "EARLY VA N/A"
                final_lines = ["OUTPUT COMPLETE", va_line,
                               "POINTS {}".format(state["points"]), "OUTPUTS MUTED"]
            else:
                final_lines = ["SCAN STOPPED", "POINTS {}".format(state["points"]),
                               "OUTPUTS MUTED"]
            _display_status(board, [profile.key.upper()] + final_lines, state)
        if state["cleanup_errors"]:
            state["status"] = "cleanup_failed"
        if simulated and hasattr(board, "set_measurement_transfer"):
            board.set_measurement_transfer(previous_transfer)
        if beta_mode:
            with (directory/'beta_points.csv').open('w', newline='', encoding='utf-8-sig') as beta_stream:
                writer = csv.DictWriter(beta_stream, fieldnames=('curve','tx1_v','ib_estimated_a',
                    'uce_v','ic_a','beta','pick_method','target_error_v','simulated','profile','measurement_basis') + BETA_DETAILS)
                writer.writeheader()
                writer.writerows(dict(point, beta=point['ic_a']/point['ib_estimated_a'], simulated=int(simulated),
                                      profile=config.profile, measurement_basis=state['measurement_basis']) for point in beta_rows)
        state["finished_at"] = time.time()
        save()
    emit("finished", state)
    return directory, state


def _measure_point(board, calibration, frontend, config, curve, index, tx1_request,
                   tx1_table, tx2_request, sequence_set, raw, simulated, pause, cancel,
                   qualification, record=lambda row:None):
    if cancel.is_set():
        raise InterruptedError("Scan cancelled")
    tx2_code, tx2_table = calibration.dac_code(1, tx2_request)
    base_code=calibration.dac_code(0, tx1_request)[0]
    if getattr(board,"codes",[None])[0]!=base_code:board.set_code(0,base_code)
    pulsed = config.scan_mode == '脉冲'
    if pulsed: board.set_pulse(calibration, tx2_request,config.pulse_frequency_hz,config.pulse_duty_percent)
    else: board.set_code(1, tx2_code)
    pause(max(config.settle_s, 1/config.pulse_frequency_hz+.01) if pulsed else config.settle_s)
    rejected = {}
    frame_values = []
    frame_codes = []
    sequences = []
    for repeat in range(config.frames_per_point * (config.pulse_attempts_per_frame if pulsed else 1)):
        frame = board.capture(sample_stride=256) if pulsed else board.capture()
        raw.write(json.dumps({'curve':curve,'index':index,'repeat':repeat,'frame':frame.as_record()},ensure_ascii=False)+'\n')
        raw.flush()
        if frame.simulated != simulated:
            raise ValueError("Mixed simulated and real data")
        if frame.sequence in sequence_set:
            raise ValueError("Repeated ADC frame sequence")
        sequence_set.add(frame.sequence)
        sequences.append(frame.sequence)
        if not simulated:
            rate = qualification.get("sample_rate_hz", 0)
            physical_rates = frame.adc_sample_rates_hz if pulsed else frame.sample_rates_hz
            if rate <= 0 or len(physical_rates)!=2 or any(abs(actual - rate) > 0.02 * rate for actual in physical_rates):
                raise ValueError("ADC clock differs from calibration qualification")
        for channel in (0, 1):
            codes = frame.codes(channel)
            if frame.overrange(channel) or min(codes) == 0 or max(codes) == 65535:
                raise ValueError("ADC overrange or clipped samples")
        if pulsed:
            from .pulse import plateau, PlateauRejected
            try:
                mean_codes, selection = plateau(frame, calibration, config, tx2_table*frontend.collector_amplifier_gain)
            except PlateauRejected as error:
                rejected[str(error)]=rejected.get(str(error),0)+1
                raw.write(json.dumps(dict(sequence=frame.sequence,pulse_accepted=False,reason=str(error),
                                         diagnostics=error.diagnostics))+'\n')
                raw.flush(); pause(.007+.003*(repeat%5)); continue
            raw.write(json.dumps(dict(sequence=frame.sequence,pulse_accepted=True,selection=selection))+'\n')
            raw.flush()
        else: mean_codes = [statistics.fmean(frame.codes(channel)) for channel in (0, 1)]
        frame_codes.append(mean_codes)
        frame_values.append({channel: calibration.port_v(mean_codes[channel], channel) for channel in (0, 1)})
        pause(0)
        if len(frame_values) == config.frames_per_point: break
    if len(frame_values) != config.frames_per_point:
        raise ValueError('脉冲有效帧不足：TX2={:g} V，已取得 {}/{} 帧；剔除 {}；原始帧已保存'.format(tx2_request,len(frame_values),config.frames_per_point,rejected))
    expected_codes = (calibration.dac_code(0, tx1_request)[0], tx2_code)
    for channel, expected_code in enumerate(expected_codes):
        output = board.output(channel)
        if not output.enabled or output.code != expected_code:
            raise RuntimeError("TX output state changed during scan")
    gpio = board.gpio()
    profile = Profile(config.profile)
    route = profile.route('output')
    if (gpio["output"] & route['mask']) != route['value'] or \
            ((gpio["output"] ^ gpio["sense"]) & route['mask']):
        raise RuntimeError("BJT output GPIO configuration changed during scan")
    collector_port = statistics.fmean(row[config.collector_channel] for row in frame_values)
    source_port = statistics.fmean(row[config.source_channel] for row in frame_values)
    sense_v = collector_port / config.collector_adc_per_v
    vcc_v = source_port / config.source_adc_per_v
    ib = tx1_table / config.base_resistance_ohm
    vc_v, ve_v = (0.0, sense_v) if profile.pnp else (sense_v, 0.0)
    uce_v, ic_a = profile.output_nodes(sense_v, vcc_v, config.collector_resistor_ohm, ib)
    ie_a = (vcc_v-ve_v)/config.collector_resistor_ohm if profile.pnp else ic_a+ib
    row = {"curve": curve, "index": index, "tx1_request_v": tx1_request,
            "ib_estimated_a": ib, "base_resistance_ohm": config.base_resistance_ohm,
            "tx1_table_v": tx1_table,
            "tx2_request_v": tx2_request, "tx2_code": tx2_code, "tx2_table_v": tx2_table,
            "vcc_v": vcc_v, "vc_v": vc_v, "ve_v": ve_v, "ie_a": ie_a, "uce_v": uce_v,
            "ic_a": ic_a, "profile":config.profile,
            "measurement_basis":measurement_basis(simulated,qualification),
            "frame_sequences": ";".join(str(sequence) for sequence in sequences),
            "simulated": int(simulated)}
    row.update(rx1_mean_code=statistics.fmean(p[0] for p in frame_codes),
               scan_mode=config.scan_mode,
               rx2_mean_code=statistics.fmean(p[1] for p in frame_codes),
               rx1_port_v=statistics.fmean(p[0] for p in frame_values),
               rx2_port_v=statistics.fmean(p[1] for p in frame_values),
               vcc_predicted_v=tx2_table*frontend.collector_amplifier_gain)
    record(row)
    return row


def _early_summary(rows):
    summaries = []
    for curve in sorted({row["curve"] for row in rows}):
        points = [row for row in rows if row["curve"] == curve]
        fit = fit_early_voltage(points, 1.0)
        if fit:
            fit["curve"] = curve
            fit["ib_estimated_a"] = points[0]["ib_estimated_a"]
            summaries.append(fit)
    reliable=[item for item in summaries if item['fit_reliable']]
    values = [item["early_va_v"] for item in reliable]
    resistances=[item['ro_ohm'] for item in reliable]
    return {"method": "linear high-UCE tail; candidate start 30..70% of active span",
            "curves": summaries,
            "reliable_curve_count":len(reliable),
            "ro_equation":"ro = dUCE/dIC = 1000/slope_mA_per_v = (VA+UCE_Q)/IC_Q",
            "ro_median_ohm":statistics.median(resistances) if resistances else None,
            "intersection_basis":"independent tail extrapolations; no forced common intersection",
            "mean_va_v": statistics.fmean(values) if values else None,
            "median_va_v": statistics.median(values) if values else None}


def _beta_tx2_values(config, curve_index, calibration):
    start = config.tx2_first_start_v + (curve_index // 2) * config.tx2_start_increment_v
    stop = min(config.tx2_stop_v, 1.8)
    if start > stop:
        raise ValueError("Legacy beta-search start exceeds the calibrated TX2 range")
    return _decimal_range(start, stop, config.tx2_step_v, maximum=1.8)


def _beta_down_values(config, start):
    count = int(math.floor((start - config.tx2_min_v) / config.tx2_step_v + 1e-10))
    return [round(start - (index + 1) * config.tx2_step_v, 10) for index in range(count)
            if start - (index + 1) * config.tx2_step_v >= config.tx2_min_v - 1e-9]


def _base_values(config, beta_mode):
    if beta_mode:
        if config.tx1_segments_v:return segmented_values(config.tx1_segments_v,.02,2)
        return _decimal_range(config.tx1_start_v, config.tx1_stop_v, config.tx1_step_v, maximum=2.0)
    return config.base_control_v


def _decimal_range(start, stop, step, maximum):
    start, stop, step = [Decimal(str(value)) for value in (start, stop, step)]
    if not all(value.is_finite() for value in (start, stop, step)) or step <= 0 or start < 0 or stop < start or stop > Decimal(str(maximum)):
        raise ValueError("Scan interval must be finite, ascending and within the calibrated range")
    count = int((stop - start) / step) + 1
    if count > 2000:
        raise ValueError("Too many scan points")
    result = [float(start + index * step) for index in range(count)]
    if Decimal(str(result[-1])) < stop:
        result.append(float(stop))
    return result


def _validate_source_range(config, calibration, frontend, control_max):
    _, upper = calibration.conversion_range(config.source_channel)
    predicted = control_max * frontend.collector_amplifier_gain * config.source_adc_per_v
    if predicted > upper + 1e-9:
        raise ValueError('规划的 RX{} 电压 {:.3f} V 超出软件输入上限 {:.3f} V；请降低 TX2 扫描上限'.format(
            config.source_channel+1, predicted, upper))


def _validate_common(config, frontend):
    if config.scan_mode=='脉冲':
        from .pulse import validate
        validate(config.pulse_frequency_hz,config.pulse_duty_percent)
        if type(config.pulse_attempts_per_frame) is not int or not 5 <= config.pulse_attempts_per_frame <= 100:
            raise ValueError('每个有效帧的最大尝试次数须为 5～100')
        if not math.isfinite(config.pulse_noise_span_v) or not .005 <= config.pulse_noise_span_v <= .2:
            raise ValueError('脉冲帧内噪声跨度下限须在 0.005～0.2 V 内（换算后的节点电压）')
    if config.scan_mode not in ('步进','脉冲') or (config.scan_mode=='脉冲' and config.profile not in ('npn_big','pnp_big')):
        raise ValueError('脉冲扫描仅支持NPN/PNP大功率输出与β线性精度')
    for value in (config.base_resistance_ohm, config.collector_resistor_ohm,
                  config.collector_adc_per_v):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Analog scale factors and resistances must be finite and positive")
    if not math.isfinite(config.source_adc_per_v) or config.source_adc_per_v <= 0:
        raise ValueError("Enter the measured ADC source-feedback voltage / actual VCC ratio")
    if not math.isfinite(config.settle_s) or not 0 <= config.settle_s <= 60:
        raise ValueError("Invalid analog settling interval")
    if type(config.frames_per_point) is not int or not 2 <= config.frames_per_point <= 20:
        raise ValueError("Use 2..20 independent ADC frames per point")
    _validate_channels(config)


def _validate_channels(config):
    if config.collector_channel not in (0, 1) or config.source_channel not in (0, 1):
        raise ValueError("ADC channel mapping must select RX1 or RX2")
    if config.collector_channel == config.source_channel:
        raise ValueError("Collector and source feedback must use different ADC channels")


def controls_first(values):
    return values[0]


def _display_status(board, lines, state):
    if not hasattr(board, "display_status"):
        return
    try:
        board.display_status(lines)
    except Exception as error:
        state.setdefault("display_errors", []).append(str(error))


def _beta_next_control(points,config):
    """Closed-loop search bounded by both the voltage limits and measured bracket."""
    target=config.target_uce_v;last=points[-1]
    if abs(last['uce_v']-target)<=config.max_target_error_v:return None
    lower=[p for p in points if p['uce_v']<target];upper=[p for p in points if p['uce_v']>=target]
    if lower and upper:
        lo=max(lower,key=lambda p:p['uce_v']);hi=min(upper,key=lambda p:p['uce_v'])
        if hi['uce_v']-lo['uce_v']<=2*config.target_window_v:return None
        ratio=(target-lo['uce_v'])/(hi['uce_v']-lo['uce_v'])
        ratio=max(.1,min(.9,ratio))
        candidate=lo['tx2_request_v']+ratio*(hi['tx2_request_v']-lo['tx2_request_v'])
    else:
        slope=6.0
        if len(points)>1:
            prev=points[-2];dv=last['tx2_request_v']-prev['tx2_request_v']
            if dv:
                measured=(last['uce_v']-prev['uce_v'])/dv
                if .2<=measured<=30:slope=measured
        delta=max(-.1,min(.1,(target-last['uce_v'])/slope))
        candidate=last['tx2_request_v']+delta
    candidate=round(max(config.tx2_min_v,min(config.tx2_stop_v,1.8,candidate)),6)
    if any(abs(candidate-p['tx2_request_v'])<.0001 for p in points):return None
    return candidate
