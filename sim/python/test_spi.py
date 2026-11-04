from collections import deque
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/python"))
from zynq_bjt.converters import Converters, SCLK, MISO, SDIO, ADC_SCLK, ADC_CS, CLOCK_CS


class Pins:
    def __init__(self, bits=()):
        self.levels = {}; self.events = []; self.bits = deque(bits)
    def write(self, pin, value):
        self.levels[pin] = value; self.events.append(("write", pin, value))
    def output(self, pin, enabled): self.events.append(("direction", pin, enabled))
    def read(self, pin):
        self.events.append(("read", pin, self.levels.copy()))
        if not self.bits: raise RuntimeError("Read queue exhausted")
        return self.bits.popleft()


def bits(value): return [(value >> n) & 1 for n in range(7, -1, -1)]


class Tests(unittest.TestCase):
    def test_clock_chip_samples_low_and_releases_select(self):
        p = Pins([0]*16 + bits(0xa5))
        self.assertEqual(Converters(p, lambda _: None).read(9516, 3), 0xa5)
        reads = [event for event in p.events if event[0] == "read"]
        self.assertTrue(all(event[2][SCLK] == 0 for event in reads[-8:]))
        self.assertEqual(p.levels[CLOCK_CS], 1)

    def test_dac_samples_high(self):
        from zynq_bjt.converters import DAC_CS
        p = Pins([0]*8 + bits(0x39))
        self.assertEqual(Converters(p, lambda _: None).read(9747, 3), 0x39)
        reads = [event for event in p.events if event[0] == "read"]
        self.assertTrue(all(event[2][SCLK] == 1 for event in reads[-8:]))
        self.assertEqual(p.levels[DAC_CS], 1)

    def test_adc_releases_data_before_read_falling_edge(self):
        p = Pins(bits(0x32))
        self.assertEqual(Converters(p, lambda _: None).adc_transfer(1), 0x32)
        release = p.events.index(("direction", SDIO, False))
        self.assertEqual(p.events[release-1], ("write", ADC_SCLK, 1))
        self.assertEqual(p.events[release+1], ("write", ADC_SCLK, 0))
        reads = [e for e in p.events if e[0] == "read"]
        self.assertTrue(all(e[2][ADC_SCLK] == 0 for e in reads))
        self.assertEqual(p.levels[ADC_CS], 1)
        self.assertEqual(p.events[-1], ("direction", SDIO, True))

    def test_failed_adc_read_ends_bus_transaction(self):
        p = Pins()
        with self.assertRaisesRegex(RuntimeError, "queue"):
            Converters(p, lambda _: None).adc_transfer(1)
        self.assertEqual(p.levels[ADC_CS], 1)
        self.assertEqual(p.events[-1], ("direction", SDIO, True))


if __name__ == "__main__": unittest.main()
