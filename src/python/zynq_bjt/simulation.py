"""Explicit synthetic backend. Never imports PYNQ or opens physical devices."""
import math
import bisect
import time
from .mmio import Frame, validate_capture_channels
from .runtime import OutputState
from .profiles import Profile


class SimulatedBoard:
    simulated = True
    adc_ready = True
    def __init__(self, calibration, frontend):
        self.cal, self.front = calibration, frontend
        self.identity = {'kind': 'synthetic_bjt_model', 'analog_calibration_qualified': False}
        self.codes = [0, calibration.dac_code(1, 0)[0], 32768]
        self.volts = [0.0, 0.0, 0.0]
        self.enabled = [False]*3
        self.gpio_value = 0
        self.sequence = 0
        self.measurement_transfer = None
        self.ac_transfer = None
        self.ac_frequency_hz = 0.0
        self.ac_amplitude_vpp = 0.0
        self.display_lines = []
    def output(self, ch): return OutputState(self.codes[ch], self.enabled[ch], 'simulation')
    def enable(self, ch, enabled): self.enabled[ch] = bool(enabled); return self.output(ch)
    def set_code(self, ch, code):
        self.codes[ch] = code
        if ch == 0: self.volts[ch] = code*2.5/4096
        elif ch == 1:
            codes = self.cal.dac['channels'][1]['dc_table']['codes']
            step = self.cal.dac['channels'][1]['dc_table']['step_uv']/1e6
            for i in range(len(codes)-1):
                if codes[i+1] <= code <= codes[i]:
                    self.volts[ch] = (i+(code-codes[i])/(codes[i+1]-codes[i]))*step
                    break
            else: raise ValueError('Synthetic TX2 outside DC table')
        return self.output(ch)
    def gpio(self, mask=None, value=None):
        if mask is not None: self.gpio_value = (self.gpio_value & ~mask) | (value & mask)
        return {'output': self.gpio_value, 'sense': self.gpio_value, 'sequence': self.sequence}
    def set_measurement_transfer(self, transfer):
        previous = self.measurement_transfer
        self.measurement_transfer = transfer
        return previous
    def display_status(self, lines):
        self.display_lines = list(lines)
    def set_ac_transfer(self, transfer):
        previous = self.ac_transfer
        self.ac_transfer = transfer
        return previous
    def set_sine(self, channel, calibration, frequency_hz, amplitude_vpp):
        if channel != 2: raise ValueError('Only TX3 is modeled as the AC source')
        samples = calibration.sine_samples(frequency_hz, amplitude_vpp)
        self.ac_frequency_hz = frequency_hz
        self.ac_amplitude_vpp = amplitude_vpp
        self.codes[channel] = samples[0]
        return self.output(channel)
    def capture_statistics(self, sample_count):
        if not all(self.enabled): raise RuntimeError('Synthetic AC stimuli are disabled')
        if not self.ac_transfer: raise RuntimeError('Synthetic AC transfer is not configured')
        transfer = self.ac_transfer
        frequency = self.ac_frequency_hz
        gain = transfer.get('passband_gain', 100.0) / math.sqrt(
            1.0 + (frequency / transfer.get('f_beta_hz', 250000.0)) ** 2)
        source_peak = self.ac_amplitude_vpp * transfer.get('source_buffer_gain', 1.0) / 2.0
        input_node_peak = source_peak * transfer.get('input_node_fraction', 0.5)
        input_current_peak = ((source_peak - input_node_peak) /
                              transfer.get('input_test_resistor_ohm', 100.0))
        if transfer.get('pnp_emitter_sense'):
            # Common collector fixture: VE follows VB. Solve the input divider
            # instead of combining arbitrary VB with common-emitter gain.
            base_input_ohm = (gain+1.0)*transfer.get('output_resistor_ohm',100.0)/.98
            input_current_peak = source_peak/(transfer.get('input_test_resistor_ohm',100.0)+base_input_ohm)
            input_node_peak = input_current_peak*base_input_ohm
        input_rms = (input_node_peak * transfer.get('input_sample_gain', 10.0) /
                     math.sqrt(2.0))
        output_rms = ((gain + (1.0 if transfer.get('pnp_emitter_sense') else 0.0)) * input_current_peak * transfer.get('output_resistor_ohm', 100.0) /
                      math.sqrt(2.0))
        values = [None, None]
        for channel, rms, ratio in (
                (transfer['input_channel'], input_rms, transfer.get('input_adc_per_v', 1.0)),
                (transfer['output_channel'], output_rms, transfer.get('output_adc_per_v', 0.206))):
            profile = (self.cal.rx1, self.cal.rx2)[channel]
            values[channel] = {
                'mean_code': profile['zero_code_q16'] / 65536.0,
                'rms_code': rms * ratio * 1e9 / abs(profile['slope_nv_per_code']) / transfer.get('adc_amplitude_multiplier', 1.0),
                'fault_count': 0,
            }
        self.sequence += 1
        return {'sample_count': sample_count, 'channels': values, 'completed_at': time.time(),
                'simulated': True}
    def set_pulse(self, calibration, high_v, frequency_hz=10.0, duty_percent=20.0):
        from .pulse import table
        samples, self.pulse_plan = table(calibration, high_v, 125000000,frequency_hz,duty_percent)
        self.set_code(1, samples[0])
        return self.pulse_plan

    def capture(self, channels=(0, 1), sample_stride=1):
        validate_capture_channels(channels)
        if not all(self.enabled[:2]): raise RuntimeError('Synthetic stimuli are disabled')
        transfer = self.measurement_transfer or {}
        profile = Profile(transfer.get('profile', 'npn_small'))
        if self.gpio_value & 0x04:
            resistance = transfer.get('base_resistance_ohm', self.front.base_equivalent_resistance_ohm)
            collector_r = transfer.get('collector_resistor_ohm', 100.0)
            ib = max(self.volts[0] / resistance, 1e-12)
            vcc = self.volts[1] * self.front.collector_amplifier_gain
            ic_ideal = 100.0 * ib
            if transfer.get('polarity_probe'):
                device = getattr(self, 'probe_device_polarity', 'npn')
                gain = 0 if device == 'open' else 100 if device == 'ambiguous' or device == ('pnp' if profile.pnp else 'npn') else 1
                ic_ideal = gain * ib
            uce = max(0.0, (vcc - collector_r * (ic_ideal + (ib if profile.pnp else 0))) /
                      (1.0 + collector_r * ic_ideal / 50.0))
            ic = ic_ideal * (1.0 + uce / 50.0)
            collector_channel = transfer.get('collector_channel', 0)
            source_channel = transfer.get('source_channel', 1)
            voltages = [0.0, 0.0]
            vc = uce  # ADC1 senses VE for PNP, VC for NPN
            voltages[collector_channel] = vc * transfer.get('collector_adc_per_v', self.front.rx1_per_vc)
            voltages[source_channel] = vcc * transfer.get('source_adc_per_v', 0.4)
            vb = .53+.042*math.log(max(ib, 1e-10)/1e-7)-.004*math.log1p(uce)
        else:
            ib = self.volts[1 if profile.pnp else 0]/transfer.get('base_resistance_ohm',self.front.base_equivalent_resistance_ohm)
            supply = self.volts[0 if profile.pnp else 1]*self.front.collector_amplifier_gain
            uce = supply+.001
            voltages = [0.0, 0.0]
            voltages[transfer.get('collector_channel',1)] = uce*self.front.rx1_per_vc
            if profile.pnp and transfer.get('ve_table'):
                points=self.cal.ve_conversion(profile.key,transfer.get('collector_channel',1))['points']
                index=min(max(bisect.bisect_right([p['ve_v'] for p in points],uce)-1,0),len(points)-2)
                a,b=points[index:index+2]
                voltages[transfer.get('collector_channel',1)]=a['adc_v']+(uce-a['ve_v'])*(b['adc_v']-a['adc_v'])/(b['ve_v']-a['ve_v'])
            vb = .53+.042*math.log(max(ib, 1e-10)/1e-7)-.004*math.log1p(uce)
            voltages[transfer.get('base_channel',0)] = (uce-vb if profile.pnp else vb)*transfer.get('base_adc_per_v',.25)
        words = []
        for ch, (v, p) in enumerate(zip(voltages, (self.cal.rx1, self.cal.rx2))):
            if ch not in channels:
                words.append(())
                continue
            code = round(v*1e9/p['slope_nv_per_code']+p['zero_code_q16']/65536)
            words.append(tuple(code+((i+self.sequence) % 3-1) for i in range(1024)))
            if transfer.get('pulsed') and hasattr(self,'pulse_plan'):
                zero=round(p['zero_code_q16']/65536)
                phase=(self.sequence*.137)%1
                words[-1]=tuple(v if (phase+i*sample_stride/125000000*self.pulse_plan['frequency_hz'])%1 < self.pulse_plan['duty_percent']/100
                                else zero for i,v in enumerate(words[-1]))
        self.sequence += 1
        return Frame(self.sequence, tuple(words), (125000000/sample_stride,)*2, time.time(), simulated=True,
                     captured_channels=tuple(channels), sample_stride=sample_stride,
                     adc_sample_rates_hz=(125000000,)*2)
