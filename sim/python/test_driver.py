"""Behavioral tests exercise actual conversion and AXI transaction decisions."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/python"))
from zynq_bjt import AddaCore, Calibration, Frontend

ROOT = Path(__file__).resolve().parents[2]


class VirtualTime:
    def __init__(self): self.now = 0.0
    def clock(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Registers:
    def __init__(self):
        self.values = {0: 0x41444441, 0x20: 1024, 0x44: 0x54583101,
                       0x48: 0x47504901, 0x80: 0x41574701, 0x30: 250000000,
                       0x4c: 0x1515, 0x54: 7, 0xc: 0x10}
        self.writes = []
        self.complete = True
    def read(self, address):
        if address==0xc4 and address not in self.values:
            raise AssertionError('Legacy unmapped register must never be probed')
        if 0x1000 <= address < 0x2000: return 32000 + (address - 0x1000) // 4
        if 0x2000 <= address < 0x3000: return 34000 + (address - 0x2000) // 4
        return self.values.get(address, 0)
    def write(self, address, value):
        self.writes.append((address, value))
        if address == 0x50:
            mask = (value >> 8) & 127
            new = (self.values[0x4c] & 127 & ~mask) | (value & mask)
            self.values[0x4c] = new | (new << 8)
        if address == 8:
            self.values[0xc] = 0x13 if self.complete else 0x18
        self.values[address] = value


class Tests(unittest.TestCase):
    def test_long_capture_reads_real_contiguous_ram_and_rejects_legacy_depth(self):
        regs=Registers();regs.values.update({0xc:0xa0000010,0xc4:0x53435001,0xcc:4096})
        original=regs.read
        def read(address):
            if 0x8000<=address<0xc000:return 20000+(address-0x8000)//4
            if 0x4000<=address<0x8000:return 10000+(address-0x4000)//4
            return original(address)
        regs.read=read
        frame=AddaCore(regs).capture((50e6,)*2,sample_count=4096,sample_stride=20)
        self.assertEqual(frame.codes(0)[-1],24095);self.assertEqual(frame.codes(1)[-1],14095)
        self.assertEqual(len(frame.words[0]),4096);self.assertEqual(frame.sample_rates_hz,(2.5e6,)*2)
        self.assertIn((0xd0,4096),regs.writes)
        legacy=Registers()
        with self.assertRaises(RuntimeError):AddaCore(legacy).capture((50e6,)*2,sample_count=4096)
        self.assertEqual(legacy.writes,[])

    def test_clock_rates_exclude_sequential_mmio_read_latency(self):
        regs=Registers();timer=VirtualTime();original=regs.read
        def read(address):
            if address in (0x24,0x28,0x2c):
                timer.sleep(.0001)
                return round(timer.now*50e6)&0xffffffff
            return original(address)
        regs.read=read
        rates=AddaCore(regs,clock=timer.clock,pause=timer.sleep).clock_rates()
        for rate in rates:self.assertAlmostEqual(rate,50e6,places=4)

    def test_raw_record_preserves_all_words_fault_bits_and_stride_metadata(self):
        from zynq_bjt.mmio import Frame
        from dataclasses import asdict
        import json
        frame=Frame(7,((0x1ffff,)*1024,(12345,)*1024),(2.5e6,2.5e6),123.0,
                    adc_sample_rates_hz=(50e6,50e6),sample_stride=20)
        self.assertEqual(json.dumps(frame.as_record()),json.dumps(asdict(frame)))
        decoded=json.loads(json.dumps(frame.as_record()))
        self.assertEqual(decoded['words'][0][-1],0x1ffff)
        self.assertEqual(decoded['sample_stride'],20)
        self.assertEqual(decoded['adc_sample_rates_hz'],[50e6,50e6])

    def test_identity_failure_is_read_only(self):
        regs = Registers(); regs.values[0] = 0
        with self.assertRaises(ValueError): AddaCore(regs)
        self.assertEqual(regs.writes, [])

    def test_physical_adc_order_and_complete_frame(self):
        regs = Registers(); core = AddaCore(regs)
        frame = core.capture((125000000, 125000000))
        self.assertEqual(frame.codes(0)[0], 34000)  # RX1 RAM B
        self.assertEqual(frame.codes(1)[0], 32000)  # RX2 RAM A
        self.assertEqual(frame.codes(0)[-1], 35023)
        self.assertFalse(frame.starts_aligned)

    def test_stopped_adc_times_out_instead_of_reusing_previous_data(self):
        regs = Registers(); regs.complete = False
        timer = VirtualTime(); core = AddaCore(regs, clock=timer.clock, pause=timer.sleep)
        with self.assertRaises(TimeoutError): core.capture((125000000,)*2, .01)
        self.assertEqual(core.sequence, 0)

    def test_single_rx1_read_does_not_access_adc1_rx2_ram(self):
        regs=Registers(); read=regs.read; ram_reads=[]
        def selected_read(address):
            if 0x1000 <= address < 0x2000:
                raise AssertionError('Unused ADC1/RX2 RAM must not be read')
            if 0x2000 <= address < 0x3000:ram_reads.append(address)
            return read(address)
        regs.read=selected_read;core=AddaCore(regs)
        frame=core.capture((50e6,50e6),channels=(0,))
        self.assertEqual(len(ram_reads),1024)
        self.assertEqual(frame.captured_channels,(0,))
        self.assertEqual(frame.words[1],())
        self.assertEqual(frame.codes(0)[0],34000)
        with self.assertRaisesRegex(ValueError,'not read'):frame.codes(1)
        before=list(regs.writes)
        for channels in ((),(2,),(0,0),(True,)):
            with self.assertRaises(ValueError):core.capture((50e6,50e6),channels=channels)
        self.assertEqual(regs.writes,before)

    def test_long_window_requires_capability_and_restores_stride_for_normal_capture(self):
        regs=Registers();core=AddaCore(regs)
        with self.assertRaisesRegex(RuntimeError,'长窗口需要配套示波器位流'):core.capture((50e6,)*2,sample_stride=20)
        self.assertEqual(regs.writes,[])
        regs.values[0xc4]=0x53435001;regs.values[0xc]=0x80000010
        long=core.capture((50e6,)*2,sample_stride=20)
        self.assertEqual(long.sample_rates_hz,(2.5e6,)*2)
        self.assertEqual(long.adc_sample_rates_hz,(50e6,)*2)
        self.assertAlmostEqual(1023/long.sample_rates_hz[0],.0004092)
        regs.values[0xc]|=0x80000000
        core.capture((50e6,)*2)
        self.assertEqual(regs.values[0xc8],1)

    def test_gpio_mask_preserves_other_relays(self):
        regs = Registers(); result = AddaCore(regs).gpio(0x60, 0x40)
        self.assertEqual(result["output"], 0x55)
        self.assertEqual(regs.writes, [(0x50, 0x6040)])

    def test_awg_does_not_enable_analog_output(self):
        regs = Registers(); AddaCore(regs).awg(1, [32768]*256, 1000000)
        self.assertEqual(len([a for a, v in regs.writes if 0x4000 <= a < 0x4400]), 256)
        self.assertIn((0x90, round(1000000 / 250000000 * 2**32)), regs.writes)
        self.assertEqual(regs.writes[-1], (0x88, 2))

    def test_awg_rejects_unlocked_clock_before_writing(self):
        regs = Registers(); regs.values[0xc] = 0
        with self.assertRaises(RuntimeError): AddaCore(regs).awg(0, [32768]*256)
        self.assertEqual(regs.writes, [])

    def test_attenuation_and_drive_are_separate_paths(self):
        f = Frontend()
        self.assertAlmostEqual(f.vc_from_rx1(1), 1/.206)
        self.assertAlmostEqual(f.tx2_for_uce(3), .5)
        other = Frontend(rx1_per_vc=.25)
        self.assertAlmostEqual(other.vc_from_rx1(1), 4)
        self.assertAlmostEqual(other.tx2_for_uce(3), .5)
        self.assertAlmostEqual(f.ib_estimate(.02), 1e-7)

    def test_historical_calibration_polarity_and_quantization(self):
        c = Calibration(ROOT / "data")
        for ch, p in enumerate((c.rx1, c.rx2)):
            zero = p["zero_code_q16"] / 65536
            code = zero + 1e9 / p["slope_nv_per_code"]
            self.assertAlmostEqual(c.port_v(code, ch), 1)
        tx1, nominal = c.dac_code(0, .02)
        self.assertEqual(tx1, 33)
        self.assertAlmostEqual(nominal, 33*2.5/4096)
        for volts in (0, .013, .6, 1.8):
            code, actual = c.dac_code(1, volts)
            self.assertLess(abs(actual-volts), .0001)
        with self.assertRaises(ValueError): c.dac_code(1, 1.81)


if __name__ == "__main__": unittest.main()
