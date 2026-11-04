import math
import unittest

from zynq_bjt.analysis import (analyze_beta_linearity, collector_current_a,
                               fit_ac_response, fit_early_voltage, pick_at_target_uce)


class AnalysisTests(unittest.TestCase):
    def test_output_current_uses_reference_100_ohm_resistor(self):
        self.assertAlmostEqual(collector_current_a(5.0, 4.0), 0.01)

    def test_beta_target_interpolates_between_measured_points(self):
        picked = pick_at_target_uce([
            {"uce_v": 4.0, "ic_a": 0.008},
            {"uce_v": 6.0, "ic_a": 0.010},
        ])
        self.assertEqual(picked["method"], "interpolated")
        self.assertAlmostEqual(picked["ic_a"], 0.009)

    def test_beta_target_ignores_saturation_region_points(self):
        picked = pick_at_target_uce([
            {"uce_v": 0.8, "ic_a": 0.020},
            {"uce_v": 5.2, "ic_a": 0.010},
        ])
        self.assertEqual(picked["method"], "nearest")
        self.assertAlmostEqual(picked["ic_a"], 0.010)
        self.assertIsNone(pick_at_target_uce([
            {"uce_v": 0.2, "ic_a": 0.001},
            {"uce_v": 0.8, "ic_a": 0.002},
        ]))

    def test_early_tail_fit_recovers_negative_axis_intercept(self):
        points = [{"uce_v": x, "ic_a": (0.5 + 0.02 * x) / 1000}
                  for x in (i * 0.1 for i in range(1, 101))]
        result = fit_early_voltage(points)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["early_va_v"], 25.0, places=5)
        self.assertGreater(result["r_squared"], 0.999999)

    def test_beta_linearity_reports_exact_linear_fit(self):
        points = [{"tx1_v": ib_a * 2000.0, "ic_a": 120.0 * ib_a}
                  for ib_a in (i * 1e-5 for i in range(1, 11))]
        result = analyze_beta_linearity(points, drop_initial=0, moving_average_window=1)
        self.assertAlmostEqual(result["fit_slope_beta"], 120.0, places=8)
        self.assertLess(result["linearity_error_pct"], 1e-8)
        self.assertAlmostEqual(result["beta_mean"], 120.0)
        self.assertEqual(result["fit_inlier_mask"], [True] * result["fit_point_count"])

    def test_beta_linearity_uses_project_two_point_moving_average(self):
        points = [{"tx1_v": ib, "ic_a": ic}
                  for ib, ic in ((1.0, 2.0), (2.0, 5.0), (3.0, 10.0))]
        result = analyze_beta_linearity(points, base_resistance_ohm=1.0,
                                        drop_initial=0, moving_average_window=2)
        self.assertEqual(result["fit_point_count"], 2)
        self.assertAlmostEqual(result["fit_slope_beta"], 4.0)
        self.assertAlmostEqual(result["beta_mean"], (2.25 + 35.0 / 12.0) / 2)
        self.assertAlmostEqual(result["beta_raw_mean"], (2.0 + 2.5 + 10.0 / 3.0) / 3)

    def test_beta_requires_two_points_after_project_source_drop(self):
        points = [{"tx1_v": i * 0.04, "ic_a": i * 0.001} for i in range(4)]
        with self.assertRaises(ValueError):
            analyze_beta_linearity(points, drop_initial=3)

    def test_ac_lowpass_fit_recovers_au_fbeta_and_ft(self):
        points = []
        for frequency in range(10000, 2000001, 10000):
            gain = 80.0 / math.sqrt(1.0 + (frequency / 250000.0) ** 2)
            points.append({"actual_freq_hz": frequency, "gain": gain})
        result = fit_ac_response(points, 150000)
        self.assertAlmostEqual(result["au"], 80.0, delta=1.0)
        self.assertAlmostEqual(result["f_beta_hz"], 250000.0, delta=10000)
        self.assertAlmostEqual(result["ft_hz"], 20e6, delta=1.0e6)


if __name__ == "__main__":
    unittest.main()
