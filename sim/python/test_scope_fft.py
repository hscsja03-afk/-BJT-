import math
import unittest
import numpy as np
from zynq_bjt.scope_display import spectrum


class SpectrumTests(unittest.TestCase):
    def test_known_sine_rms_and_dbv(self):
        t=np.arange(1024)
        for window in ('hann','rectangular'):
            result=spectrum(3+math.sqrt(2)*np.sin(2*np.pi*32*t/1024),102400,window)
            self.assertAlmostEqual(result['rms'][32],1)
            self.assertAlmostEqual(result['db'][32],0)
            self.assertEqual(result['frequency_hz'][32],3200)
            self.assertLess(result['rms'][0],1e-12)

    def test_dc_and_nyquist_do_not_double(self):
        t=np.arange(1024)
        result=spectrum(3+2*(-1.)**t,1024,'rectangular',False)
        self.assertAlmostEqual(result['rms'][0],3)
        self.assertAlmostEqual(result['rms'][-1],2)
        self.assertAlmostEqual(sum(result['rms']**2),13)

    def test_odd_length_last_bin_and_invalid(self):
        t=np.arange(101)
        result=spectrum(np.sin(2*np.pi*50*t/101),101,'rectangular')
        self.assertAlmostEqual(result['rms'][-1],1/math.sqrt(2))
        for values,rate in (([1]*7,1),([float('nan')]*8,1),([1]*8,0)):
            with self.assertRaises(ValueError):spectrum(values,rate)

    def test_hann_reduces_distant_leakage(self):
        x=np.sin(2*np.pi*32.3*np.arange(1024)/1024)
        self.assertLess(spectrum(x,1024)['rms'][80],spectrum(x,1024,'rectangular')['rms'][80]/100)


if __name__=='__main__':unittest.main()
