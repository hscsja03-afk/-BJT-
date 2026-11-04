"""NPN input curves, raw evidence, cancellation and owned-resource cleanup."""
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
from .profiles import Profile, assumptions
from .sweep import segmented_values


@dataclass(frozen=True)
class ScanConfig:
    profile: str = 'npn_small'
    collector_channel: int = 1
    base_channel: int = 0
    base_adc_per_v: float = 0.25
    ve_conversion_mode: str = '实测表优先'
    tx1_start_v: float = .02
    tx1_stop_v: float = 2.0
    tx1_step_v: float = .1
    tx1_fine_stop_v: float = .4
    tx1_fine_step_v: float = .05
    tx1_segments_v: str = ''
    uce_values_v: tuple = (0.5,)
    settle_s: float = .02
    curve_settle_s: float = .15
    frames_per_point: int = 2
    discard_frames: int = 1
    frame_gap_s: float = .01
    adaptive_settle_v: float = .02
    max_node_drift_v: float = .05
    uce_tolerance_v: float = .03
    relay_active_level: int = 1

    def validate(self, calibration, frontend):
        profile=Profile(self.profile)
        if self.ve_conversion_mode not in ('实测表优先', '线性比例'):
            raise ValueError('VE 换算请选择实测表优先或线性比例')
        if profile.pnp and self.ve_conversion_mode=='实测表优先' and not calibration.ve_conversion(self.profile,self.collector_channel):
            raise ValueError('当前档位 / RX 通道没有匹配的 VE 实测表；请检查通道，或明确选择线性比例')
        base_ch,bias_ch=(1,0) if profile.pnp else (0,1)
        if (type(self.collector_channel) is not int or type(self.base_channel) is not int
                or {self.collector_channel, self.base_channel} != {0, 1}):
            raise ValueError('集电极与基极反馈必须分别选择 RX1、RX2')
        if not math.isfinite(self.base_adc_per_v) or self.base_adc_per_v <= 0:
            raise ValueError('基极反馈比例必须为正的有限数值')
        if type(self.relay_active_level) is not int or self.relay_active_level not in (0, 1):
            raise ValueError("Relay active level must be 0 or 1")
        if self.tx1_segments_v:
            values=segmented_values(self.tx1_segments_v,.02,2)
        else:
            start, stop, step = [Decimal(str(v)) for v in (self.tx1_start_v, self.tx1_stop_v, self.tx1_step_v)]
            if not all(v.is_finite() for v in (start, stop, step)) or not Decimal('.02') <= start <= stop <= 2 or step <= 0:
                raise ValueError("TX1 sweep must be within .02..2 V with a positive step")
            fine_stop, fine_step = Decimal(str(self.tx1_fine_stop_v)), Decimal(str(self.tx1_fine_step_v))
            if not fine_stop.is_finite() or not fine_step.is_finite() or not 0 <= fine_stop <= 2 or fine_step <= 0:
                raise ValueError('Invalid low-current fine sweep range/step')
            positions = [start]
            while positions[-1] < stop:
                current = positions[-1]
                fine = fine_step < step and current < fine_stop
                increment = fine_step if fine else step
                boundary = min(stop, fine_stop) if fine else stop
                positions.append(min(current + increment, boundary))
                if len(positions) > 2000: raise ValueError('Too many sweep points')
            values = [float(value) for value in positions]
        codes = [calibration.dac_code(base_ch, v)[0] for v in values]
        if len(values) > 2000 or len(codes) != len(set(codes)):
            raise ValueError("Sweep repeats quantized codes or exceeds 2000 points")
        if not 1 <= len(self.uce_values_v) <= 20: raise ValueError("Expected 1..20 collector biases")
        for v in self.uce_values_v:
            calibration.dac_code(bias_ch, frontend.tx2_for_uce(v))
            port = v * frontend.rx1_per_vc
            low, high = calibration.conversion_range(self.collector_channel)
            if not low <= port <= high:
                raise ValueError("Collector feedback outside connector calibration range")
        for v in (self.settle_s, self.curve_settle_s, self.frame_gap_s):
            if not math.isfinite(v) or not 0 <= v <= 60: raise ValueError("Invalid settling interval")
        for v in (self.max_node_drift_v, self.uce_tolerance_v):
            if not math.isfinite(v) or not 0 < v <= 1: raise ValueError("Invalid drift/tolerance threshold")
        if not math.isfinite(self.adaptive_settle_v) or not 0 <= self.adaptive_settle_v <= 1:
            raise ValueError('Adaptive settling threshold must be within 0..1 V')
        if type(self.frames_per_point) is not int or not 2 <= self.frames_per_point <= 20:
            raise ValueError("Use 2..20 independent frames per point")
        if type(self.discard_frames) is not int or not 0 <= self.discard_frames <= 5:
            raise ValueError("Invalid discarded frame count")
        return values


