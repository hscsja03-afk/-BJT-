"""A quantized square trace must retain plateau amplitude without edge ringing."""
import sys as _repo_sys
from pathlib import Path as _RepoPath
_repo_sys.path.insert(0, str(_RepoPath(__file__).resolve().parents[2]))

import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'board'))
from board.instruments.waveform_metrics import square_plateaus


class PlateauTests(unittest.TestCase):
    def test_phase_selected_means_on_quantized_noisy_plateaus(self):
        rng=np.random.default_rng(19)
        dt=1/5e6;f=10003;t=np.arange(12000)*dt
        carrier=np.sin(2*np.pi*f*t+.8)
        values=.004+.1*np.sign(carrier)+rng.normal(0,.0012,len(t))
        values[np.abs(carrier)<.12]+=.07*np.sign(carrier[np.abs(carrier)<.12])
        values=np.round(values/.003158203)*.003158203
        m=square_plateaus(values,dt,f)
        self.assertLess(abs(m['vpp_v']-.2),.0005)
        self.assertLess(abs(m['dc_v']-.004),.0003)
        self.assertGreater(m['high_count'],2500)
        self.assertGreater(np.ptp(values),.3)


if __name__=='__main__':unittest.main()
