import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from zynq_bjt.desktop import App


class PulseTimingUiTests(unittest.TestCase):
    def test_timing_edits_survive_page_switch_defaults_and_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=tk.Tk()
            try:
                app=App(root,workspace=folder);app.enter_workbench();app.show_page('output')
                app.profile.set('NPN 大功率');app.change_profile()
                app.config_vars['scan_mode'].set('脉冲')
                app.config_vars['pulse_frequency_hz'].set('5')
                app.config_vars['pulse_duty_percent'].set('30')
                app.config_vars['pulse_attempts_per_frame'].set('40')
                app.config_vars['pulse_noise_span_v'].set('0.035')
                app.save_page_default();app.show_page('input');app.show_page('output')
                cfg=app.read_config()
                self.assertEqual((cfg['pulse_frequency_hz'],cfg['pulse_duty_percent'],cfg['pulse_attempts_per_frame']),(5,30,40))
                self.assertEqual(cfg['pulse_noise_span_v'],.035)
                saved=json.loads((Path(folder)/'measurement_defaults.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['npn_big']['output']['pulse_frequency_hz'],5)
                self.assertEqual(saved['npn_big']['output']['pulse_noise_span_v'],.035)
                app.set_summary(dict(method='pulse',config=cfg,status='complete',simulated=True))
                self.assertIn('5 Hz / 30%',app.summary.get('1.0','end'))
            finally:
                for task in root.tk.call('after','info'):root.tk.call('after','cancel',task)
                root.destroy()