class NodeDriftError(ValueError):
    def __init__(self, collector_channel, base_channel, node_drift, base_drift, limit):
        self.details = dict(collector_channel=collector_channel, base_channel=base_channel,
                            node_drift_v=node_drift, base_drift_v=base_drift, limit_v=limit)
        super().__init__('节点尚未稳定：RX{} 的 VC/VE 帧间变化 {:.4f} V，'
                         'RX{} 的 VB 帧间变化 {:.4f} V；允许上限 {:.4f} V'.format(
                             collector_channel+1,node_drift,base_channel+1,base_drift,limit))


NODE_SETTLE_RETRY_DELAYS = (.2, .4, .8, 1.6)


def reduce_frames(frames, calibration, frontend, max_drift, collector_channel=1, base_channel=0, base_adc_per_v=.25, ve_profile=None):
    if len(frames) < 2 or len({f.sequence for f in frames}) != len(frames):
        raise ValueError("Need distinct independent ADC frames")
    means = [[], []]
    code_means = [[], []]
    for frame in frames:
        for channel in (0, 1):
            codes = frame.codes(channel)
            if frame.overrange(channel) or min(codes) == 0 or max(codes) == 65535:
                raise ValueError("ADC overrange or clipped samples")
            mean_code = statistics.fmean(codes)
            code_means[channel].append(mean_code)
            means[channel].append(calibration.port_v(mean_code, channel))
    drift = [max(v)-min(v) for v in means]
    convert = (lambda v: calibration.ve_from_port(v, ve_profile, collector_channel, frontend.rx1_per_vc)) if ve_profile else frontend.vc_from_rx1
    nodes = [convert(v) for v in means[collector_channel]]
    node_drift = max(nodes)-min(nodes)
    base_drift = drift[base_channel]/base_adc_per_v
    if max(node_drift, base_drift) > max_drift:
        raise NodeDriftError(collector_channel, base_channel, node_drift, base_drift, max_drift)
    ports = [statistics.fmean(v) for v in means]
    return dict(rx1_port_v=ports[0], rx2_port_v=ports[1],
                rx1_mean_code=statistics.fmean(code_means[0]), rx2_mean_code=statistics.fmean(code_means[1]),
                collector_port_v=ports[collector_channel], base_port_v=ports[base_channel],
                uce_v=convert(ports[collector_channel]), ube_v=ports[base_channel]/base_adc_per_v,
                rx1_port_drift_v=drift[0], uce_drift_v=node_drift, ube_drift_v=base_drift)


FIELDS = ('curve', 'index', 'uce_target_v', 'uce_v', 'ube_v', 'rx1_port_v',
          'tx1_request_v', 'tx1_code', 'tx1_nominal_v', 'ib_estimated_a',
          'tx2_request_v', 'tx2_code', 'tx2_table_v', 'rx1_per_vc',
          'rx1_port_drift_v', 'uce_drift_v', 'ube_drift_v', 'frame_sequences', 'simulated',
          'profile', 'vb_v', 'vc_v', 've_v', 'emitter_basis', 'measurement_basis',
          'rx2_port_v', 'collector_port_v', 'base_port_v', 'collector_channel', 'base_channel', 'base_adc_per_v', 've_conversion_basis')
FIELDS += ('base_control_tx','bias_control_tx','base_control_request_v','settle_mode', 'actual_settle_s', 'frames_used', 'actual_frame_gap_s', 'vcc_v', 'settle_retries', 'extra_settle_s')
FIELDS += ('rx1_mean_code', 'rx2_mean_code', 'vcc_predicted_v', 'base_resistance_ohm')


