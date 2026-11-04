import json,math,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from zynq_bjt.analysis import fit_ac_response,_fit_lowpass_grid_scalar
from zynq_bjt.desktop_session import MEASUREMENTS,Session
from zynq_bjt.page_defaults import load_defaults,save_default
from zynq_bjt.characteristics import BetaScanConfig,_beta_next_control
from zynq_bjt.frontend import Calibration,Frontend
from zynq_bjt.scan import ScanConfig,run_scan
from zynq_bjt.simulation import SimulatedBoard
from zynq_bjt.ac import AcScanConfig,run_ac_scan,finish_host_analysis
ROOT=Path(__file__).resolve().parents[1]

class NovemberTests(unittest.TestCase):
    def test_saved_defaults_survive_restart_and_are_per_profile_and_page(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'defaults.json'
            config=load_defaults(path,'npn_small',MEASUREMENTS)['input'];config.update(tx1_stop_v=1.5,tx1_segments_v='.02:1.5:.05')
            save_default(path,'npn_small','input',config)
            self.assertEqual(load_defaults(path,'npn_small',MEASUREMENTS)['input']['tx1_stop_v'],1.5)
            self.assertEqual(load_defaults(path,'npn_small',MEASUREMENTS)['beta']['target_uce_v'],5)
            self.assertEqual(load_defaults(path,'pnp_small',MEASUREMENTS)['input']['tx1_stop_v'],1.8)

    def test_vectorized_fit_matches_original_robust_grid(self):
        points=[dict(actual_freq_hz=10000+i*75000,gain=120/math.sqrt(1+((10000+i*75000)/8e5)**2)) for i in range(40)]
        points[12]['gain']*=1.25
        fast=fit_ac_response(points)
        with patch('zynq_bjt.analysis._fit_lowpass_grid',_fit_lowpass_grid_scalar):slow=fit_ac_response(points)
        for key in ('au','f_beta_hz','order','rmse_percent'):
            self.assertAlmostEqual(fast[key],slow[key],delta=max(1e-7,abs(slow[key])*1e-9))

    def test_beta_search_is_bounded_and_uses_few_points(self):
        cfg=BetaScanConfig();points=[];control=.95
        for _ in range(32):
            points.append(dict(tx2_request_v=control,uce_v=6*control-.8))
            control=_beta_next_control(points,cfg)
            if control is None:break
            self.assertTrue(cfg.tx2_min_v<=control<=cfg.tx2_stop_v)
        self.assertLessEqual(len(points),3)
        self.assertLessEqual(abs(points[-1]['uce_v']-5),.03)

    def test_pnp_input_drives_current_on_tx2_and_bias_on_tx1(self):
        cal=Calibration(ROOT/'data');front=Frontend();board=SimulatedBoard(cal,front)
        cfg=ScanConfig(profile='pnp_small',tx1_stop_v=.06,tx1_step_v=.02,tx1_fine_stop_v=0,
                       uce_values_v=(1,),settle_s=0,curve_settle_s=0,frame_gap_s=0,adaptive_settle_v=0)
        with tempfile.TemporaryDirectory() as folder:
            directory,state=run_scan(board,cal,front,cfg,folder)
            self.assertEqual(state['status'],'complete',state.get('error'))
            self.assertEqual(state['input_output_roles'],dict(base_current_tx=2,bias_amplifier_tx=1))
            import csv
            with (directory/'points.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertAlmostEqual(float(rows[-1]['tx2_request_v']),.06)
            self.assertAlmostEqual(float(rows[-1]['tx1_request_v']),1/6,places=3)
            self.assertFalse(any(board.enabled))

    def test_host_fit_runs_after_hardware_cleanup(self):
        cal=Calibration(ROOT/'data');front=Frontend();board=SimulatedBoard(cal,front)
        with tempfile.TemporaryDirectory() as folder:
            cfg=AcScanConfig(settle_s=0,repeat_count=2,max_bisection_iterations=0)
            directory,state=run_ac_scan(board,cal,front,cfg,folder,defer_analysis=True)
            self.assertEqual(state['status'],'acquired',state.get('error'))
            self.assertFalse(any(board.enabled));self.assertNotIn('ac_analysis',state)
            completed=finish_host_analysis(directory)
            self.assertEqual(completed['status'],'complete')
            self.assertEqual(completed['analysis_location'],'desktop_python')

    def test_retrieved_ac_records_are_fitted_on_host_without_changing_raw_data(self):
        from zynq_bjt.desktop_transport import SshTransport
        from unittest.mock import Mock
        import shutil
        cal=Calibration(ROOT/'data');front=Frontend();board=SimulatedBoard(cal,front)
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            source,state=run_ac_scan(board,cal,front,AcScanConfig(settle_s=0,repeat_count=2,max_bisection_iterations=0),folder/'board',defer_analysis=True)
            raw=(source/'points.csv').read_bytes()
            sftp=Mock();sftp.__enter__=Mock(return_value=sftp);sftp.__exit__=Mock(return_value=False)
            sftp.get.side_effect=lambda remote,local:shutil.copyfile(source/Path(remote).name,local)
            transport=SshTransport();transport.remote_root='/home/test';transport.client=Mock();transport.client.open_sftp.return_value=sftp
            result={'run_id':source.name,'files':['run.json','points.csv']}
            for _ in range(2):
                destination=transport.fetch(result,folder/'pc')
                self.assertEqual(json.loads((destination/'run.json').read_text())['analysis_location'],'desktop_python')
                self.assertEqual((destination/'points.csv').read_bytes(),raw)

if __name__=='__main__':unittest.main()
