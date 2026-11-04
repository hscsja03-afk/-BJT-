"""Desktop waveform/unit controls translated to the existing board protocol."""
import math
from .desktop_session import waveform

WAVES = {'直流': 'dc', '正弦': 'sine', '方波': 'square', '三角波': 'triangle', 'CSV 波形': 'custom'}
UNITS = ('voltage', 'code')


def output_summary(status):
    """Describe acknowledged per-channel settings, never the unsent editor draft.

    Voltage waveforms may be sent as custom DAC tables. Their display metadata
    retains the user's shape/unit; a table's first code is not its amplitude.
    """
    settings = status.get('output_settings', {})
    names = {value: key for key, value in WAVES.items()}

    def number(value):
        try:
            value = float(value)
            return '{:.6g}'.format(value) if math.isfinite(value) else '—'
        except (TypeError, ValueError):
            return '—'

    lines = []
    for channel, state in enumerate(status.get('outputs', [])):
        parts = ['TX{}：{}'.format(channel+1, '启用' if state['enabled'] else '停止')]
        setting = settings.get(str(channel), settings.get(channel, {}))
        mode = setting.get('mode', '')
        legacy_wave, _, legacy_unit = mode.rpartition('_')
        wave = setting.get('display_waveform', legacy_wave)
        unit = setting.get('display_unit', legacy_unit)
        if wave not in names or unit not in UNITS:
            lines.append(' · '.join(parts+['波形 / 设定未确认']))
            continue
        parts.append(names[wave])
        suffix = 'V' if unit == 'voltage' else '码'
        offset = setting.get('display_offset', setting.get('offset'))
        prefix = '待启动设定' if state.get('code_basis') == 'pending_until_enabled' else '设定'
        if wave == 'dc':
            parts.append('{} {} {}'.format(prefix, number(offset), suffix))
        else:
            frequency = setting.get('frequency_hz')
            if isinstance(frequency, (int, float)) and frequency >= 1000:
                freq = number(frequency/1000)+' kHz'
            else:
                freq = number(frequency)+' Hz'
            peak = setting.get('display_peak', setting.get('peak'))
            # Legacy compensated sine requests stored Vpp, not a raw peak.
            vpp = (setting.get('vpp') if 'display_peak' not in setting and mode == 'sine_voltage'
                   else 2*float(peak) if peak is not None else None)
            parts.extend(['{} {}'.format(prefix, freq),
                          number(vpp)+(' Vpp' if unit == 'voltage' else ' 码峰峰值'),
                          '偏置 {} {}'.format(number(offset), suffix)])
            if wave == 'square':
                parts.append('占空比 {}%'.format(number(setting.get('duty_percent'))))
            if setting.get('sine_amplitude_basis') == 'scaled_reference_unverified':
                parts.append('幅度估算 / 未校准')
            elif setting.get('sine_amplitude_basis') == 'compatible_bitstream_reference_unverified':
                parts.append('当前位流沿用原实测表 · 参考换算')
            elif setting.get('sine_amplitude_basis') == 'scope_verified_warm_point':
                parts.append('该设定预热后已复核 · 当前温态未检测')
            elif setting.get('sine_amplitude_basis') == 'scope_verified_grid':
                parts.append('实测参考节点 · 零点/温态需复核')
            elif setting.get('sine_amplitude_basis') == 'scope_checked_unstable_reference':
                parts.append('幅度实测参考 · 稳定性未通过')
            elif setting.get('sine_amplitude_basis') in ('interpolated_grid_unverified','extrapolated_grid_unverified'):
                parts.append('插值 / 外推估算，未单独校准')
        lines.append(' · '.join(parts))
    return '\n'.join(lines)


def defaults(channel, wave, unit, calibration):
    values = dict(offset='0', peak='0.025', frequency_hz='100000', duty_percent='50', phase_degrees='0')
    if channel==2 and wave=='sine' and unit=='voltage':
        values['peak']='{:g}'.format(calibration.dac['channels'][2]['sine_50mv']['target_vpp_uv']/2e6)
    if unit == 'code':
        values.update(offset=str(calibration.dac['channels'][channel]['zero_code']), peak='1000', frequency_hz='1000')
        if channel == 1 and wave != 'dc': values['offset'] = str(calibration.dac_code(1, .9)[0])
    elif channel == 1 and wave != 'dc':
        values.update(offset='0.9', peak='0.1', frequency_hz='1000')
    if wave == 'dc': values['peak'] = '0'
    return values


