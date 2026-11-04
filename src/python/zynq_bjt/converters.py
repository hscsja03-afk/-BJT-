"""Python port of the archived AD9516/AD9268/AD9747 GPIO SPI protocol.

Injected pins provide read(pin), write(pin, value), output(pin, enabled).
Initialization is explicit. Python scheduling can slow SPI; no sample timing
depends on this software bus. ADC/DAC sample clocks remain in hardware.
"""
import time

SCLK, MOSI, MISO, DAC_CS, DAC_RESET, IQSEL, CLOCK_CS = range(7, 14)
SDIO, ADC_SCLK, ADC_CS, DATA_OE, CTRL_OE = range(29, 34)


class Converters:
    def __init__(self, pins, pause=time.sleep):
        self.pins, self.pause = pins, pause

    def half(self): self.pause(.000001)

    def begin(self, cs):
        self.pins.write(DAC_CS, 1); self.pins.write(CLOCK_CS, 1)
        self.pins.write(SCLK, 0); self.half()
        self.pins.write(cs, 0); self.half()

    def end(self, cs):
        self.half(); self.pins.write(cs, 1); self.half()

    def byte(self, value):
        result = 0
        for shift in range(7, -1, -1):
            self.pins.write(MOSI, (value >> shift) & 1); self.half()
            self.pins.write(SCLK, 1); self.half()
            result = (result << 1) | (self.pins.read(MISO) & 1)
            self.pins.write(SCLK, 0)
        return result

    def write(self, device, address, value):
        if type(value) is not int or not 0 <= value <= 255:
            raise ValueError("SPI value must be a byte")
        if device not in (9516, 9747) or not 0 <= address <= (0x1fff if device == 9516 else 0x1f):
            raise ValueError("Invalid SPI device/address")
        cs = CLOCK_CS if device == 9516 else DAC_CS
        self.begin(cs)
        try:
            if device == 9516: self.byte(address >> 8)
            self.byte(address & 255); self.byte(value)
        finally: self.end(cs)

    def read(self, device, address):
        if device not in (9516, 9747) or not 0 <= address <= (0x1fff if device == 9516 else 0x1f):
            raise ValueError("Invalid SPI device/address")
        cs = CLOCK_CS if device == 9516 else DAC_CS
        self.begin(cs)
        try:
            if device == 9747:
                self.byte(0x80 | address)
                return self.byte(0)
            self.byte(0x80 | (address >> 8)); self.byte(address & 255)
            self.pins.write(MOSI, 0)
            result = 0
            # AD9516 SDO settles after falling SCLK; sample while low.
            for _ in range(8):
                self.half(); result = (result << 1) | (self.pins.read(MISO) & 1)
                self.pins.write(SCLK, 1); self.half(); self.pins.write(SCLK, 0)
            return result
        finally: self.end(cs)

    def adc_transfer(self, address, value=None):
        if not 0 <= address <= 0x1fff or (value is not None and (type(value) is not int or not 0 <= value <= 255)):
            raise ValueError("Invalid ADC SPI command")
        read = value is None
        self.pins.write(ADC_SCLK, 0); self.pins.write(ADC_CS, 1)
        self.pins.write(SDIO, 0); self.pins.output(SDIO, True)
        self.half(); self.pins.write(ADC_CS, 0); self.half()
        try:
            command = address | (0x8000 if read else 0)
            bits = [(command >> i) & 1 for i in range(15, -1, -1)]
            if not read: bits += [(value >> i) & 1 for i in range(7, -1, -1)]
            for i, bit in enumerate(bits):
                self.pins.write(SDIO, bit); self.half()
                self.pins.write(ADC_SCLK, 1); self.half()
                if read and i == 15: self.pins.output(SDIO, False)
                self.pins.write(ADC_SCLK, 0); self.half()
            result = 0
            if read:
                for _ in range(8):
                    self.half(); result = (result << 1) | (self.pins.read(SDIO) & 1)
                    self.pins.write(ADC_SCLK, 1); self.half()
                    self.pins.write(ADC_SCLK, 0); self.half()
            return result
        finally:
            self.pins.write(ADC_CS, 1); self.half()
            self.pins.write(SDIO, 0); self.pins.output(SDIO, True)

    @staticmethod
    def check(device, address, expected, actual):
        if actual != expected:
            raise RuntimeError(f"SPI readback {device} register 0x{address:x}: expected 0x{expected:x}, got 0x{actual:x}")

    def mute(self, channel_mask=0):
        if channel_mask not in range(4): raise ValueError("Invalid DAC channel mask")
        value = 0x30 | (3 ^ channel_mask)
        self.write(9747, 3, value); self.pause(.001)
        self.check(9747, 3, value, self.read(9747, 3))

    def init_dac_muted(self):
        self.pins.write(DAC_RESET, 1); self.pause(.00001)
        self.pins.write(DAC_RESET, 0); self.pause(.0001)
        settings = [(0, 0), (3, 0x33), (2, 0x80), (0xa, 0),
                    (0xb, 0xf9), (0xc, 1), (0xf, 0xf9), (0x10, 1)]
        for a, v in settings: self.write(9747, a, v)
        for a, v in settings: self.check(9747, a, v, self.read(9747, a))

    def init_adc(self):
        self.adc_transfer(0, 0x3c); self.pause(.001); self.adc_transfer(0, 0x18)
        self.check(9268, 1, 0x32, self.adc_transfer(1))
        self.adc_transfer(5, 3)
        settings = [(8, 0x80), (9, 1), (0xb, 0), (0xd, 0),
                    (0x14, 0), (0x16, 0), (0x17, 0), (0x18, 0xc0)]
        for a, v in settings: self.adc_transfer(a, v)
        self.adc_transfer(0xff, 1); self.pause(.001)
        try:
            for channel in (1, 2):
                self.adc_transfer(5, channel)
                for a, v in settings: self.check(9268, a, v, self.adc_transfer(a))
        finally: self.adc_transfer(5, 3)

    def adc_test_mode(self, mode):
        if mode not in range(8): raise ValueError("Invalid ADC test mode")
        self.adc_transfer(5, 3); self.adc_transfer(0xd, mode)
        self.adc_transfer(0xff, 1); self.pause(.001)
        try:
            for channel in (1, 2):
                self.adc_transfer(5, channel)
                self.check(9268, 0xd, mode, self.adc_transfer(0xd) & 7)
        finally: self.adc_transfer(5, 3)

    def init_clocks(self, adc_divider, dac_divider):
        if adc_divider not in (8, 10, 12, 16, 20) or dac_divider not in (4, 5, 6, 7, 8, 10, 20):
            raise ValueError("Unsupported clock profile")
        def div(n): return ((n//2-1) << 4) | ((n+1)//2-1)
        settings = [(0x10, 0x4c), (0x11, 1), (0x12, 0), (0x13, 0), (0x14, 5), (0x15, 0),
                    (0x16, 4), (0x17, 0xb4), (0x18, 6), (0x19, 0), (0x1a, 0),
                    (0x1b, 0xa0), (0x1c, 3), (0x1d, 0)]
        settings += [(a, 0xa) for a in range(0xf0, 0xf6)]
        settings += [(a, 0x43) for a in range(0x140, 0x144)]
        settings += [(0x199, div(adc_divider)), (0x19a, 0), (0x19b, 0), (0x19c, 0x20), (0x19d, 0),
                     (0x19e, div(dac_divider)), (0x19f, 0), (0x1a0, 0), (0x1a1, 0x20), (0x1a2, 0),
                     (0x1e0, 0), (0x1e1, 2), (0x230, 0)]
        self.write(9516, 0, 0x99)
        self.check(9516, 3, 0x43, self.read(9516, 3))
        for a, v in settings: self.write(9516, a, v)
        self.write(9516, 0x232, 1); self.write(9516, 4, 1)
        for a, v in settings: self.check(9516, a, v, self.read(9516, a))
        self.write(9516, 0x18, 7); self.write(9516, 0x232, 1)
        for _ in range(1000):
            if self.read(9516, 0x1f) & 0x4b == 0x4b: break
            self.pause(.001)
        else: raise TimeoutError("AD9516 PLL did not lock")
        self.write(9516, 0x140, 0x42); self.write(9516, 0x142, 0x42); self.write(9516, 0x232, 1)
        self.write(9516, 0x230, 1); self.write(9516, 0x232, 1); self.pause(.00001)
        self.write(9516, 0x230, 0); self.write(9516, 0x232, 1); self.pause(.001)
        for address in (0x140, 0x142): self.check(9516, address, 0x42, self.read(9516, address))
