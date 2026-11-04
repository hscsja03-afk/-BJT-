"""Rejected PS configuration must not replace PL or acquire any GPIO lines."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import hashlib
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/python'))
from zynq_bjt.runtime import Board
from zynq_bjt.mio import Mio, PINS
from zynq_bjt.converters import DATA_OE, CTRL_OE


class InitializationTests(unittest.TestCase):
    def make_board(self, rates):
        states = {}
        pins = Mock(write=Mock(side_effect=lambda pin, value: states.update({pin: value})))
        core = Mock(io=Mock(read=Mock(side_effect={0x30: 50000000, 0xc: 16}.__getitem__)))
        board = Board(core, pins, pause=Mock())
        board.spi = Mock()
        board.tx1 = Mock()
        board.digital_self_test = Mock()
        def init_adc():
            self.assertEqual(states[CTRL_OE], 0)
            self.assertEqual(states[DATA_OE], 1)
        board.spi.init_adc.side_effect = init_adc
        def clock_rates():
            board.spi.init_adc.assert_called_once_with()
            self.assertEqual(states[DATA_OE], 0)
            self.assertEqual(states[CTRL_OE], 0)
            board.pause.assert_called_with(.001)
            board.digital_self_test.assert_not_called()
            return rates
        core.clock_rates.side_effect = clock_rates
        return board, states

    def test_clock_check_follows_adc_and_data_path_enable(self):
        board, states = self.make_board((50000000.,)*3)
        result = board.initialize()
        self.assertEqual(result['digital_self_test'], 'passed')
        self.assertTrue(board.initialized)
        board.digital_self_test.assert_called_once_with()
        board.tx1.initialize_muted.assert_called_once_with()
        board.spi.init_dac_muted.assert_called_once_with()
        board.spi.mute.assert_called_once_with(0)

    def test_bad_clock_disables_enabled_adc_path_and_mutes_outputs(self):
        board, states = self.make_board((0., 0., 50000000.))
        with self.assertRaisesRegex(RuntimeError, 'Clock profile mismatch'):
            board.initialize()
        self.assertFalse(board.initialized)
        self.assertFalse(board.adc_ready)
        self.assertEqual(states[CTRL_OE], 1)
        self.assertEqual(states[DATA_OE], 1)
        board.spi.mute.assert_called_once_with(0)
        board.tx1.verified.assert_called_once_with(3, 1)
        board.digital_self_test.assert_not_called()

    def test_dac125_profile_uses_divider_eight_with_adc_fifty(self):
        board,states=self.make_board((50000000.,50000000.,125000000.))
        board.core.io.read.side_effect={0x30:125000000,0xc:16}.__getitem__
        result=board.initialize()
        self.assertEqual(result['adc_divider'],20)
        self.assertEqual(result['dac_divider'],8)
        board.digital_self_test.assert_called_once_with()

    def test_old_overlay_rejects_high_adc_clock_before_any_write(self):
        board, states = self.make_board((50000000.,)*3)
        with self.assertRaisesRegex(ValueError, 'compiled timing'):
            board.initialize(adc_divider=16)
        self.assertEqual(states, {})
        board.core.io.write.assert_not_called()
        board.spi.init_clocks.assert_not_called()

    def test_new_overlay_accepts_qualified_rate_and_waits_for_both_locks(self):
        board, _ = self.make_board((62500000.,62500000.,125000000.))
        board.core.io.read.side_effect={0x30:125000000,0xc:0x10000010,0xd4:16,0xd8:3}.__getitem__
        board.core.wait.side_effect=lambda predicate, timeout:self.assertTrue(predicate())
        result=board.initialize(adc_divider=16)
        self.assertEqual(result['adc_divider'],16)
        board.spi.init_clocks.assert_called_once_with(16,8)
        self.assertEqual(board.core.wait.call_count,2)

    def test_adc_unlock_rejects_frames_and_statistics(self):
        board, _ = self.make_board((62500000.,62500000.,125000000.))
        board.adc_ready=True
        board.core.io.read.side_effect={0xc:0x10000010,0xd8:1}.__getitem__
        for action in (board.capture,lambda:board.capture_statistics(50000)):
            with self.assertRaisesRegex(RuntimeError,'ADC clock lost lock'):action()
        board.core.capture.assert_not_called()
        board.core.capture_statistics.assert_not_called()


class SineOutputTests(unittest.TestCase):
    def test_other_bitstream_is_rejected_before_awg_write(self):
        from zynq_bjt.frontend import Calibration
        board=Board(Mock(),Mock(),pause=Mock());board.initialized=True
        board.identity={'bit_sha256':'other-bit'}
        cal=Calibration.__new__(Calibration);cal.tx3_waveforms={'bitstream_sha256':'measured-bit'}
        with self.assertRaisesRegex(ValueError,'位流不匹配'):board.set_sine(2,cal,5000000,.07)
        board.core.awg.assert_not_called()

    def test_calibration_from_other_dac_rate_is_rejected_before_awg_write(self):
        board = Board(Mock(), Mock(), pause=Mock())
        board.initialized = True
        board.core.io.read.return_value = 250000000
        cal = Mock(dac={"channels": [{}, {}, {"sine_50mv": {"dac_sample_rate_hz": 50000000}}]})
        with self.assertRaisesRegex(ValueError, "different DAC sample rate"):
            board.set_sine(2, cal, 100000, .05)
        board.core.awg.assert_not_called()

    def test_frequency_compensation_and_dc_to_sine_restore_actual_table(self):
        board = Board(Mock(), Mock(), pause=Mock())
        board.initialized = True
        board.output = Mock()
        cal = Mock(dac={"channels": [{}, {}, {"sine_50mv": {"zero_code": 32400}}]})
        # Same requested Vpp needs different codes at different frequencies.
        cal.sine_samples.side_effect = [[32400, 32800]*128, [32400, 32820]*128,
                                       [32400, 32820]*128]
        board.set_sine(2, cal, 10000, .05)
        board.set_sine(2, cal, 6000000, .05)
        self.assertNotEqual(board.core.awg.call_args_list[0].args[1],
                            board.core.awg.call_args_list[1].args[1])
        board.set_code(2, 32768)
        board.set_sine(2, cal, 6000000, .05)
        self.assertEqual(board.core.awg.call_args.args[1], [32400, 32820]*128)
        self.assertEqual(board.core.awg.call_args.kwargs, {"frequency_hz": 6000000})
        self.assertEqual(board.codes[2], 32400)
        board.core.awg_frequency.assert_not_called()


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bit = Path(self.temp.name) / 'bjt.bit'
        self.bit.write_bytes(b'test bitstream')
        self.bit.with_suffix('.hwh').write_bytes(b'test metadata')
        self.pinregs = {4*p: (3 if p < 16 else 1) << 9 for p in PINS}
        self.slcr = Mock(read=Mock(side_effect=lambda offset: self.pinregs[offset]))
        self.regs = Mock(read=Mock(side_effect={
            0: 0x41444441, 0x20: 1024, 0x44: 0x54583101,
            0x48: 0x47504901, 0x80: 0x41574701}.__getitem__))
        self.overlay = Mock(ip_dict={'adda_core_0': {'phys_addr': 0x43c00000, 'addr_range': 0x10000}},
                            adda_core_0=SimpleNamespace(mmio=self.regs))
        self.pynq = SimpleNamespace(Overlay=Mock(return_value=self.overlay),
                                   MMIO=Mock(return_value=self.slcr),
                                   GPIO=SimpleNamespace(get_gpio_base=lambda: 906))
        self.context = patch.dict(sys.modules, {'pynq': self.pynq})
        self.context.start()
        self.addCleanup(self.context.stop)

    def test_wrong_mux_or_voltage_rejected_before_program_and_claim(self):
        for value in (0x602, 0x200):
            with self.subTest(register=value):
                self.pinregs[4*7] = value
                with patch.object(Mio, 'from_pynq') as claim, patch.object(Path, 'write_text') as write:
                    with self.assertRaisesRegex(RuntimeError, 'MIO7 mux or IO voltage'):
                        Board.from_pynq(self.bit, program=True)
                claim.assert_not_called(); write.assert_not_called()
                self.overlay.download.assert_not_called()

    def test_owned_gpio_rejected_before_program(self):
        original_exists = Path.exists
        def exists(path):
            return path.name == 'gpio913' or original_exists(path)
        with patch.object(Path, 'exists', exists), patch.object(Mio, 'from_pynq') as claim:
            with self.assertRaisesRegex(RuntimeError, 'already exported'):
                Board.from_pynq(self.bit, program=True)
        claim.assert_not_called(); self.overlay.download.assert_not_called()

    def test_valid_ps_setup_programs_and_returns_explicit_uninitialized_session(self):
        pins = Mock()
        def download():
            self.assertEqual([c.args[0] for c in self.slcr.read.call_args_list], [p*4 for p in PINS])
            pins.write.assert_not_called()
        self.overlay.download.side_effect = download
        with patch.object(Mio, 'from_pynq', return_value=pins):
            board = Board.from_pynq(self.bit, program=True)
        self.pynq.Overlay.assert_called_once_with(str(self.bit.resolve()), download=False)
        self.pynq.MMIO.assert_called_once_with(0xf8000700, 0x100)
        self.overlay.download.assert_called_once_with()
        self.assertFalse(board.initialized)
        self.assertEqual(board.identity['bit_sha256'], hashlib.sha256(self.bit.read_bytes()).hexdigest())
        self.regs.write.assert_not_called(); pins.close.assert_not_called()

    def test_loaded_overlay_still_requires_valid_ps_without_reprogramming(self):
        self.overlay.is_loaded.return_value = True
        self.pinregs[4*33] = 0x600
        with patch.object(Mio, 'from_pynq') as claim:
            with self.assertRaisesRegex(RuntimeError, 'MIO33'):
                Board.from_pynq(self.bit)
        self.overlay.download.assert_not_called(); claim.assert_not_called()

    def test_constructor_failure_releases_claimed_gpio(self):
        class FailingBoard(Board):
            def __init__(self, core, pins):
                raise RuntimeError('session setup failed')
        pins = Mock()
        with patch.object(Mio, 'from_pynq', return_value=pins):
            with self.assertRaisesRegex(RuntimeError, 'session setup failed'):
                FailingBoard.from_pynq(self.bit, program=True)
        pins.close.assert_called_once_with()


if __name__ == '__main__': unittest.main()