def _shape(wave, duty, normalized):
    if wave == 'sine': return [math.sin(2 * math.pi * i / 256) for i in range(256)]
    if wave == 'square':
        if not 1 <= duty <= 99: raise ValueError('占空比范围为 1～99%')
        return [1 if i < round(duty * 256 / 100) else -1 for i in range(256)]
    if wave == 'triangle': return [1 - 4 * abs(i / 256 - .5) for i in range(256)]
    if wave == 'custom':
        if not 2 <= len(normalized) <= 65536 or any(not math.isfinite(v) or not -1 <= v <= 1 for v in normalized):
            raise ValueError('请先导入 2～65536 个 −1～1 的有限 CSV 采样值')
        values = []
        for i in range(256):
            pos = i * len(normalized) / 256; j = int(pos); f = pos-j
            values.append(normalized[j]*(1-f) + normalized[(j+1) % len(normalized)]*f)
        return values
    raise ValueError('未知波形')


def _nominal_tx3_code(volts, calibration):
    p = calibration.dac['channels'][2]
    slope = p['reference_uv'] / 1e6 / p['reference_codes']
    code = p['zero_code'] + volts / slope
    if not math.isfinite(code) or not 0 <= code <= 65535:
        raise ValueError('TX3 电压超出可设定码值范围；请减小偏置或幅度')
    return int(math.floor(code+.5))


