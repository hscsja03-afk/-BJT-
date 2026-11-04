"""Voltage units, conversion boundaries, physical VE mapping, and read-only meter."""
import json, math, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration, Frontend
from zynq_bjt.meter import readings
from zynq_bjt.scope_display import reference_channels
from zynq_bjt.mmio import Frame
from zynq_bjt.scan import reduce_frames
from zynq_bjt.desktop_session import Session


class Tests(unittest.TestCase):
    def setUp(self): self.cal=Calibration(ROOT/'data')

    def code(self,v,ch):
        p=(self.cal.rx1,self.cal.rx2)[ch]
        return p['zero_code_q16']/65536+v/(p['slope_nv_per_code']/1e9)

    def stats(self,dc,ac):
        return dict(sample_count=50000,completed_at=1,channels=[
            dict(mean_code=self.code(dc,ch),rms_code=ac/abs(p['slope_nv_per_code']/1e9),fault_count=0)
            for ch,p in enumerate((self.cal.rx1,self.cal.rx2))])

    def test_dc_true_and_ac_rms_handle_negative_gain_and_offset(self):
        for dc,ac in ((.4,.1/math.sqrt(2)),(-.5,0),(0,.2)):
            rows=readings(self.stats(dc,ac),self.cal,(50e6,50e6))['channels']
            for row in rows:
                self.assertAlmostEqual(row['dc_v'],dc)
                self.assertAlmostEqual(row['true_rms_v'],math.hypot(dc,ac))
                self.assertAlmostEqual(row['ac_rms_v'],ac)

    def test_meter_rejects_faults_and_rate_mismatch_without_good_partial_mean(self):
        stats=self.stats(.4,.1);stats['channels'][0]['fault_count']=1
        rows=readings(stats,self.cal,(50e6,125e6))['channels']
        for row in rows:
            self.assertIsNone(row['dc_v']);self.assertIsNone(row['true_rms_v']);self.assertTrue(row['error'])

    def test_two_volt_software_limit_keeps_calibration_and_rail_guards(self):
        self.assertEqual(self.cal.rx1['valid_max_v'],1.75)
        self.assertEqual(self.cal.conversion_range(0),(-2,2))
        self.assertAlmostEqual(self.cal.port_v(self.code(1.87,0),0),1.87)
        frame=dict(words=[[round(self.code(1.87,0))],[32884]],sample_rates_hz=[50e6]*2)
        row=reference_channels(frame,self.cal)[0]
        self.assertFalse(row['nominal_dc_calibrated']);self.assertEqual(row['voltage_basis'],'linear_extrapolation')
        for code in (0,65535):
            with self.assertRaisesRegex(ValueError,'rail'):self.cal.port_v(code,0)
        self.cal.rx1['slope_nv_per_code']*=2
        with self.assertRaisesRegex(ValueError,'software'):self.cal.port_v(100,0)

    def test_ve_table_replaces_only_matching_input_fixture_scaling(self):
        # Independent physically recorded midpoint, withheld from the table.
        feedback=1.0416094518863626;expected=4.9366688
        words=tuple((round(self.code(v,ch)),)*1024 for ch,v in enumerate((.9,feedback)))
        frames=[Frame(i,words,(50e6,50e6),i) for i in (1,2)]
        row=reduce_frames(frames,self.cal,Frontend(),.05,ve_profile='pnp_small')
        self.assertAlmostEqual(row['uce_v'],expected,delta=.025)
        self.assertAlmostEqual(row['ube_v'],3.6,delta=.001)
        old=reduce_frames(frames,self.cal,Frontend(),.05)
        self.assertAlmostEqual(old['uce_v'],feedback/.206,delta=.001)
        self.assertIsNone(self.cal.ve_conversion('npn_small',1))
        self.assertEqual(self.cal.ve_conversion('pnp_big',1)['points'],self.cal.ve_conversion('pnp_small',1)['points'])
        self.assertGreater(self.cal.ve_from_port(1.9,'pnp_small'),self.cal.ve_feedback['points'][-1]['ve_v'])
        with self.assertRaisesRegex(ValueError,'software conversion'):self.cal.ve_from_port(2.1,'pnp_small')
        self.assertIn('ve_feedback_calibration.json',self.cal.manifest())

    def test_pnp_big_input_uses_recorded_table_even_if_linear_ratio_is_different(self):
        import csv
        from zynq_bjt.scan import ScanConfig,run_scan
        from zynq_bjt.simulation import SimulatedBoard
        front=Frontend(rx1_per_vc=.4);board=SimulatedBoard(self.cal,front);sequence=[0]
        words=tuple((round(self.code(v,ch)),)*1024 for ch,v in enumerate((1.05,1.0416094518863626)))
        def capture():
            sequence[0]+=1;return Frame(sequence[0],words,(50e6,50e6),sequence[0],simulated=True)
        board.capture=capture
        cfg=ScanConfig(profile='pnp_big',tx1_stop_v=.02,uce_values_v=(5,),settle_s=0,curve_settle_s=0,frame_gap_s=0)
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_scan(board,self.cal,front,cfg,folder)
            self.assertEqual(state['status'],'complete',state.get('error'))
            self.assertEqual(state['measurement_gpio']['pin_values'][87],0)
            self.assertEqual(state['ve_feedback_conversion']['points'],self.cal.ve_feedback['points'])
            with (path/'points.csv').open(encoding='utf-8-sig') as f:row=next(csv.DictReader(f))
            self.assertAlmostEqual(float(row['ve_v']),4.9366688,delta=.025)
            self.assertEqual(row['ve_conversion_basis'],'scope_table_interpolation')
            self.assertAlmostEqual(float(row['ube_v']),float(row['ve_v'])-4.2,delta=.001)

    def test_table_mode_never_silently_falls_back_when_channel_or_table_is_missing(self):
        from zynq_bjt.scan import ScanConfig
        from dataclasses import replace
        cfg=ScanConfig(profile='pnp_big',collector_channel=0,base_channel=1,tx1_stop_v=1.8)
        with self.assertRaisesRegex(ValueError,'实测表'):cfg.validate(self.cal,Frontend())
        replace(cfg,ve_conversion_mode='线性比例').validate(self.cal,Frontend())
        self.cal.ve_feedback=None
        with self.assertRaisesRegex(ValueError,'实测表'):ScanConfig(profile='pnp_big').validate(self.cal,Frontend())

    def test_actual_meter_dispatch_only_acquires_statistics(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as path:
            session=Session(ROOT/'data',path)
            with self.assertRaisesRegex(RuntimeError,'初始化'):session.dispatch('meter')
            board=Mock();board.sample_rates_hz=(50e6,50e6)
            board.capture_statistics.return_value=self.stats(.4,.1)
            session.board=board
            result=session.dispatch('meter')
            self.assertEqual([c[0] for c in board.mock_calls],['capture_statistics'])
            board.capture_statistics.assert_called_once_with(50000)
            self.assertAlmostEqual(result['window_ms'][0],1)


if __name__=='__main__':unittest.main()
