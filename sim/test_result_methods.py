import csv
import json
from pathlib import Path
import tempfile
import unittest
from zynq_bjt.result_paths import create_run, relative_run
from zynq_bjt.desktop_results import latest_result
from zynq_bjt.desktop_session import MEASUREMENTS


class ResultMethodTests(unittest.TestCase):
    def test_paths_separate_methods_and_accept_legacy(self):
        with tempfile.TemporaryDirectory() as root:
            for measurement in ('output','beta'):
                for method,label in (('step','步进'),('pulse','脉冲')):
                    path=create_run(root,'npn_big',measurement,method)
                    self.assertEqual(path.parent.name,label)
                    self.assertEqual(len(relative_run(path.relative_to(root).as_posix()).parts),4)
            self.assertEqual(len(relative_run('NPN大功率/输出特性/old').parts),3)
            self.assertEqual(len(relative_run('old').parts),1)
            self.assertEqual(create_run(root,'pnp_big','output').parent.name,'步进')
        for invalid in ('NPN大功率/输出特性/未知/run','NPN小功率/输出特性/脉冲/run',
                        'NPN大功率/交流特性/脉冲/run','NPN大功率/输出特性/脉冲/../run'):
            with self.assertRaises(ValueError):relative_run(invalid)

    def test_latest_method_filters_nested_and_old_records(self):
        with tempfile.TemporaryDirectory() as root:
            for name,stamp,method,scan_mode in [('步进/step',1,'step','步进'),('脉冲/pulse',2,'pulse','脉冲'),
                                                ('legacy_pulse',3,None,'脉冲')]:
                path=Path(root)/'NPN大功率'/'输出特性'/name;path.mkdir(parents=True)
                state=dict(measurement='output',profile='npn_big',finished_at=stamp,config=dict(scan_mode=scan_mode))
                if method:state['method']=method
                (path/'run.json').write_text(json.dumps(state))
                (path/'output_points.csv').write_text('uce_v,ic_a\n1,.001\n')
            self.assertEqual(latest_result(root,'output','npn_big',MEASUREMENTS,method='step')['run_id'],'step')
            self.assertEqual(latest_result(root,'output','npn_big',MEASUREMENTS,method='pulse')['run_id'],'legacy_pulse')
            self.assertIsNone(latest_result(root,'beta','npn_big',MEASUREMENTS,method='pulse'))
