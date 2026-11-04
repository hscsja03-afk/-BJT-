import importlib.util
import tempfile
import unittest
from pathlib import Path

from zynq_bjt.ac import AcScanConfig, run_ac_scan
from zynq_bjt.characteristics import (BetaScanConfig, OutputScanConfig,
                                      run_beta_scan, run_output_scan)
from zynq_bjt.frontend import Calibration, Frontend
from zynq_bjt.notebook import NpnNotebook
from zynq_bjt.simulation import SimulatedBoard


ROOT = Path(__file__).resolve().parents[3]


class CharacteristicScanTests(unittest.TestCase):
    def setUp(self):
        self.calibration = Calibration(ROOT / "data")
        self.frontend = Frontend.load(ROOT / "data" / "frontend.json")

    def test_output_defaults_use_explicit_provisional_unity_vcc_feedback(self):
        OutputScanConfig().validate(self.calibration,self.frontend)
        BetaScanConfig().validate(self.calibration,self.frontend)
        self.assertEqual(OutputScanConfig().source_adc_per_v,.206)
        with self.assertRaisesRegex(ValueError, "measured ADC source-feedback"):
            OutputScanConfig(source_adc_per_v=0).validate(self.calibration, self.frontend)
        with self.assertRaisesRegex(ValueError, "measured ADC source-feedback"):
            BetaScanConfig(source_adc_per_v=0).validate(self.calibration, self.frontend)

    def test_output_scan_mutes_outputs_restores_gpio_and_records_early_analysis(self):
        board = SimulatedBoard(self.calibration, self.frontend)
        board.gpio_value = 0x02
        with tempfile.TemporaryDirectory() as temporary:
            directory, state = run_output_scan(board, self.calibration, self.frontend,
                OutputScanConfig(base_control_v=(0.05, 0.15), tx2_control_stop_v=0.2,
                                 tx2_control_step_v=0.1, source_adc_per_v=0.4,
                                 settle_s=0), temporary)
            self.assertEqual(state["status"], "complete", state.get("error"))
            self.assertTrue((directory / "output_points.csv").is_file())
            self.assertEqual(board.gpio_value, 0x02)
            self.assertFalse(any(board.enabled))
            self.assertEqual(board.display_lines[-1], "OUTPUTS MUTED")

    def test_beta_scan_uses_project_source_target_and_restores_hardware_state(self):
        board = SimulatedBoard(self.calibration, self.frontend)
        board.gpio_value = 0x02
        with tempfile.TemporaryDirectory() as temporary:
            config = BetaScanConfig(tx1_start_v=0.05, tx1_stop_v=0.13, tx1_step_v=0.04,
                                    drop_initial_points=0, moving_average_window=1,
                                    source_adc_per_v=0.4, tx2_stop_v=.6, target_uce_v=1.2,tx2_first_start_v=.24,settle_s=0, frames_per_point=2)
            directory, state = run_beta_scan(board, self.calibration, self.frontend,
                                               config, temporary)
            self.assertEqual(state["status"], "complete", state.get("error"))
            self.assertEqual(state["beta"]["dropped_initial_base_curves"], 0)
            self.assertGreaterEqual(state["beta"]["point_count"], 2)
            self.assertEqual(len(state["beta"]["fit_inlier_mask"]),
                             state["beta"]["fit_point_count"])
            self.assertEqual(state["measurement_name"], "NPN output beta linearity")
            self.assertEqual(state["linearity_method"]["target_uce_v"], 1.2)
            self.assertEqual(state["source_parameters"]["analog_outputs_enabled_during_scan"], [0, 1])
            self.assertEqual(state["gpio_pin_by_bit"][6], 48)
            self.assertEqual(state["source_parameters"]["gpio_pin_values"][85], 0)
            self.assertEqual(board.display_lines[1], "BETA COMPLETE")
            self.assertTrue(board.display_lines[2].startswith("LIN "))
            self.assertTrue((directory / "beta_points.csv").is_file())
            self.assertTrue((directory / "beta_trace.csv").is_file())
            self.assertEqual(board.gpio_value, 0x02)
            self.assertFalse(any(board.enabled))

    def test_beta_default_spans_49_currents_and_records_selection(self):
        board=SimulatedBoard(self.calibration,self.frontend)
        cfg=BetaScanConfig(settle_s=0,frames_per_point=2)
        values=cfg.validate(self.calibration,self.frontend)
        self.assertEqual(len(values),49)
        self.assertEqual((values[0],values[-1]),(.02,.5))
        with tempfile.TemporaryDirectory() as temporary:
            _,state=run_beta_scan(board,self.calibration,self.frontend,cfg,temporary)
        self.assertEqual(state['status'],'complete',state.get('error'))
        self.assertEqual(state['beta_selection']['planned_base_points'],49)
        selected=state['beta_selection']['selected_points']
        self.assertGreater(selected,15)
        self.assertEqual(state['config']['target_uce_v'],5)
        self.assertEqual(selected+len(state['beta_selection']['skipped_points']),49)
        self.assertEqual(state['beta']['point_count'],selected-2)
        self.assertEqual(state['beta']['fit_point_count'],selected-3)
        self.assertFalse(any(board.enabled))

    def test_ac_scan_uses_long_statistics_window_and_restores_outputs(self):
        board = SimulatedBoard(self.calibration, self.frontend)
        board.gpio_value = 0x02
        config = AcScanConfig(sample_count=50000, repeat_count=2, settle_s=0,
                              max_bisection_iterations=3)
        with tempfile.TemporaryDirectory() as temporary:
            directory, state = run_ac_scan(board, self.calibration, self.frontend,
                                           config, temporary)
            self.assertEqual(state["status"], "complete", state.get("error"))
            self.assertEqual(state["config"]["input_channel"], 0)  # RX1: base
            self.assertEqual(state["config"]["output_channel"], 1)  # RX2: collector
            self.assertEqual(state["source_parameters"]["low_frequency_cycles_at_50msps"], 10.0)
            self.assertEqual(state["source_parameters"]["gpio_mask"], 0x7f)
            self.assertEqual(state["source_parameters"]["gpio_value"], 0x02)
            self.assertEqual(state["source_parameters"]["gpio_pin_values"],
                             {87: 0, 85: 1, 83: 0, 81: 0, 79: 0, 77: 0, 48: 0})
            self.assertAlmostEqual(state["ac_analysis"]["au"], 100.0, delta=2.0)
            self.assertAlmostEqual(state["ac_analysis"]["ft_hz"],
                                   state["ac_analysis"]["au"] *
                                   state["ac_analysis"]["f_beta_hz"])
            self.assertTrue((directory / "points.csv").is_file())
            self.assertEqual(board.display_lines[1], "AC COMPLETE")
            self.assertTrue(board.display_lines[2].startswith("fB "))
            self.assertEqual(board.gpio_value, 0x02)
            self.assertFalse(any(board.enabled))

    def test_ac_releases_outputs_and_gpio_before_fit_even_if_analysis_fails(self):
        from unittest.mock import patch
        board=SimulatedBoard(self.calibration,self.frontend);board.gpio_value=0x55
        def fail_fit(*args):
            self.assertFalse(any(board.enabled))
            self.assertEqual(board.gpio_value,0x55)
            raise RuntimeError('intentional analysis failure')
        with tempfile.TemporaryDirectory() as temporary, patch('zynq_bjt.ac.fit_ac_response',side_effect=fail_fit):
            _,state=run_ac_scan(board,self.calibration,self.frontend,AcScanConfig(settle_s=0,repeat_count=2,max_bisection_iterations=0),temporary)
        self.assertEqual(state['status'],'failed')
        self.assertIn('intentional analysis failure',state['error'])
        self.assertFalse(state['cleanup_errors'])

    @unittest.skipUnless(importlib.util.find_spec("ipywidgets") and
                         importlib.util.find_spec("matplotlib"),
                         "Notebook display dependencies are optional")
    def test_workbench_exposes_all_four_measurement_tabs_and_runs_output_scan(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = NpnNotebook(self.calibration, self.frontend, output_root=temporary)
            self.assertEqual(len(app.tabs.children), 4)
            self.assertEqual(app.ac_input_channel.value, 0)
            self.assertEqual(app.ac_output_channel.value, 1)
            self.assertEqual(app.output_source_scale.value, 0.0)
            self.assertEqual(app.beta_source_scale.value, 0.0)
            self.assertIn('输出', app.tabs.get_title(2))
            self.assertIn('β线性精度', app.tabs.get_title(2))
            app.tabs.selected_index = 1
            app.output_tx2_stop.value = 0.1
            app.output_tx2_step.value = 0.1
            app.output_bases.value = "0.05"
            app.output_source_scale.value = .4
            app.start_scan()
            app.worker.join(20)
            self.assertFalse(app.worker.is_alive())
            self.assertEqual(app.last_result[1]["status"], "complete",
                             app.last_result[1].get("error"))
            self.assertTrue((app.last_result[0] / "curves.png").is_file())
            app.tabs.selected_index = 2
            app.beta_tx1_start.value = .02
            app.beta_tx1_stop.value = .18
            app.beta_tx1_step.value = .04
            app.beta_source_scale.value = .4
            app.start_scan()
            app.worker.join(20)
            self.assertFalse(app.worker.is_alive())
            self.assertEqual(app.last_result[1]["status"], "complete",
                             app.last_result[1].get("error"))
            self.assertTrue((app.last_result[0] / "curves.png").is_file())

    @unittest.skipUnless(importlib.util.find_spec("ipywidgets"),
                         "Notebook display dependencies are optional")
    def test_real_scans_stay_locked_until_fixture_is_confirmed(self):
        with tempfile.TemporaryDirectory() as temporary:
            board = SimulatedBoard(self.calibration, self.frontend)
            app = NpnNotebook(self.calibration, self.frontend, output_root=temporary,
                              board=board)
            app.source.value = app.source.options[1]
            app.start_scan()
            self.assertIsNone(app.worker)
            self.assertIn('已锁止', app.last_error)


if __name__ == "__main__":
    unittest.main()
