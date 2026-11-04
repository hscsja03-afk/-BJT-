"""Regression for stable PNP plateaus rejected by raw noise, 2026-11-03."""
import json
import statistics
import unittest
from pathlib import Path

from zynq_bjt.characteristics import OutputScanConfig, BetaScanConfig
from zynq_bjt.frontend import Calibration, Frontend
from zynq_bjt.mmio import Frame
from zynq_bjt.profiles import defaults_for
from zynq_bjt.pulse import plateau, PlateauRejected

ROOT = Path(__file__).resolve().parents[1]


class PnpPulseNoiseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cal = Calibration(ROOT/'data')
        cls.recorded = json.loads((ROOT/'sim/fixtures/pnp_pulse_noisy_plateau.json').read_text())

    def test_recorded_high_plateaus_pass_without_changing_retained_samples(self):
        cfg = OutputScanConfig(profile='pnp_big', scan_mode='脉冲')
        for item in self.recorded['frames']:
            frame = Frame(**item['frame'])
            if item['repeat'] == 1:
                with self.assertRaisesRegex(PlateauRejected, '尚未取得完整高电平帧'):
                    plateau(frame, self.cal, cfg, .54)
                continue
            means, selection = plateau(frame, self.cal, cfg, .54)
            self.assertEqual(selection['retained_samples_per_channel'], 450)
            for channel in (0, 1):
                self.assertEqual(means[channel], statistics.fmean(sorted(frame.codes(channel)[359:921])[56:-56]))
            old_cfg = OutputScanConfig(profile='pnp_big', pulse_noise_span_v=.02)
            if item['repeat'] == 12:
                plateau(frame, self.cal, old_cfg, .54)
            else:
                with self.assertRaisesRegex(PlateauRejected, '帧内噪声跨度超限'):
                    plateau(frame, self.cal, old_cfg, .54)

    def frame(self, nodes):
        words = []
        for cal in (self.cal.rx1, self.cal.rx2):
            words.append(tuple(round(v*.206*1e9/cal['slope_nv_per_code']+cal['zero_code_q16']/65536) for v in nodes))
        return Frame(1, tuple(words), (195312.5,)*2, 0)

    def test_noise_allowance_does_not_accept_edges_drift_low_or_excess_noise(self):
        cfg = OutputScanConfig(profile='pnp_big', scan_mode='脉冲')
        cases = [([0]*1024, '完整高电平'),
                 ([0]*512+[.54]*512, '完整高电平'),
                 ([.54]*512+[.57]*512, '平台未稳定'),
                 ([.54+i*.000015 for i in range(1024)], '仍在漂移'),
                 ([.54+(.03 if i%2 else -.03) for i in range(1024)], '噪声跨度超限')]
        for nodes, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(PlateauRejected, reason):
                plateau(self.frame(nodes), self.cal, cfg, .54)
        plateau(self.frame([.54+(.013 if i%2 else -.013) for i in range(1024)]), self.cal, cfg, .54)

    def test_profile_defaults_and_invalid_limits_fail(self):
        frontend = Frontend.load(ROOT/'data/frontend.json')
        for measurement, cls in [('output', OutputScanConfig), ('beta', BetaScanConfig)]:
            for profile in ('npn_small', 'npn_big', 'pnp_small', 'pnp_big'):
                expected = {'npn_big':.03,'pnp_big':.04}.get(profile,.02)
                self.assertEqual(cls(profile=profile).pulse_noise_span_v, expected)
                self.assertEqual(defaults_for(measurement, cls, profile)['pulse_noise_span_v'], expected)
            for value in (float('nan'), float('inf'), 0, .201):
                with self.assertRaisesRegex(ValueError, '噪声跨度'):
                    cls(profile='pnp_big', scan_mode='脉冲', pulse_noise_span_v=value).validate(self.cal, frontend)
