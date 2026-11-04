"""Keep connector calibration, external analog transfer, and setpoints separate."""
from dataclasses import dataclass, asdict
from pathlib import Path
import bisect
import hashlib
import json
import math


@dataclass(frozen=True)
class Frontend:
    # Legacy serialized name: collector attenuation; channel selected by scan config.
    rx1_per_vc: float = 0.206
    collector_amplifier_gain: float = 6.0
    base_equivalent_resistance_ohm: float = 200000.0
    max_uce_v: float = 5.0
    transfer_basis: str = "legacy_user_confirmed_nominal_not_new_calibration"

    def __post_init__(self):
        for value in (self.rx1_per_vc, self.collector_amplifier_gain,
                      self.base_equivalent_resistance_ohm, self.max_uce_v):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Frontend coefficients must be finite and positive")

    def vc_from_rx1(self, connector_v):
        return connector_v / self.rx1_per_vc

    def tx2_for_uce(self, requested_uce):
        if not math.isfinite(requested_uce) or not 0 <= requested_uce <= self.max_uce_v:
            raise ValueError("UCE outside configured planning limits")
        return requested_uce / self.collector_amplifier_gain

    def ib_estimate(self, tx1_nominal_v):
        return tx1_nominal_v / self.base_equivalent_resistance_ohm

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))


