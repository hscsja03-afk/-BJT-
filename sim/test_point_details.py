from dataclasses import asdict, replace
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration,Frontend
from zynq_bjt.simulation import SimulatedBoard
from zynq_bjt.mmio import Frame
from zynq_bjt.profiles import Profile,defaults_for
from zynq_bjt.scan import ScanConfig,run_scan
from zynq_bjt.characteristics import OutputScanConfig,BetaScanConfig,run_output_scan,run_beta_scan
from zynq_bjt.ac import AcScanConfig,run_ac_scan
from zynq_bjt.desktop_session import MEASUREMENTS
from zynq_bjt.desktop_results import latest_result,point_details


class DetailsTests(unittest.TestCase):
    def test_pnp_big_half_volt_is_10ma_in_points_and_beta(self):
        from zynq_bjt.analysis import analyze_beta_linearity
        for cls,mode in ((OutputScanConfig,'output'),(BetaScanConfig,'beta')):
            self.assertEqual(cls(profile='pnp_big').base_resistance_ohm,50)
            self.assertEqual(defaults_for(mode,cls,'pnp_big')['base_resistance_ohm'],50)
        board=SimulatedBoard(self.cal,self.front)
        self.fixed_frames(board,(.618,.412))
        cfg=OutputScanConfig(profile='pnp_big',base_control_v=(.5,),collector_resistor_ohm=1,
                             tx2_control_stop_v=.01,frames_per_point=2,settle_s=0)
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_output_scan(board,self.cal,self.front,cfg,folder)
            self.assertEqual(state['status'],'complete',state.get('error'))
            row=self.rows(path,'output_points.csv')[0]
            self.assertAlmostEqual(float(row['ib_estimated_a']),.01,delta=1e-5)
            self.assertEqual(float(row['base_resistance_ohm']),50)
            self.assertAlmostEqual(float(row['ic_a'])/float(row['ib_estimated_a']),100,delta=.2)
            self.assertEqual(point_details(row,'output',Profile('pnp_big'))['base_r'],'50')
        # Fixed independent observations: 0.5 V/1 A and 0.6 V/1.2 A give beta=100.
        result=analyze_beta_linearity([dict(tx1_v=.5,ic_a=1),dict(tx1_v=.6,ic_a=1.2)],
                                      base_resistance_ohm=BetaScanConfig(profile='pnp_big').base_resistance_ohm,
                                      drop_initial=0,moving_average_window=1)
        self.assertAlmostEqual(result['beta_mean'],100)

    def setUp(self):
        self.cal=Calibration(ROOT/'data');self.front=Frontend()

    def rows(self,path,name='points.csv'):
        with (path/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

    def fixed_frames(self,board,voltages):
        codes=[round(v*1e9/p['slope_nv_per_code']+p['zero_code_q16']/65536)
               for v,p in zip(voltages,(self.cal.rx1,self.cal.rx2))]
        counter=[0]
        def capture():
            counter[0]+=1
            return Frame(counter[0],tuple((code,)*1024 for code in codes),(50e6,50e6),counter[0],simulated=True)
        board.capture=capture
        return codes

    def test_npn_big_ac_has_small_current_range_and_pin87_low(self):
        route=Profile('npn_big').route('ac')
        self.assertEqual(route['value'],2)
        self.assertEqual((route['pin_values'][87],route['pin_values'][77],route['pin_values'][48]),(0,0,0))
        self.assertEqual(route['current_range_a'],[10e-6,.001])
        self.assertEqual(Profile('npn_big').route('output')['value'],37)
        self.assertEqual(Profile('pnp_big').route('ac')['value'],26)
        cfg=defaults_for('ac',AcScanConfig,'npn_big')
        self.assertEqual((cfg['base_resistance_ohm'],cfg['collector_resistor_ohm']),(2000,1))

    def test_custom_output_transfers_use_real_adc_codes_and_independent_prediction(self):
        board=SimulatedBoard(self.cal,self.front)
        codes=self.fixed_frames(board,(.6,.4))
        cfg=OutputScanConfig(base_control_v=(.02,),base_resistance_ohm=2500,collector_resistor_ohm=150,
            collector_adc_per_v=.2,source_adc_per_v=.2,tx2_control_stop_v=0,settle_s=0,frames_per_point=2)
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_output_scan(board,self.cal,self.front,cfg,folder)
            self.assertEqual(state['status'],'complete',state.get('error'))
            row=self.rows(path,'output_points.csv')[0]
            self.assertEqual([float(row['rx1_mean_code']),float(row['rx2_mean_code'])],codes)
            self.assertAlmostEqual(float(row['rx1_port_v']),.6,delta=.0001)
            self.assertAlmostEqual(float(row['rx2_port_v']),.4,delta=.0001)
            self.assertAlmostEqual(float(row['ic_a']),(3-2)/150,delta=2e-6)
            self.assertAlmostEqual(float(row['ib_estimated_a']),self.cal.dac_code(0,.02)[1]/2500)
            self.assertAlmostEqual(float(row['vcc_predicted_v']),0,delta=.001)
            self.assertGreater(float(row['vcc_v']),2.9)

    def test_input_current_coefficient_is_editable_and_raw_codes_are_preserved(self):
        front=replace(self.front,base_equivalent_resistance_ohm=400000,collector_amplifier_gain=5,rx1_per_vc=.2)
        board=SimulatedBoard(self.cal,front)
        codes=self.fixed_frames(board,(.1,.2))
        cfg=ScanConfig(profile='pnp_small',ve_conversion_mode='线性比例',tx1_stop_v=.02,uce_values_v=(1,),
            settle_s=0,curve_settle_s=0,frame_gap_s=0,adaptive_settle_v=0)
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_scan(board,self.cal,front,cfg,folder)
            self.assertEqual(state['status'],'complete',state.get('error'))
            row=self.rows(path)[0]
            self.assertEqual(state['measurement'],'input')
            self.assertEqual(float(row['rx1_mean_code']),codes[0])
            self.assertAlmostEqual(float(row['ib_estimated_a']),float(row['tx2_table_v'])/400000)
            self.assertAlmostEqual(float(row['ve_v']),1,delta=.001)
            self.assertAlmostEqual(float(row['vb_v']),.4,delta=.001)
            self.assertAlmostEqual(float(row['vcc_predicted_v']),1,delta=.003)

    def test_ac_raw_rms_is_distinct_from_scaled_node_and_peak_values(self):
        board=SimulatedBoard(self.cal,self.front);cancel=threading.Event()
        rms=(.1,.02)
        board.capture_statistics=lambda count:dict(simulated=True,channels=[
            dict(mean_code=p['zero_code_q16']/65536,rms_code=v*1e9/abs(p['slope_nv_per_code']),fault_count=0)
            for v,p in zip(rms,(self.cal.rx1,self.cal.rx2))])
        cfg=AcScanConfig(collector_resistor_ohm=120,input_test_resistor_ohm=60,
                         base_resistance_ohm=2400,settle_s=0,repeat_count=2)
        front=replace(self.front,collector_amplifier_gain=5)
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_ac_scan(board,self.cal,front,cfg,folder,cancel,
                emit=lambda kind,row:cancel.set() if kind=='point' else None)
            self.assertEqual(state['status'],'cancelled',state.get('error'))
            row=self.rows(path)[0]
            self.assertAlmostEqual(float(row['rx1_port_ac_rms_v']),.1)
            self.assertAlmostEqual(float(row['rx2_port_ac_rms_v']),.02)
            self.assertAlmostEqual(float(row['input_node_v_peak']),.1/9.78*math.sqrt(2))
            vb=.1/9.78*math.sqrt(2);vin=cfg.tx3_input_vpp*cfg.source_buffer_gain/2
            self.assertAlmostEqual(float(row['input_resistance_ohm']),60*vb/(vin-vb))
            self.assertAlmostEqual(float(row['output_node_v_peak']),.02/.206*math.sqrt(2))
            self.assertAlmostEqual(float(row['vcc_predicted_v']),7.5)
            self.assertAlmostEqual(state['source_parameters']['tx1_nominal_current_a'],.2/2400)

    def test_cancelled_beta_retains_selected_points_with_real_neighbor_diagnostics(self):
        board=SimulatedBoard(self.cal,self.front);cancel=threading.Event()
        cfg=BetaScanConfig(settle_s=0,frames_per_point=2)
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_beta_scan(board,self.cal,self.front,cfg,folder,cancel,
                emit=lambda kind,row:cancel.set() if kind=='point' else None)
            self.assertEqual(state['status'],'cancelled',state.get('error'))
            row=self.rows(path,'beta_points.csv')[0]
            trace=self.rows(path,'beta_trace.csv')
            sample=next(p for p in trace if p['curve']==row['curve'] and p['index']==row['sample_index'])
            for key in ('rx1_mean_code','rx2_mean_code','rx1_port_v','rx2_port_v','vcc_v'):
                self.assertEqual(row[key],sample[key])
            self.assertEqual(row['sample_uce_v'],sample['uce_v'])
            self.assertIn('acquired_sample',row['adc_basis'])

    def test_latest_matching_run_ignores_empty_corrupt_and_other_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,stamp,profile,empty in [('old',1,'npn_small',False),('partial',2,'npn_small',False),
                                            ('empty',3,'npn_small',True),('other',4,'pnp_small',False)]:
                path=root/name;path.mkdir()
                (path/'run.json').write_text(json.dumps(dict(config={'uce_values_v':[.5]},profile=profile,
                    status='cancelled',finished_at=stamp)),encoding='utf-8')
                (path/'points.csv').write_text('curve,ube_v,ib_estimated_a\n'+('' if empty else '0,.6,.000001\n'))
            bad=root/'bad';bad.mkdir();(bad/'run.json').write_text('{')
            result=latest_result(root,'input','npn_small',MEASUREMENTS)
            self.assertEqual(result['run_id'],'partial')
            self.assertIsNone(latest_result(root,'beta','npn_small',MEASUREMENTS))

    def test_table_distinguishes_curve_conditions_and_missing_old_diagnostics(self):
        p=Profile('npn_small')
        a=point_details(dict(curve=0,index=2,uce_target_v=.5),'input',p)
        b=point_details(dict(curve=1,index=0,uce_target_v=1),'input',p)
        self.assertEqual(a['point'],'3')
        self.assertNotEqual(a['curve'],b['curve']);self.assertNotEqual(a['condition'],b['condition'])
        self.assertEqual(a['rx1_v'],'—')


if __name__=='__main__':unittest.main()
