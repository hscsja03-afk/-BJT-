"""Voltage display must preserve polarity and reject invalid/partial frames."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration
from zynq_bjt.scope_display import reference_channels


class ScopeDisplayTests(unittest.TestCase):
    def setUp(self):
        self.cal = Calibration(ROOT/'data')

    def frame(self, a, b):
        return dict(words=[a, b], sample_rates_hz=[50_000_000]*2, simulated=False)

    def test_input_polarities_and_no_qualification_from_conversion(self):
        a, b = reference_channels(self.frame([29152, 29215], [54710, 54989]), self.cal)
        self.assertGreater(a['reference_volts'][0], a['reference_volts'][1])
        self.assertLess(b['reference_volts'][0], b['reference_volts'][1])
        self.assertAlmostEqual(a['reference_volts'][0], .2066970619, places=6)
        for channel in (a, b):
            self.assertFalse(channel['voltage_qualified'])
            self.assertEqual(channel['capture_sample_rate_hz'], 50_000_000)
        self.assertEqual(a['profile_sample_rate_hz'],50_000_000)
        self.assertTrue(a['nominal_dc_calibrated'])
        self.assertEqual(b['profile_sample_rate_hz'],50_000_000)
        self.assertTrue(b['nominal_dc_calibrated'])

    def test_current_nominal_profile_refuses_wrong_rate(self):
        frame=self.frame([32571],[32884]);frame['sample_rates_hz']=[125000000]*2
        for ch in reference_channels(frame,self.cal):
            self.assertIsNone(ch['mean_v'])
            self.assertEqual(ch['voltage_basis'],'profile_rate_mismatch')

    def test_overrange_never_averages_only_remaining_good_samples(self):
        a, _ = reference_channels(self.frame([29152, 29215 | 65536], [54710, 54989]), self.cal)
        self.assertEqual(a['overrange'], 1)
        self.assertIsNone(a['reference_volts'][1])
        self.assertIsNone(a['mean_v'])
        self.assertIsNone(a['vpp_v'])

    def test_no_extrapolation_outside_historical_positive_range(self):
        a, b = reference_channels(self.frame([65535], [0]), self.cal)
        for channel in (a, b):
            self.assertEqual(channel['reference_volts'], [None])
            self.assertIsNone(channel['mean_v'])


if __name__ == '__main__':
    unittest.main()