def point_timing(config, previous, previous_change):
    """Keep the proven acquisition timing while the fixture nodes are changing."""
    conservative = config.adaptive_settle_v > 0 and (previous is None or previous_change is None
        or previous_change > config.adaptive_settle_v
        or max(v for v in (previous['ube_drift_v'], previous['uce_drift_v']) if v is not None) > min(.005, config.max_node_drift_v))
    if conservative:
        return max(.05, config.settle_s), max(3, config.frames_per_point), max(.05, config.frame_gap_s), 'settling'
    return config.settle_s, config.frames_per_point, config.frame_gap_s, 'balanced'


def validate_measurement_board(board, calibration, frontend, qualification):
    simulated = bool(getattr(board, 'simulated', False))
    if not simulated:
        if qualification and qualification.get('status') == 'reference_only':
            if qualification.get('explicit_reference_mode') is not True:
                raise ValueError('Reference conversion must be explicitly selected')
            if not board.adc_ready: raise RuntimeError('Initialize ADC before reference scans')
            return False
        if not qualification or qualification.get('status') != 'validated':
            raise ValueError("New hardware requires a qualified calibration record before calibrated scans")
        for key in ('bit_sha256', 'hwh_sha256'):
            if not board.identity.get(key) or qualification.get(key) != board.identity[key]:
                raise ValueError("Calibration qualification does not match the active overlay")
        hashes = {k: v['sha256'] for k, v in calibration.manifest().items()}
        if qualification.get('calibration_sha256') != hashes:
            raise ValueError("Calibration qualification does not match profiles")
        if qualification.get('frontend') != asdict(frontend):
            raise ValueError("Frontend transfer changed after qualification")
    if not board.adc_ready: raise RuntimeError("Initialize and digitally verify ADC before scanning")
    if not simulated and board.identity.get('transport') == 'baremetal_uart':
        if qualification.get('transport') != 'baremetal_uart':
            raise ValueError("Baremetal measurements require a new baremetal calibration qualification")
        if not board.identity.get('firmware_sha256') or qualification.get('firmware_sha256') != board.identity['firmware_sha256']:
            raise ValueError("Calibration qualification does not match the baremetal firmware")
    return simulated


def measurement_basis(simulated, qualification):
    return 'simulation' if simulated else ('reference_parameters_unverified' if
        qualification and qualification.get('status')=='reference_only' else 'qualified_measurement')


