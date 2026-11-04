import unittest
from pathlib import Path
from zynq_bjt.sweep import segmented_values
from zynq_bjt.scan import ScanConfig
from zynq_bjt.characteristics import OutputScanConfig,BetaScanConfig
from zynq_bjt.ac import AcScanConfig
from zynq_bjt.frontend import Calibration,Frontend

class SegmentedSweeps(unittest.TestCase):
    def test_shared_boundary_endpoint_and_invalid_inputs(self):
        self.assertEqual(segmented_values('0:.1:.03;.1:.2:.05',0,1),[0,.03,.06,.09,.1,.15,.2])
        for spec in ('0:1:0','nan:1:.1','1:0:.1','0:1:.1;.9:2:.1','0:2:1','0:1:.00001',''):
            with self.assertRaises(ValueError,msg=spec):segmented_values(spec,0,1,100)

    def test_segmented_config_controls_actual_plan_and_checks_feedback_limit(self):
        cal=Calibration(Path(__file__).resolve().parents[1]/'data');front=Frontend()
        self.assertEqual(ScanConfig(tx1_segments_v='.02:.08:.02;.08:.2:.06').validate(cal,front),[.02,.04,.06,.08,.14,.2])
        self.assertEqual(OutputScanConfig(tx2_segments_v='0:.03:.01;.03:.09:.03').validate(cal,front),[0,.01,.02,.03,.06,.09])
        with self.assertRaisesRegex(ValueError,'软件输入上限'):
            OutputScanConfig(tx2_segments_v='0:1.8:.1').validate(cal,front)
        self.assertEqual(BetaScanConfig(tx1_segments_v='.02:.1:.04').validate(cal,front),[.02,.06,.1])
        cfg=AcScanConfig();frequencies=cfg.validate(cal,front)
        self.assertEqual((frequencies[0],frequencies[-1],len(frequencies)),(10000,5000000,64))
        self.assertEqual(cfg.input_adc_per_v,9.78)
        self.assertIn(150000,frequencies);self.assertIn(200000,frequencies)
        self.assertEqual(frequencies,sorted(set(frequencies)))