def prepare(channel, wave, unit, values, calibration, *, normalized=(), confirmed=False, action='apply'):
    """Return a legacy-compatible request and a preview in the user's unit.

    Voltage waveform ranges are validated in full before constructing any
    request. TX2 uses its positive DC table; TX3 sine retains the existing
    compensated sine path. Other TX3 voltage shapes are explicitly nominal.
    """
    if channel not in (0,1,2) or wave not in WAVES.values() or unit not in UNITS:
        raise ValueError('输出通道、波形或单位无效')
    request = dict(channel=channel, action=action, wiring_confirmed=confirmed)
    if action == 'stop': return dict(request=request, preview=[], basis='')
    if channel == 0 and wave != 'dc': raise ValueError('TX1 当前支持直流输出')
    offset = float(values['offset'])
    peak = float(values['peak']) if wave != 'dc' else 0.0
    frequency = float(values['frequency_hz']) if wave != 'dc' else 0.0
    # The existing compensated sine path has zero phase. Disable that field
    # in the form instead of presenting an editable value the board ignores.
    phase = float(values['phase_degrees']) if wave != 'dc' else 0.0
    duty = float(values['duty_percent']) if wave == 'square' else 50.0
    if not all(math.isfinite(v) for v in (offset,peak,frequency,phase,duty)):
        raise ValueError('设定值必须为有限数值')
    if peak < 0 or not 0 <= phase < 360 or (wave != 'dc' and not 0 < frequency <= 10000000):
        raise ValueError('请检查幅度（≥0）、频率（0～10 MHz）及相位（0～360°）')
    request.update(offset=offset,peak=peak,frequency_hz=frequency,phase_degrees=phase,duty_percent=duty)
    shape = [0.0]*256 if wave == 'dc' else _shape(wave,duty,list(normalized))
    preview = [offset + peak*v for v in shape]
    if channel==1 and unit=='voltage' and wave!='dc' and (min(preview)<0 or max(preview)>1.8):
        raise ValueError('TX2 电压波形的全部电平须在 0～1.8 V 内；请调整偏置或幅度')
    tx2_plan=(calibration.tx2_waveform_parameters(wave,frequency,2*peak,offset)
              if channel==1 and unit=='voltage' and wave in ('sine','square','triangle')
              and (wave!='square' or duty==50) else None)
    basis = '码值设定；接口电压以实际测量为准。'
    if unit == 'code':
        request.update(mode=wave+'_code',samples=list(normalized))
        if channel == 0 and (not offset.is_integer() or not 0 <= offset <= 4095):
            raise ValueError('TX1 码值须为 0～4095 的整数')
        preview,_,_ = waveform(request)
    elif wave == 'dc' and channel in (0,1):
        try: calibration.dac_code(channel,offset)
        except ValueError:
            raise ValueError('TX1 直流范围为 0～2.499 V' if channel == 0 else 'TX2 直流电压范围为 0～1.8 V') from None
        request['mode'] = 'dc_voltage'
        basis = 'TX1 按标称系数换算。' if channel == 0 else 'TX2 使用本板直流校准表。'
    elif tx2_plan is not None:
        request.update(mode=wave+'_code',offset=tx2_plan['zero_code'],peak=tx2_plan['peak_codes'],
                       phase_degrees=(phase+180)%360,display_phase_degrees=phase,
                       tx2_waveform_calibration_id=tx2_plan['calibration_id'],
                       sine_amplitude_basis=tx2_plan['amplitude_basis'])
        waveform(request)
        basis='TX2 采用交流波形参考表；直流设定仍使用原直流表。'
        if tx2_plan['amplitude_basis']=='interpolated_grid_unverified':
            basis+=' 当前频率/幅度为插值估算。'
        if not tx2_plan.get('amplitude_stability_qualified',True):
            basis+=' 固定码值稳定性未通过。'
    elif channel == 2 and wave in ('sine','square','triangle') and calibration.tx3_waveforms:
        if offset != 0 or (wave=='square' and duty!=50):
            raise ValueError('TX3 多点波形表支持零偏置，方波占空比为50%')
        plan=calibration.waveform_parameters(wave,frequency,2*peak)
        request.update(mode=wave+'_code',offset=plan['zero_code'],peak=plan['peak_codes'],
                       waveform_calibration_id=plan['calibration_id'],sine_amplitude_basis=plan['amplitude_basis'])
        waveform(request)
        basis=('TX3 当前设定采用原标定表的实测参考节点。' if plan['amplitude_basis']=='scope_verified_grid' else
               'TX3 当前频率/幅度为本次实测参考。' if plan['amplitude_basis']=='scope_checked_unstable_reference' else
               'TX3 当前设定由多点表'+('外推' if plan['amplitude_basis']=='extrapolated_grid_unverified' else '插值')+'估算，未单独校准。')
        basis+='\n仅本次接线、负载和温态；偏置与长期稳定性需复核。'
        if not plan.get('amplitude_stability_qualified',True):
            basis+='\n固定码值幅度稳定窗口未通过，当前表仅作实测参考。'
        if plan.get('offset_validation_status')=='drift_observed':
            basis+='\n后续复测出现零点漂移，不能保证直流中心在±5 mV内。'
    elif channel == 2 and wave == 'sine':
        if offset != 0: raise ValueError('TX3 电压正弦目前支持零偏置；请将偏置设为 0 V')
        if phase != 0: raise ValueError('TX3 电压正弦目前支持 0° 相位')
        if not 10000 <= frequency <= 6000000 or peak <= 0:
            raise ValueError('TX3 电压正弦：频率 10 kHz～6 MHz，峰值幅度须大于 0 V')
        calibration.sine_samples(frequency,2*peak)
        plan = calibration.sine_parameters(frequency,2*peak)
        request.update(mode='sine_voltage',vpp=2*peak,sine_amplitude_basis=plan['amplitude_basis'])
        reference_mv=plan['reference_vpp']*1000
        if plan['amplitude_basis']=='scope_verified_warm_point':
            basis = 'TX3 {:g} kHz / {:g} mVpp：已完成预热后单点校准复核。'.format(frequency/1000,2*peak*1000)
            basis += '\n校准条件：该频率、幅度及预热状态。冷机或连续运行时请测量实际输出。'
        else:
            basis = ('TX3 使用本板 {:g} mVpp 正弦幅度补偿。'.format(reference_mv) if plan['amplitude_basis']=='scope_verified_reference'
                     else 'TX3 当前频率/幅度按参考表比例估算。')
            warm=plan.get('warm_reference')
            if warm:
                basis+='\n已复核点仅为 {:g} kHz / {:g} mVpp（预热后），不涵盖当前设置。'.format(warm['frequency_hz']/1000,warm['amplitude_vpp_v']*1000)
        basis += '\n当前码值允许峰值上限约 {:.3f} V；接口电压以实测为准。'.format(plan['max_vpp']/2)
        if plan.get('offset_validation_status')=='drift_observed':
            basis+='\n预热记录包含幅度及零点漂移，输出参数按实际温态测量。'
    else:
        if channel == 1:
            if min(preview) < 0 or max(preview) > 1.8:
                raise ValueError('TX2 电压波形的全部电平须在 0～1.8 V 内；请调整偏置或幅度')
            codes = [calibration.dac_code(1,v)[0] for v in preview]
            basis = 'TX2 按直流校准表换算波形；交流幅度响应未校准。'
        else:
            codes = [_nominal_tx3_code(v,calibration) for v in preview]
            basis = 'TX3 此波形按标称电压系数估算。'
        if wave == 'dc': request.update(mode='dc_code',offset=codes[0])
        else:
            # Exact reconstruction of integer DAC samples via the existing
            # normalized CSV path; no new board protocol or driver required.
            request.update(mode='custom_code',offset=32767.5,peak=32767.5,
                           samples=[(v-32767.5)/32767.5 for v in codes])
            assert waveform(request)[0] == codes
    if channel==1 and unit=='voltage':
        active_rate=calibration.dac.get('operating_dac_sample_rate_hz')
        reference_rate=calibration.dac['channels'][1].get('dac_sample_rate_hz')
        if active_rate and reference_rate and active_rate!=reference_rate:
            basis+='\nTX2 沿用 {:g} MHz 下的直流表；{:g} MHz 下为参考换算。'.format(reference_rate/1e6,active_rate/1e6)
    request.update(display_waveform=wave,display_unit=unit,display_offset=offset,display_peak=peak,voltage_basis=basis)
    shift = int(round(phase/360*256)) % 256
    preview = preview[shift:]+preview[:shift]
    return dict(request=request,preview=preview,basis=basis,frequency_hz=frequency,offset=offset,peak=peak)
