"""Regression for early NPN pulse failures using recorded ADC words."""
from dataclasses import replace
import json
from pathlib import Path
import statistics
import tempfile
import unittest

from zynq_bjt.characteristics import OutputScanConfig
from zynq_bjt.frontend import Calibration
from zynq_bjt.mmio import Frame
from zynq_bjt.page_defaults import load_defaults, save_default
from zynq_bjt.pulse import plateau, PlateauRejected

ROOT = Path(__file__).resolve().parents[1]


class NpnPulseNoiseTests(unittest.TestCase):
    def setUp(self):
        self.saved = json.loads((ROOT/'sim/fixtures/npn_pulse_noisy_plateau.json').read_text(encoding='utf-8'))
        self.cal = Calibration(ROOT/'data')
        for attr,value in self.saved['calibration'].items():
            setattr(self.cal,attr,value)
        self.cfg = OutputScanConfig(profile='npn_big',scan_mode='脉冲')

    def test_recorded_stable_frame_no_longer_starves_scan(self):
        frame = Frame(**self.saved['frame'])
        with self.assertRaisesRegex(PlateauRejected,'RX2帧内噪声跨度超限'):
            plateau(frame,self.cal,replace(self.cfg,pulse_noise_span_v=.02),self.saved['expected_source_v'])
        means,info = plateau(frame,self.cal,self.cfg,self.saved['expected_source_v'])
        self.assertEqual(info['retained_samples_per_channel'],450)
        for ch in (0,1):
            self.assertEqual(means[ch],statistics.fmean(sorted(frame.codes(ch)[359:921])[56:-56]))

    def test_edges_drift_and_excess_noise_are_still_rejected(self):
        def frame(nodes):
            words = [tuple(round(v*.206*1e9/cal['slope_nv_per_code']+cal['zero_code_q16']/65536)
                           for v in nodes) for cal in (self.cal.rx1,self.cal.rx2)]
            return Frame(1,tuple(words),(195312.5,)*2,0)
        for nodes,reason in [([0]*1024,'完整高电平'),
                             ([0]*512+[.24]*512,'完整高电平'),
                             ([.24]*512+[.27]*512,'平台未稳定'),
                             ([.24+i*.000015 for i in range(1024)],'仍在漂移'),
                             ([.24+(.02 if i%2 else -.02) for i in range(1024)],'噪声跨度超限')]:
            with self.subTest(reason=reason),self.assertRaisesRegex(PlateauRejected,reason):
                plateau(frame(nodes),self.cal,self.cfg,.24)

    def test_saved_custom_noise_setting_is_not_silently_overridden(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'defaults.json'
            measurements = {'output':(OutputScanConfig,)}
            self.assertEqual(load_defaults(path,'npn_big',measurements)['output']['pulse_noise_span_v'],.03)
            save_default(path,'npn_big','output',{'pulse_noise_span_v':.018})
            self.assertEqual(load_defaults(path,'npn_big',measurements)['output']['pulse_noise_span_v'],.018)
