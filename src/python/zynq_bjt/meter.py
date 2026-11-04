"""DC and RMS from contiguous ADC-domain statistics; no output controls."""
import math


def readings(capture, calibration, sample_rates):
    result = []
    for ch, raw in enumerate(capture['channels']):
        profile = (calibration.rx1, calibration.rx2)[ch]
        row = dict(dc_v=None, true_rms_v=None, ac_rms_v=None, error=None,
                   voltage_basis='dc_profile_rms_conversion', fault_count=raw['fault_count'])
        try:
            if raw['fault_count']:
                raise ValueError('输入过量程或削顶')
            if abs(sample_rates[ch]/profile['sample_rate_hz']-1) > .02:
                raise ValueError('采样时钟与接口校准不匹配')
            if not math.isfinite(raw['rms_code']) or raw['rms_code'] < 0:
                raise ValueError('无效 RMS 统计')
            dc = calibration.port_v(raw['mean_code'], ch)
            ac = raw['rms_code']*abs(profile['slope_nv_per_code'])/1e9
            row.update(dc_v=dc, true_rms_v=math.hypot(dc, ac), ac_rms_v=ac)
            if not profile['valid_min_v'] <= dc <= profile['valid_max_v']:
                row['voltage_basis'] = 'dc_linear_extrapolation_rms_conversion'
        except ValueError as error:
            row['error'] = str(error)
        result.append(row)
    return dict(channels=result, completed_at=capture['completed_at'],
                sample_count=capture['sample_count'], sample_rates_hz=list(sample_rates),
                window_ms=[capture['sample_count']/r*1000 for r in sample_rates],
                simulated=capture.get('simulated', False), statistics=capture)
