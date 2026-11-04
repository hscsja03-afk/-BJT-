from pathlib import Path
import unittest
from unittest.mock import Mock

from zynq_bjt.frontend import Calibration
from zynq_bjt.runtime import Board

ROOT = Path(__file__).resolve().parents[1]


class Tx3CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.cal = Calibration(ROOT/'data')
        self.entry = self.cal.tx3_waveforms['compatible_bitstreams'][0]
        self.identity = dict(bit_sha256=self.entry['bitstream_sha256'],
                             hwh_sha256=self.entry['hwh_sha256'], dac_divider=8)

    def test_native_lcd_uses_same_codes_with_explicit_reference_provenance(self):
        for shape in ('sine','square','triangle'):
            for frequency in (10000,100000,1000000):
                original = self.cal.waveform_parameters(shape,frequency,.05)
                bound = self.cal.bind_waveform_plan(original,self.identity)
                self.assertEqual(bound['amplitude_basis'],'compatible_bitstream_reference_unverified')
                self.assertEqual(bound['reference_amplitude_basis'],original['amplitude_basis'])
                self.assertFalse(bound['bitstream_reference']['analog_recalibrated'])
                for key in ('zero_code','peak_codes','dac_sample_rate_hz'):
                    self.assertEqual(bound[key],original[key])
        self.assertNotEqual(self.cal.tx3_waveforms['bitstream_sha256'],self.identity['bit_sha256'])
        measured = self.cal.bind_waveform_plan(original,{'bit_sha256':self.cal.tx3_waveforms['bitstream_sha256']})
        self.assertEqual(measured['amplitude_basis'],original['amplitude_basis'])

    def test_unknown_bit_wrong_hwh_missing_clock_and_wrong_clock_stay_locked(self):
        for changes in ({'bit_sha256':'unknown'}, {'hwh_sha256':'unknown'}, {'hwh_sha256':None},
                        {'dac_divider':20}, {'dac_divider':None}):
            board = Board(Mock(),Mock(),pause=Mock());board.initialized=True
            board.identity = dict(self.identity,**changes)
            with self.assertRaisesRegex(ValueError,'位流不匹配'):
                board.set_sine(2,self.cal,100000,.05)
            board.core.awg.assert_not_called()
        self.cal.tx3_waveforms['compatible_bitstreams'][0]['source_bitstream_sha256']='unrelated'
        with self.assertRaisesRegex(ValueError,'位流不匹配'):
            self.cal.validate_waveform_identity(self.identity)

    def test_native_lcd_runtime_programs_the_original_sine_table(self):
        board = Board(Mock(),Mock(),pause=Mock());board.initialized=True
        board.identity = self.identity
        board.core.io.read.return_value=125000000
        board.output=Mock()
        for frequency in (10000,100000,1000000,5000000):
            board.set_sine(2,self.cal,frequency,.05)
            self.assertEqual(board.core.awg.call_args.args[1],self.cal.sine_samples(frequency,.05))
        board.core.io.read.return_value=50000000
        board.core.awg.reset_mock()
        with self.assertRaisesRegex(ValueError,'different DAC sample rate'):
            board.set_sine(2,self.cal,100000,.05)
        board.core.awg.assert_not_called()
