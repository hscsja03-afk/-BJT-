"""Explicit board session for PYNQ. No hardware is opened by importing it."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import math
import threading
import time
from .converters import Converters, DATA_OE, CTRL_OE
from .mmio import AddaCore
from .tx1 import Tx1


@dataclass(frozen=True)
class OutputState:
    code: int
    enabled: bool
    code_basis: str


class Board:
    def __init__(self, core, pins, *, pause=time.sleep):
        self.core, self.pins, self.pause = core, pins, pause
        self.spi = Converters(pins, pause)
        self.tx1 = Tx1(core.io, pause)
        self.lock = threading.RLock()
        self.initialized = False
        self.adc_ready = False
        self.sample_rates_hz = None
        self.codes = [None, None, None]
        self.identity = {}

    @classmethod
    def from_pynq(cls, bitfile, *, program=False):
        from pynq import Overlay
        from .mio import Mio
        bitfile = Path(bitfile).resolve()
        hwh = bitfile.with_suffix(".hwh")
        if not bitfile.is_file() or not hwh.is_file(): raise FileNotFoundError("Matching bit/HWH pair required")
        identity = {p.suffix[1:]+"_sha256": hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (bitfile, hwh)}
        overlay = Overlay(str(bitfile), download=False)
        info = overlay.ip_dict.get("adda_core_0", {})
        if info.get("phys_addr") != 0x43c00000 or info.get("addr_range") != 0x10000:
            raise ValueError("Overlay address map differs from driver contract")
        # Reject an incompatible running PS setup before replacing the PL.
        # Mio.from_pynq checks again when it actually claims the GPIO lines.
        Mio.preflight_from_pynq()
        if program: overlay.download()
        elif not overlay.is_loaded(): raise RuntimeError("Selected overlay is not loaded; explicitly program it first")
        core = AddaCore(overlay.adda_core_0.mmio)
        pins = Mio.from_pynq()
        try:
            board = cls(core, pins)
            board.overlay = overlay
            board.identity = identity
        except BaseException as error:
            try: pins.close()
            except Exception as cleanup:
                raise RuntimeError(f"Board construction failed ({error}); GPIO cleanup unconfirmed: {cleanup}") from error
            raise
        return board

    def initialize(self, *, adc_divider=20, dac_divider=None):
        """Initialize chips muted, verify clocks and both ADC digital paths."""
        with self.lock:
            if self.initialized: raise RuntimeError("Board already initialized")
            if dac_divider is None:
                compiled_rate=self.core.io.read(0x30)
                if compiled_rate not in (50000000,125000000):
                    raise ValueError('Automatic initialization supports DAC50 or DAC125 only')
                dac_divider=1000000000//compiled_rate
            if adc_divider not in (8, 10, 12, 16, 20) or dac_divider not in (4, 5, 6, 7, 8, 10, 20):
                raise ValueError("Unsupported clock divider")
            minimum_divider = int(self.core.io.read(0xd4)) if self.core.io.read(0xc)&0x10000000 else 20
            if minimum_divider not in (8,10,12,16,20) or adc_divider<minimum_divider:
                raise ValueError('ADC clock exceeds the compiled timing profile')
            if self.core.io.read(0x30) != 1000000000 // dac_divider:
                raise ValueError("DAC divider differs from the compiled overlay")
            try:
                self.pins.write(DATA_OE, 1); self.pins.write(CTRL_OE, 1)
                self.core.io.write(4, 6); self.pause(.001)
                self.core.io.write(4, 7)
                self.spi.init_dac_muted()
                self.spi.init_clocks(adc_divider, dac_divider)
                self.core.io.write(4, 3)
                self.core.wait(lambda: bool(self.core.io.read(0xc) & 16), 1)
                # ADC DCO reaches the FPGA through the data translator. Enable
                # that path before evaluating its clock counters (as in adda.c).
                self.pins.write(CTRL_OE, 0)
                self.spi.init_adc()
                self.pins.write(DATA_OE, 0)
                if self.core.io.read(0xc)&0x10000000:
                    self.core.wait(lambda:self.core.io.read(0xd8)==3,1)
                self.pause(.001)
                rates = self.core.clock_rates()
                expected = (1000000000/adc_divider,)*2+(1000000000/dac_divider,)
                if any(not math.isfinite(actual) or abs(actual-target) > .02*target
                       for actual, target in zip(rates, expected)):
                    raise RuntimeError(f"Clock profile mismatch: measured {rates}, expected {expected}")
                self.sample_rates_hz = (rates[1], rates[0])
                digital_results=self.digital_self_test()
                self.tx1.initialize_muted()
                self.codes[0] = 0
                for channel in (0, 1):
                    self.core.awg(channel, [32768]*256)
                    self.codes[channel+1] = 32768
                self.spi.mute(0)
                self.initialized = self.adc_ready = True
                self.identity.update(adc_divider=adc_divider, dac_divider=dac_divider,
                                     measured_clock_hz=rates, digital_self_test="passed",
                                     digital_test_results=digital_results,analog_calibration_qualified=False)
                return dict(self.identity)
            except BaseException as primary:
                errors = self._quiesce()
                if errors: raise RuntimeError(f"{primary}; cleanup unconfirmed: {errors}") from primary
                raise

    def digital_self_test(self):
        results = []
        count=4096 if self.core.io.read(0xc)&0x20000000 else 1024
        try:
            for mode, expected in ((1, 0x8000), (2, 0xffff), (3, 0), (4, None)):
                self.spi.adc_test_mode(mode)
                frame = self.core.capture(self.sample_rates_hz,sample_count=count)
                for channel in (0, 1):
                    codes = frame.codes(channel)
                    errors = sum(v != expected for v in codes) if expected is not None else sum(
                        v not in (0xaaaa, 0x5555) or (i > 0 and v == codes[i-1])
                        for i, v in enumerate(codes))
                    results.append({"test_mode": mode, "channel": channel, "errors": errors,"samples":len(codes)})
                    if errors: raise RuntimeError(f"ADC RX{channel+1} test mode {mode}: {errors} bad codes")
        finally:
            self.spi.adc_test_mode(0)
        return results

    def capture(self, sample_stride=1, channels=(0, 1), sample_count=1024):
        with self.lock:
            if not self.adc_ready: raise RuntimeError("ADC is not initialized")
            if not self.core.io.read(0xc) & 16: raise RuntimeError("DAC clock lost lock")
            if self.core.io.read(0xc)&0x10000000 and self.core.io.read(0xd8)!=3:
                raise RuntimeError("ADC clock lost lock; reinitialize before capture")
            return self.core.capture(self.sample_rates_hz, sample_stride=sample_stride, channels=channels, sample_count=sample_count)

    def capture_statistics(self, sample_count):
        with self.lock:
            if not self.adc_ready: raise RuntimeError("ADC is not initialized")
            if not self.core.io.read(0xc) & 16: raise RuntimeError("DAC clock lost lock")
            if self.core.io.read(0xc)&0x10000000 and self.core.io.read(0xd8)!=3:
                raise RuntimeError("ADC clock lost lock; reinitialize before capture")
            return self.core.capture_statistics(sample_count)

    def gpio(self, mask=None, value=None):
        with self.lock: return self.core.gpio(mask, value)

    def display_status(self, lines, *, page=1, color=2):
        if getattr(self, 'scan_lcd_managed', False):
            return  # Keep the host's live graph instead of switching to ASCII.
        with self.lock:
            if not self.initialized:
                raise RuntimeError("Board is not initialized")
            self.core.display_text(page, lines, color)

    def output(self, channel):
        if channel not in (0, 1, 2): raise ValueError("Invalid output")
        with self.lock:
            if not self.initialized: raise RuntimeError("Board is not initialized")
            if channel == 0:
                s = self.tx1.state()
                if s["reference_alarm"]: raise RuntimeError("TX1 reference alarm")
                return OutputState(s["code"], s["enabled"], s.get("code_basis", "device_register_readback"))
            power = self.spi.read(9747, 3)
            if power & 0x30 != 0x30: raise RuntimeError("Unexpected AD9747 auxiliary output state")
            return OutputState(self.codes[channel], not bool(power & (1 << (channel-1))),
                               "host_table_commit_ack_not_analog_readback")

    def set_code(self, channel, code):
        with self.lock:
            if not self.initialized: raise RuntimeError("Board is not initialized")
            if channel == 0: self.tx1.code(code)
            elif channel in (1, 2): self.core.awg(channel-1, [code]*256)
            else: raise ValueError("Invalid output channel")
            self.codes[channel] = code
            return self.output(channel)

    def set_sine(self, channel, calibration, frequency_hz, amplitude_vpp):
        if channel != 2: raise ValueError("Only TX3 has a sine-amplitude reference")
        calibration.validate_waveform_identity(self.identity)
        samples = calibration.sine_samples(frequency_hz, amplitude_vpp)
        with self.lock:
            if not self.initialized: raise RuntimeError("Board is not initialized")
            rate = calibration.dac["channels"][2]["sine_50mv"].get("dac_sample_rate_hz")
            if rate is not None and self.core.io.read(0x30) != rate:
                raise ValueError("TX3 sine reference targets a different DAC sample rate")
            # Frequency compensation changes the sample values too. Always
            # commit the calibrated table, including after DC/raw-wave mode.
            self.core.awg(1, samples, frequency_hz=frequency_hz)
            self.codes[channel] = samples[0]
            return self.output(channel)

    def set_pulse(self, calibration, high_v, frequency_hz=10.0, duty_percent=20.0):
        from .pulse import table
        with self.lock:
            if not self.initialized: raise RuntimeError('Board is not initialized')
            if not self.core.io.read(0x0c) & 0x80000000:
                raise RuntimeError('脉冲扫描需要支持长窗口采集的位流')
            samples, plan = table(calibration, high_v, self.core.io.read(0x30),frequency_hz,duty_percent)
            self.core.awg(0, samples, frequency_hz=plan['requested_frequency_hz'])
            self.codes[1] = samples[0]
            self.pulse_plan = plan
            return plan

    def enable(self, channel, enabled):
        if type(enabled) is not bool or channel not in (0, 1, 2): raise ValueError("Invalid output enable")
        with self.lock:
            if not self.initialized: raise RuntimeError("Board is not initialized")
            if channel == 0: self.tx1.enable(enabled)
            else:
                mask = 3 ^ (self.spi.read(9747, 3) & 3)
                bit = 1 << (channel-1)
                self.spi.mute((mask | bit) if enabled else (mask & ~bit))
            return self.output(channel)

    def _quiesce(self):
        errors = []
        for name, action in (("DAC mute", lambda: self.spi.mute(0)),
                             ("TX1 power down", lambda: self.tx1.verified(3, 1)),
                             ("ADC data disable", lambda: self.pins.write(DATA_OE, 1)),
                             ("ADC control disable", lambda: self.pins.write(CTRL_OE, 1))):
            try: action()
            except Exception as error: errors.append(f"{name}: {error}")
        self.initialized = self.adc_ready = False
        return errors

    def close(self):
        with self.lock:
            errors = self._quiesce()
            try:
                close_display=getattr(self.core,'close_display',None)
                if close_display is not None:close_display()
            except Exception as error:errors.append('LCD: '+str(error))
            try: self.pins.close()
            except Exception as error: errors.append(str(error))
            if errors: raise RuntimeError("Board cleanup unconfirmed: " + "; ".join(errors))
