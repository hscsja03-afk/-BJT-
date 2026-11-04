import json
import math
from pathlib import Path
import unittest
from matplotlib.figure import Figure
from zynq_bjt.analysis import fit_early_voltage,input_resistance_summary
from zynq_bjt.measurement_views import draw_early,draw_rin
from zynq_bjt.profiles import Profile
ROOT=Path(__file__).resolve().parents[1]


class DerivedAnalysisTests(unittest.TestCase):
    def test_known_early_voltage_and_output_resistance(self):
        rows=[dict(curve=0,ib_estimated_a=20e-6,uce_v=i/10,ic_a=(30+i/10)/4000) for i in range(10,81)]
        fit=fit_early_voltage(rows)
        self.assertAlmostEqual(fit['early_va_v'],30)
        self.assertAlmostEqual(fit['x_intercept_v'],-30)
        self.assertAlmostEqual(fit['ro_ohm'],4000)
        self.assertAlmostEqual((fit['early_va_v']+fit['q_uce_v'])/fit['q_ic_a'],4000)
        self.assertTrue(fit['fit_reliable'])
        ax=Figure().add_subplot(111);draw_early(ax,rows,Profile('pnp_big'))
        self.assertTrue(any(min(line.get_xdata())<0 for line in ax.lines if len(line.get_xdata())))

    def test_nonphysical_and_flat_slopes_do_not_report_early(self):
        for fn in (lambda u:.01,lambda u:.02-.001*u,lambda u:.001*u-.001):
            rows=[dict(uce_v=i/10,ic_a=fn(i/10)) for i in range(20,81)]
            fit=fit_early_voltage(rows)
            self.assertTrue(fit is None or not fit['fit_reliable'])

    def test_rin_plot_retains_acquired_points_and_refinement(self):
        rows=[dict(actual_freq_hz=f,input_resistance_ohm=r,mode=mode)
              for f,r,mode in [(10000,400,'sweep'),(100000,600,'sweep'),(50000,550,'refine'),(200000,-1,'sweep')]]
        ax=Figure().add_subplot(111)
        result=draw_rin(ax,rows,dict(input_test_resistor_ohm=100))
        sweep=next(line for line in ax.lines if line.get_label()=='扫描点')
        refine=next(line for line in ax.lines if line.get_label()=='截止附近补测')
        self.assertEqual(list(sweep.get_xdata()),[10000,100000])
        self.assertEqual(list(sweep.get_ydata()),[400,600])
        self.assertEqual(list(refine.get_xdata()),[50000])
        self.assertEqual(list(refine.get_ydata()),[550])
        self.assertEqual(result['point_count'],3)
        self.assertEqual(result['test_resistor_ohm'],100)
        self.assertEqual(ax.get_xlabel(),'频率 / Hz')

    def test_rin_summary_retains_measured_values_and_excludes_invalid(self):
        rows=[dict(actual_freq_hz=f,input_resistance_ohm=r) for f,r in ((10000,400),(100000,600),(1e6,1000),(2e6,-1),(3e6,float('nan'))) ]
        s=input_resistance_summary(rows)
        self.assertEqual(s['point_count'],3);self.assertEqual(s['passband_median_ohm'],500)
        self.assertEqual(s['maximum_ohm'],1000)


if __name__=='__main__':unittest.main()