class Calibration:
    """Historical profiles remain historical; qualification is not inferred.

    RX1=ADC B, RX2=ADC A. Archived DC profiles were collected at 125 MSPS.
    A new bitstream/rate/analog board needs independent requalification.
    """
    def __init__(self, directory):
        directory = Path(directory)
        self.paths = [directory / n for n in
                      ("rx1_dc_calibration.json", "rx2_calibration.json", "dac_calibration.json")]
        self.rx1, self.rx2, self.dac = [json.loads(p.read_text(encoding="utf-8")) for p in self.paths]
        self.input_limits = {}
        self.ve_feedback = None
        self.tx3_waveforms = None
        self.tx2_waveforms = None
        for name, attribute in (("adc_input_limits.json", "input_limits"),
                                ("tx2_waveform_calibration.json", "tx2_waveforms"),
                                ("tx3_waveform_calibration.json", "tx3_waveforms"),
                                ("ve_feedback_calibration.json", "ve_feedback")):
            path = directory / name
            if path.exists():
                setattr(self, attribute, json.loads(path.read_text(encoding="utf-8")))
                self.paths.append(path)
        self.tx2_waveform_library=self.tx2_waveforms
        if self.ve_feedback:
            if hashlib.sha256(self.paths[1].read_bytes()).hexdigest() != self.ve_feedback['adc_channel_calibration_sha256']:
                raise ValueError('VE table does not match the RX2 connector calibration')
            points = self.ve_feedback['points']
            if len(points) < 2 or any(not math.isfinite(p[k]) for p in points for k in ('adc_v', 've_v')):
                raise ValueError('Invalid VE feedback table')
            if any(b['adc_v'] <= a['adc_v'] or b['ve_v'] <= a['ve_v'] for a,b in zip(points,points[1:])):
                raise ValueError('VE feedback table must be strictly increasing')

    def manifest(self):
        return {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                         "profile": json.loads(p.read_text(encoding="utf-8"))}
                for p in self.paths}

    def conversion_range(self, channel):
        p = (self.rx1, self.rx2)[channel]
        return (self.input_limits.get('conversion_min_v', p['valid_min_v']),
                self.input_limits.get('conversion_max_v', p['valid_max_v']))

    def ve_conversion(self, profile, channel):
        table = self.ve_feedback
        return table if table and profile in table['profiles'] and channel == table['channel'] else None

    def ve_from_port(self, voltage, profile, channel=1, fallback_ratio=.206):
        table = self.ve_conversion(profile, channel)
        if not table:
            return voltage / fallback_ratio
        if not math.isfinite(voltage):
            raise ValueError('Invalid VE feedback voltage')
        points = table['points']
        low, high = self.conversion_range(channel)
        if not low <= voltage <= high:
            raise ValueError('VE feedback outside software conversion range')
        # Preserve the requested connector range. Outside measured knots the
        # nearest measured segment is extrapolated, and scan records mark it.
        index = min(max(bisect.bisect_right([p['adc_v'] for p in points], voltage)-1, 0),len(points)-2)
        a,b = points[index:index+2]
        return a['ve_v']+(voltage-a['adc_v'])*(b['ve_v']-a['ve_v'])/(b['adc_v']-a['adc_v'])

    def port_v(self, code, channel):
        if channel not in (0, 1) or not math.isfinite(code) or not 0 <= code <= 65535:
            raise ValueError("Invalid channel/code")
        p = (self.rx1, self.rx2)[channel]
        voltage = (code - p["zero_code_q16"] / 65536) * p["slope_nv_per_code"] / 1e9
        if code in (0,65535):
            raise ValueError('ADC clipped at code rail')
        low, high = self.conversion_range(channel)
        if not low <= voltage <= high:
            raise ValueError("ADC voltage outside software conversion range")
        return voltage

    def dac_code(self, channel, volts):
        if channel not in (0, 1, 2) or not math.isfinite(volts):
            raise ValueError("Invalid DAC channel/voltage")
        p = self.dac["channels"][channel]
        if channel == 0:
            if not 0 <= volts <= 2.5 * 4095 / 4096:
                raise ValueError("TX1 outside nominal 12-bit range")
            code = math.floor(volts * 4096 / 2.5 + .5)
            return code, code * 2.5 / 4096
        table = p.get("dc_table")
        if not table:
            raise ValueError("No qualified positive DC table for this channel")
        codes = table["codes"]
        step = table["step_uv"] / 1e6
        if not 0 <= volts <= step * (len(codes) - 1):
            raise ValueError("DAC outside archived positive DC table")
        i = min(int(volts / step), len(codes) - 2)
        code = math.floor(codes[i] + (volts / step - i) * (codes[i + 1] - codes[i]) + .5)
        j = min(max(bisect.bisect_right([-c for c in codes], -code) - 1, 0), len(codes) - 2)
        actual = (j + (code - codes[j]) / (codes[j + 1] - codes[j])) * step
        return code, actual

    def warm_sine_reference(self):
        """Return a historical warm point only while its actual code table matches.

        This is evidence about a previous measurement, not detection of the
        present board temperature or qualification of a frequency sweep.
        """
        profile = self.dac['channels'][2].get('sine_50mv', {})
        if profile.get('warm_reference_status') != '100khz_70mvpp_warmed_repeat_verified':
            return None
        record = profile.get('warm_reference', {})
        setting, stability = record.get('setting', {}), record.get('stability', {})
        try:
            frequency, amplitude = float(setting['frequency_hz']), float(setting['amplitude_vpp_v'])
            if not all(math.isfinite(v) and v > 0 for v in (frequency, amplitude)):
                return None
            if stability.get('stable') is not True or stability.get('samples', 0) < 5 or stability.get('span_s', 0) < 90:
                return None
            if not record.get('source') or setting['dac_sample_rate_hz'] != profile.get('dac_sample_rate_hz'):
                return None
            index = profile['frequency_hz'].index(frequency)
            peak = profile['peak_codes'][index] * amplitude / (profile['target_vpp_uv']/1e6)
            if setting['zero_code'] != profile['zero_code'] or not math.isclose(peak, setting['peak_codes'], rel_tol=1e-12):
                return None
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return None
        return dict(frequency_hz=frequency, amplitude_vpp_v=amplitude,
                    dac_sample_rate_hz=setting['dac_sample_rate_hz'], source=record['source'])

    def select_tx2_waveform_profile(self, identity=None):
        """Choose only measurements made with this exact FPGA image/HWH."""
        library=self.tx2_waveform_library
        if identity is None:
            self.tx2_waveforms=library
        elif library:
            self.tx2_waveforms=next((p for p in [library]+library.get('hardware_variants',[])
                if p.get('bitstream_sha256')==identity.get('bit_sha256')
                and p.get('hwh_sha256')==identity.get('hwh_sha256')),None)
        return self.tx2_waveforms

    def tx2_waveform_parameters(self, shape, frequency_hz, amplitude_vpp, offset_v):
        """AC-only reference inside its measured region; DC tables stay separate."""
        profile=self.tx2_waveforms
        if not profile or shape not in ('sine','square','triangle'):
            return None
        if not all(math.isfinite(v) for v in (frequency_hz,amplitude_vpp,offset_v)):
            raise ValueError('TX2 waveform parameters must be finite')
        if not math.isclose(offset_v,profile['offset_v'],abs_tol=1e-12):
            return None
        rows=[r for r in profile['points'] if r['shape']==shape]
        if profile.get('exact_nodes_only'):
            rows=[r for r in rows if math.isclose(r['frequency_hz'],frequency_hz,rel_tol=1e-12)
                  and math.isclose(r['target_vpp_v'],amplitude_vpp,rel_tol=1e-12)]
            if not rows:return None
        if not rows or not (min(r['frequency_hz'] for r in rows)<=frequency_hz<=max(r['frequency_hz'] for r in rows)
                           and min(r['target_vpp_v'] for r in rows)<=amplitude_vpp<=max(r['target_vpp_v'] for r in rows)):
            return None
        if profile['dac_sample_rate_hz']!=self.dac.get('operating_dac_sample_rate_hz'):
            raise ValueError('TX2 waveform table targets a different DAC sample rate')
        from .waveform_reference import resolve
        return resolve(dict(profile,points=rows),shape,frequency_hz,amplitude_vpp)

    def validate_tx2_waveform_identity(self, identity):
        profile=self.tx2_waveforms
        if not profile or not profile.get('bitstream_sha256') or not profile.get('hwh_sha256') or any(identity.get(key)!=profile.get(field) for key,field in
                              (('bit_sha256','bitstream_sha256'),('hwh_sha256','hwh_sha256'))):
            raise ValueError('TX2 waveform table does not match the active bitstream/HWH')
        if identity.get('dac_divider')!=1000000000/profile['dac_sample_rate_hz']:
            raise ValueError('TX2 waveform table targets a different DAC clock')

    def waveform_parameters(self, shape, frequency_hz, amplitude_vpp):
        if self.tx3_waveforms is None: return None
        from .waveform_reference import resolve
        rate=self.tx3_waveforms['dac_sample_rate_hz']
        if rate != self.dac.get('operating_dac_sample_rate_hz') or rate != self.dac['channels'][2]['sine_50mv'].get('dac_sample_rate_hz'):
            raise ValueError('TX3 waveform table targets a different DAC sample rate')
        return resolve(self.tx3_waveforms,shape,frequency_hz,amplitude_vpp)

    def validate_waveform_identity(self, identity):
        profile = self.tx3_waveforms or {}
        expected = profile.get('bitstream_sha256')
        actual = identity.get('bit_sha256')
        if not expected:
            return dict(status='legacy_reference_without_bitstream_binding')
        basis = dict(calibration_bitstream_sha256=expected, active_bitstream_sha256=actual)
        if actual == expected:
            return dict(basis, status='measured_bitstream')
        # A reviewed digital derivative may use the original table as a
        # reference. Never replace its measured identity or claim a new analog
        # calibration. Unknown bitstreams and wrong HWH/clock pairs stay locked.
        for record in profile.get('compatible_bitstreams', []):
            rate = record.get('dac_sample_rate_hz', 0)
            if (record.get('bitstream_sha256') == actual
                    and record.get('source_bitstream_sha256') == expected
                    and record.get('hwh_sha256')
                    and record['hwh_sha256'] == identity.get('hwh_sha256')
                    and rate == profile.get('dac_sample_rate_hz') and rate > 0
                    and identity.get('dac_divider') == 1000000000/rate
                    and record.get('basis') == 'dac_logic_and_clock_match_reference_only'):
                return dict(basis, status='compatible_bitstream_reference',
                            analog_recalibrated=False, evidence=record.get('evidence'))
        raise ValueError('TX3 校准表与当前 FPGA 位流不匹配（当前 {}；标定 {}），请使用配套发行版'.format(
            str(actual or '未知')[:12], str(expected)[:12]))

    def bind_waveform_plan(self, plan, identity):
        """Attach the actual hardware provenance without changing DAC codes."""
        binding = self.validate_waveform_identity(identity)
        result = dict(plan, bitstream_reference=binding)
        if binding['status'] == 'compatible_bitstream_reference':
            result.update(reference_amplitude_basis=plan['amplitude_basis'],
                          amplitude_basis='compatible_bitstream_reference_unverified')
        return result

    def sine_parameters(self, frequency_hz, amplitude_vpp):
        """Scale the measured reference, rejecting overflow instead of clipping.

        Only the reference amplitude was measured. A larger DAC code range is
        available, but does not establish analog amplitude accuracy or headroom.
        """
        modern=self.waveform_parameters('sine',frequency_hz,amplitude_vpp)
        if modern is not None:return modern
        profile = self.dac["channels"][2].get("sine_50mv")
        if not profile or profile.get("validation_status") not in (
                "verified_78_points_midpoints_post_jtag_gui",
                "verified_custom50_scope_78_points_midpoints",
                "drifting_scope_reference_estimate"):
            raise ValueError("TX3 does not have a supported sine reference")
        if not math.isfinite(frequency_hz) or not math.isfinite(amplitude_vpp):
            raise ValueError("Sine frequency and amplitude must be finite")
        if amplitude_vpp <= 0:
            raise ValueError("TX3 正弦峰峰值必须大于 0 V")
        frequencies = profile["frequency_hz"]
        peaks = profile["peak_codes"]
        if not frequencies[0] <= frequency_hz <= frequencies[-1]:
            raise ValueError("TX3 sine frequency is outside its reference profile")
        index = min(max(bisect.bisect_right(frequencies, frequency_hz) - 1, 0), len(frequencies) - 2)
        fraction = (frequency_hz - frequencies[index]) / (frequencies[index + 1] - frequencies[index])
        reference_peak = peaks[index] + fraction * (peaks[index + 1] - peaks[index])
        reference_vpp = profile["target_vpp_uv"] / 1e6
        zero = profile["zero_code"]
        if not 0 < zero < 65535 or reference_peak <= 0 or reference_vpp <= 0:
            raise ValueError("Invalid TX3 sine reference")
        max_vpp = reference_vpp * min(zero, 65535-zero) / reference_peak
        if amplitude_vpp > max_vpp:
            raise ValueError("TX3 当前频率的码值上限为峰值 {:.4f} V（{:.4f} Vpp）；请减小幅度".format(max_vpp/2, max_vpp))
        scale = amplitude_vpp / reference_vpp
        warm = self.warm_sine_reference()
        matches_warm = bool(warm and math.isclose(frequency_hz, warm['frequency_hz'], rel_tol=1e-12)
                            and math.isclose(amplitude_vpp, warm['amplitude_vpp_v'], rel_tol=1e-12))
        amplitude_basis = ('scope_verified_warm_point' if matches_warm else
                           'scope_verified_reference' if profile.get('validation_status')!='drifting_scope_reference_estimate'
                           and math.isclose(amplitude_vpp, reference_vpp, rel_tol=1e-12) else 'scaled_reference_unverified')
        return dict(zero_code=zero, peak_codes=reference_peak*scale,
                    reference_vpp=reference_vpp, scale=scale, max_vpp=max_vpp,
                    amplitude_basis=amplitude_basis, warm_reference=warm,
                    offset_validation_status=('warm_point_verified' if matches_warm else profile.get('offset_validation_status','historical_zero_verification')),
                    dac_sample_rate_hz=profile.get('dac_sample_rate_hz'))

    def sine_samples(self, frequency_hz, amplitude_vpp):
        """Build an unclipped TX3 sine; extended amplitudes are estimates."""
        plan = self.sine_parameters(frequency_hz, amplitude_vpp)
        zero, peak = plan['zero_code'], plan['peak_codes']
        return [int(math.floor(zero + peak * math.sin(2 * math.pi * i / 256) + 0.5))
                for i in range(256)]