def run_scan(board, calibration, frontend, config, output_root, cancel=None,
             qualification=None, emit=lambda event, value: None):
    values = config.validate(calibration, frontend)
    cancel = cancel or threading.Event()
    simulated = validate_measurement_board(board, calibration, frontend, qualification)
    profile = Profile(config.profile)
    capture_channels = (0, 1)
    route = profile.route('input')
    base_ch,bias_ch=(1,0) if profile.pnp else (0,1)
    max_idle = getattr(board, 'max_idle_s', None)
    if max_idle is not None and max(config.settle_s, config.curve_settle_s, config.frame_gap_s) >= max_idle:
        raise ValueError("Settling interval exceeds the baremetal communications watchdog budget")
    initial_outputs = [board.output(ch) for ch in (0, 1, 2)]
    if any(s.enabled for s in initial_outputs): raise RuntimeError("All outputs must be idle before this scan")
    original_gpio = board.gpio()
    if (original_gpio['output'] ^ original_gpio['sense']) & 0x7f:
        raise RuntimeError("GPIO pin feedback is inconsistent before scanning")
    if cancel.is_set(): raise InterruptedError("Scan cancelled before starting")
    from .result_paths import create_run
    directory = create_run(output_root, config.profile, 'input')
    state = dict(schema_version=1, measurement='input', status='running', simulated=simulated, config=asdict(config),
                 frontend=asdict(frontend), calibration=calibration.manifest(), qualification=qualification,
                 board_identity=dict(board.identity), initial_outputs=[asdict(v) for v in initial_outputs],
                 initial_gpio=original_gpio, started_at=time.time(), points=0, cleanup_errors=[],
                 current_basis='TX{} control / equivalent resistance; not measured current'.format(base_ch+1),
                 input_output_roles={'base_current_tx':base_ch+1,'bias_amplifier_tx':bias_ch+1},
                 captured_channels=capture_channels,
                 input_voltage_basis='measured_VE_minus_measured_VB' if profile.pnp else 'measured_VB',
                 bias_control_basis='VCC / collector_amplifier_gain; VE measured independently' if profile.pnp else 'measured_VC_feedback',
                 capture_trigger='shared_dual_ADC_trigger_selected_RAM_readout',
                 starts_aligned=False,
                 gpio_pin_by_bit={0: 87, 1: 85, 2: 83, 3: 81, 4: 79, 5: 77, 6: 48},
                 measurement_gpio=route, profile=config.profile,
                 measurement_basis=measurement_basis(simulated, qualification),
                 parameter_basis=assumptions(config.profile, 'input'))
    if profile.pnp and config.ve_conversion_mode == '实测表优先':
        state['ve_feedback_conversion'] = calibration.ve_conversion(config.profile, config.collector_channel)
    def save():
        temp = directory/'run.json.tmp'
        temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(directory/'run.json')
    def pause(seconds):
        if cancel.wait(seconds): raise InterruptedError("Scan cancelled")
    expected_codes = [None, None]
    changed = False
    seen = set()
    save()
    previous_transfer = None
    if simulated and hasattr(board, 'set_measurement_transfer'):
        previous_transfer = board.set_measurement_transfer({'profile':config.profile,
            'collector_channel':config.collector_channel, 'base_channel':config.base_channel,
            'base_adc_per_v':config.base_adc_per_v,
            've_table':bool(state.get('ve_feedback_conversion')),
            'base_resistance_ohm':frontend.base_equivalent_resistance_ohm, 'measurement':'input'})
    _display_status(board, [profile.key.upper(), "INPUT CHARACTERISTIC", "STARTING"], state)
    try:
        with (directory/'frames.jsonl').open('w', encoding='utf-8') as raw, (directory/'points.csv').open('w', newline='', encoding='utf-8-sig') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=FIELDS); writer.writeheader()
            changed = True
            for ch in (0, 1):
                board.enable(ch, False)
                expected_codes[ch] = calibration.dac_code(ch, 0)[0]
                board.set_code(ch, expected_codes[ch])
            board.enable(2, False)
            gpio_mask, gpio_value = route['mask'], route['value']
            board.gpio(gpio_mask, gpio_value)
            pause(.05)
            board.enable(1, True); board.enable(0, True)
            for curve, uce_target in enumerate(config.uce_values_v):
                previous_row, previous_change = None, None
                expected_codes[base_ch] = calibration.dac_code(base_ch, 0)[0]
                board.set_code(base_ch, expected_codes[base_ch])
                tx2_request = frontend.tx2_for_uce(uce_target)
                tx2_code, tx2_table = calibration.dac_code(bias_ch, tx2_request)
                board.set_code(bias_ch, tx2_code); expected_codes[bias_ch] = tx2_code
                pause(config.curve_settle_s)
                for index, requested in enumerate(values):
                    settle, frame_count, gap, settle_mode = point_timing(config, previous_row, previous_change)
                    code, nominal = calibration.dac_code(base_ch, requested)
                    board.set_code(base_ch, code); expected_codes[base_ch] = code
                    pause(settle)
                    previous_bias_error = None
                    for bias_attempt in range(8):
                        extra_settle = 0.0
                        for settle_attempt in range(len(NODE_SETTLE_RETRY_DELAYS)+1):
                            frames = []
                            for repeat in range(config.discard_frames+frame_count):
                                pause(0)
                                frame = board.capture()
                                raw.write(json.dumps(dict(curve=curve, index=index, repeat=repeat, bias_attempt=bias_attempt,
                                    settle_attempt=settle_attempt,
                                    discarded=repeat < config.discard_frames, frame=frame.as_record()))+'\n'); raw.flush()
                                if frame.simulated != simulated: raise ValueError("Mixed simulated and real data")
                                if frame.sequence in seen: raise ValueError("Repeated ADC frame sequence")
                                seen.add(frame.sequence)
                                if not simulated:
                                    rate = qualification.get('sample_rate_hz', 0)
                                    if rate <= 0 or any(abs(frame.sample_rates_hz[ch]-rate) > .02*rate for ch in capture_channels):
                                        raise ValueError("ADC clock differs from calibration qualification")
                                if repeat >= config.discard_frames: frames.append(frame)
                                if repeat + 1 < config.discard_frames + frame_count:
                                    pause(gap)
                            for ch in (0, 1):
                                s = board.output(ch)
                                if not s.enabled or s.code != expected_codes[ch]: raise RuntimeError("Output state changed during scan")
                            gpio = board.gpio()
                            if (gpio['output'] & gpio_mask) != gpio_value or ((gpio['output'] ^ gpio['sense']) & gpio_mask):
                                raise RuntimeError("Input-test GPIO configuration changed during scan")
                            try:
                                row = reduce_frames(frames, calibration, frontend, config.max_node_drift_v,
                                                    config.collector_channel, config.base_channel, config.base_adc_per_v,
                                                    config.profile if state.get('ve_feedback_conversion') else None)
                            except NodeDriftError as error:
                                exhausted = settle_attempt == len(NODE_SETTLE_RETRY_DELAYS)
                                wait = 0.0 if exhausted else NODE_SETTLE_RETRY_DELAYS[settle_attempt]
                                record = dict(error.details,curve=curve,index=index,bias_attempt=bias_attempt,
                                              settle_attempt=settle_attempt,wait_s=wait,
                                              frame_sequences=[frame.sequence for frame in frames])
                                state.setdefault('node_settle_attempts',[]).append(record)
                                if exhausted:
                                    state['rejected_node_drift'] = record
                                    save()
                                    raise
                                save()
                                emit('log','第 {} 条曲线第 {} 点：{}；等待 {:g} s 后重采（{}/{}）。'.format(
                                    curve+1,index+1,error,wait,settle_attempt+1,len(NODE_SETTLE_RETRY_DELAYS)))
                                pause(wait)
                                extra_settle += wait
                            else:
                                break
                        row.update(settle_retries=settle_attempt,extra_settle_s=extra_settle)
                        sense, vb = row['uce_v'], row['ube_v']
                        ve_table = state.get('ve_feedback_conversion')
                        if ve_table:
                            in_table = ve_table['points'][0]['adc_v'] <= row['collector_port_v'] <= ve_table['points'][-1]['adc_v']
                            row['ve_conversion_basis'] = 'scope_table_interpolation' if in_table else 'scope_table_endpoint_extrapolation'
                        vc, ve = (0.0, sense) if profile.pnp else (sense, 0.0)
                        row.update(vc_v=vc, vb_v=vb, ve_v=ve,
                                   uce_v=ve-vc if profile.pnp else vc,
                                   ube_v=ve-vb if profile.pnp else vb,
                                   vcc_v=uce_target if profile.pnp else None,
                                   emitter_basis='ADC_measured_RX{}'.format(config.collector_channel+1) if profile.pnp else 'ground_by_fixture_topology',
                                   profile=config.profile, measurement_basis=state['measurement_basis'])
                        row.update(curve=curve, index=index, uce_target_v=uce_target,
                            tx1_request_v=tx2_request if profile.pnp else requested, tx1_code=tx2_code if profile.pnp else code, tx1_nominal_v=tx2_table if profile.pnp else nominal,
                            ib_estimated_a=frontend.ib_estimate(nominal), tx2_request_v=requested if profile.pnp else tx2_request,
                            base_resistance_ohm=frontend.base_equivalent_resistance_ohm,
                            vcc_predicted_v=tx2_table*frontend.collector_amplifier_gain,
                            tx2_code=code if profile.pnp else tx2_code, tx2_table_v=nominal if profile.pnp else tx2_table,
                            base_control_tx=base_ch+1,bias_control_tx=bias_ch+1,base_control_request_v=requested, rx1_per_vc=frontend.rx1_per_vc,
                            frame_sequences=';'.join(str(f.sequence) for f in frames), simulated=int(simulated),
                            collector_channel=config.collector_channel, base_channel=config.base_channel,
                            base_adc_per_v=config.base_adc_per_v, settle_mode=settle_mode,
                            actual_settle_s=settle, frames_used=frame_count, actual_frame_gap_s=gap)
                        if not profile.pnp and abs(row['uce_v']-uce_target) > config.uce_tolerance_v:
                            # Bounded negative feedback compensates fixture DC offset/load drop.
                            # Do not change calibration or relax the requested tolerance.
                            if bias_attempt < 7:
                                error = uce_target-row['uce_v']
                                step = max(-.05,min(.05,.8*error/frontend.collector_amplifier_gain))
                                maximum = min(1.8,frontend.max_uce_v/frontend.collector_amplifier_gain)
                                candidate = max(0.0,min(maximum,tx2_request+step))
                                candidate_code,candidate_table = calibration.dac_code(bias_ch,candidate)
                                previous_error = previous_bias_error
                                responding = previous_error is None or abs(error) <= previous_error*1.5+config.uce_tolerance_v
                                if candidate_code != tx2_code and responding:
                                    state.setdefault('bias_adjustments',[]).append(dict(
                                        curve=curve,index=index,attempt=bias_attempt,
                                        target_v=uce_target,measured_v=row['uce_v'],
                                        tx2_before_v=tx2_request,tx2_after_v=candidate,
                                        collector_channel=config.collector_channel))
                                    board.set_code(bias_ch,candidate_code)
                                    tx2_request,tx2_code,tx2_table = candidate,candidate_code,candidate_table
                                    expected_codes[bias_ch] = candidate_code
                                    previous_bias_error = abs(error)
                                    pause(max(.05,settle))
                                    continue
                            state['rejected_point'] = dict(row,
                                bias_error_v=row['uce_v']-uce_target,
                                tolerance_v=config.uce_tolerance_v)
                            raise ValueError(
                                '偏置超差：目标 {}={:.4f} V，实测={:.4f} V，'
                                '偏差={:+.4f} V，允许 ±{:.4f} V；'
                                'RX{} 节点反馈={:.5f} V，偏置激励设定={:.5f} V。'
                                '请检查反馈、偏置驱动及接线。'.format(
                                    profile.voltage_axis,uce_target,row['uce_v'],row['uce_v']-uce_target,
                                    config.uce_tolerance_v,config.collector_channel+1,row['collector_port_v'],tx2_request))
                        if not profile.pnp and row['ube_v'] < -.05:
                            state['rejected_point'] = dict(row)
                            raise ValueError('NPN 基极反馈异常：RX{} 接口={:.4f} V，按反馈比例 {:.4g} 换算 UBE={:.4f} V；'
                                             '请核对 B/E 接线及基极反馈是否反相或悬空。'.format(
                                                 config.base_channel+1,row['base_port_v'],config.base_adc_per_v,row['ube_v']))
                        break
                    writer.writerow(row); csv_file.flush()
                    previous_change = (max(abs(row[k]-previous_row[k]) for k in ('ube_v','uce_v'))
                                       if previous_row is not None else None)
                    previous_row = row
                    state['points'] += 1
                    if index % 10 == 9 or index == len(values) - 1:
                        _display_status(board, [profile.key.upper(), "INPUT CHARACTERISTIC",
                            "CURVE {}/{}".format(curve + 1, len(config.uce_values_v)),
                            "TX{} {:.2f} V".format(base_ch+1,requested),
                            "POINT {}/{}".format(index + 1, len(values))], state)
                    emit('point', row)
            state['status'] = 'complete'
    except BaseException as error:
        state['status'] = 'cancelled' if isinstance(error, InterruptedError) else 'failed'
        state['error'] = f'{type(error).__name__}: {error}'
    finally:
        if changed:
            for ch in (0, 1, 2):
                try:
                    s = board.enable(ch, False)
                    if s.enabled: raise RuntimeError("Output still enabled")
                except Exception as error: state['cleanup_errors'].append(f'TX{ch+1}: {error}')
            try:
                final = board.gpio(0x7f, original_gpio['output'])
                state['final_gpio'] = final
            except Exception as error: state['cleanup_errors'].append(f'GPIO restore: {error}')
        if state['cleanup_errors']: state['status'] = 'cleanup_failed'
        if simulated and hasattr(board, 'set_measurement_transfer'):
            board.set_measurement_transfer(previous_transfer)
        final_lines = ([profile.key.upper(), "INPUT COMPLETE", "POINTS {}".format(state['points']),
                        "OUTPUTS MUTED"] if state['status'] == 'complete' else
                       [profile.key.upper(), "INPUT STOPPED", "POINTS {}".format(state['points']),
                        "OUTPUTS MUTED"])
        _display_status(board, final_lines, state)
        state['finished_at'] = time.time(); save()
    emit('finished', state)
    return directory, state


def _display_status(board, lines, state):
    if not hasattr(board, 'display_status'):
        return
    try:
        board.display_status(lines)
    except Exception as error:
        state.setdefault('display_errors', []).append(str(error))
