"""Configurable collector pulses with noise-robust plateau qualification."""
import math
import statistics

FREQUENCY_HZ = 10.0
DUTY_PERCENT = 20.0
STRIDE = 256


def default_noise_span_v(profile):
    # Recorded stable low-voltage NPN plateaus span 20--23 mV; the original
    # 20 mV limit starved the first points. Keep drift/edge limits independent.
    return {'npn_big': .03, 'pnp_big': .04}.get(profile, .02)


def validate(frequency_hz, duty_percent):
    if not math.isfinite(frequency_hz) or not 1 <= frequency_hz <= 50:
        raise ValueError('脉冲频率须在 1～50 Hz 内')
    if not math.isfinite(duty_percent) or not 5 <= duty_percent <= 50:
        raise ValueError('脉冲占空比须在 5～50% 内')
    if round(256*duty_percent/100)/256/frequency_hz < .008:
        raise ValueError('脉冲高电平至少须有 8 ms，以容纳完整采集窗口；请降低频率或增大占空比')


def table(calibration, high_v, dac_rate_hz, frequency_hz=FREQUENCY_HZ, duty_percent=DUTY_PERCENT):
    validate(frequency_hz,duty_percent)
    if not math.isfinite(high_v) or not 0 <= high_v <= 1.8:
        raise ValueError('TX2脉冲高电平须在0～1.8 V内')
    high, actual = calibration.dac_code(1, high_v)
    low, _ = calibration.dac_code(1, 0)
    high_count = round(256 * duty_percent / 100)
    step = round(frequency_hz / dac_rate_hz * 2**32)
    return [high]*high_count + [low]*(256-high_count), dict(
        requested_frequency_hz=frequency_hz, frequency_hz=step*dac_rate_hz/2**32,
        requested_duty_percent=duty_percent, duty_percent=high_count/256*100,
        high_request_v=high_v, high_table_v=actual, low_request_v=0,
        high_code=high, low_code=low, dac_rate_hz=dac_rate_hz)


class PlateauRejected(ValueError):
    def __init__(self, reason, diagnostics=None):
        super().__init__(reason)
        self.diagnostics = diagnostics


def plateau(frame, calibration, config, expected_source_v):
    """No pointwise channel subtraction: the ADC starts are not phase aligned.

    Qualify the whole record using 32-sample block medians and a central 90%
    noise span. Isolated non-clipping spikes must not turn a DC zero record
    into a pulse edge. Trimmed means are used only after qualification.
    """
    source = [calibration.port_v(c, config.source_channel)/config.source_adc_per_v
              for c in frame.codes(config.source_channel)]
    nodes = {config.source_channel: source,
             config.collector_channel: [calibration.port_v(c, config.collector_channel)/config.collector_adc_per_v
                                        for c in frame.codes(config.collector_channel)]}
    threshold = max(.015, expected_source_v*.5)
    tolerance = max(.02, expected_source_v*.03)
    noise_limit = max(config.pulse_noise_span_v, tolerance)
    diagnostics={}
    for channel,values in nodes.items():
        if not all(math.isfinite(v) for v in values):
            raise ValueError('非有限脉冲采样')
        blocks=[statistics.median(values[i:i+32]) for i in range(0,len(values),32)]
        ordered=sorted(values);tail=max(1,len(values)//20)
        noise_span=ordered[-tail-1]-ordered[tail]
        block_span=max(blocks)-min(blocks)
        drift=abs(statistics.median(blocks[:4])-statistics.median(blocks[-4:]))
        diagnostics[channel]=dict(raw_span_v=max(values)-min(values),central_90_span_v=noise_span,
                                  block_median_span_v=block_span,drift_v=drift)
        if channel==config.source_channel:
            if expected_source_v>0 and min(blocks)<=threshold:
                raise PlateauRejected('尚未取得完整高电平帧')
            if expected_source_v==0 and max(abs(b) for b in blocks)>tolerance:
                raise PlateauRejected('零幅度点电源反馈未回到零点范围')
        if block_span > tolerance:
            raise PlateauRejected('脉冲边沿或平台未稳定')
        if drift > tolerance/2:
            raise PlateauRejected('脉冲平台仍在漂移')
        if noise_span > noise_limit:
            raise PlateauRejected('RX{}帧内噪声跨度超限'.format(channel+1),
                dict(channel=channel,noise_span_v=noise_span,noise_limit_v=noise_limit,
                     block_median_span_v=block_span,flatness_limit_v=tolerance,drift_v=drift))
    means=[]
    for ch in (0,1):
        # Legacy output algorithm: more head trim, 10% outlier trim.
        codes=sorted(frame.codes(ch)[359:921])
        means.append(statistics.fmean(codes[56:-56]))
    return means, dict(method='independent_trimmed_plateau_means',
        source_threshold_v=threshold, flatness_limit_v=tolerance,
        qualification='block32_stability_with_separate_central90_noise_limit',
        noise_span_limit_v=noise_limit,channel_diagnostics=diagnostics,
        record_start=359, record_stop=921, retained_samples_per_channel=450,
        starts_aligned=frame.starts_aligned, pointwise_channel_subtraction=False)
