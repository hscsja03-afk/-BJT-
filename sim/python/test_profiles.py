from dataclasses import replace
import csv
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.profiles import Profile, defaults_for
from zynq_bjt.frontend import Calibration,Frontend
from zynq_bjt.characteristics import OutputScanConfig,run_output_scan
from zynq_bjt.ac import AcScanConfig,run_ac_scan
from zynq_bjt.analysis import analyze_beta_linearity
from zynq_bjt.simulation import SimulatedBoard
from zynq_bjt.desktop_session import Session

class Tests(unittest.TestCase):
    def test_vcc_divider_converts_connector_voltage_before_current_calculation(self):
        from zynq_bjt.mmio import Frame
        from zynq_bjt.characteristics import BetaScanConfig
        c=Calibration(ROOT/'data'); f=Frontend(); b=SimulatedBoard(c,f)
        sequence=[0]
        # RX1=VCC*0.206=.618 V, RX2=VC*0.206=.412 V.
        words=[]
        for voltage,cal in zip((.618,.412),(c.rx1,c.rx2)):
            code=round(cal['zero_code_q16']/65536+voltage/(cal['slope_nv_per_code']/1e9))
            words.append((code,)*1024)
        def capture():
            sequence[0]+=1
            return Frame(sequence[0],tuple(words),(50e6,50e6),sequence[0],simulated=True)
        b.capture=capture
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_output_scan(b,c,f,OutputScanConfig(base_control_v=(.02,),tx2_control_stop_v=.01,settle_s=0,frames_per_point=2),folder)
            self.assertEqual(state['status'],'complete',state.get('error'))
            with (path/'output_points.csv').open(encoding='utf-8-sig') as stream: row=next(csv.DictReader(stream))
            self.assertAlmostEqual(float(row['vcc_v']),3,places=3)
            self.assertAlmostEqual(float(row['vc_v']),2,places=3)
            self.assertAlmostEqual(float(row['ic_a']),.01,places=5)
        self.assertEqual(BetaScanConfig().source_adc_per_v,.206)

    def test_ac_vb_user_gain_9_78_is_removed_once(self):
        from zynq_bjt.ac import _rms_voltage
        from zynq_bjt.scan import ScanConfig
        c=Calibration(ROOT/'data'); cfg=AcScanConfig()
        # A fixed 100 mV RMS at RX1 represents 100/9.78 mV RMS at VB.
        adc_rms_code=.1/(abs(c.rx1['slope_nv_per_code'])/1e9)
        vb_rms=_rms_voltage(c,0,adc_rms_code,cfg.input_adc_per_v)
        self.assertAlmostEqual(vb_rms,.1/9.78)
        self.assertAlmostEqual(vb_rms/cfg.input_sample_gain,.1/9.78)
        self.assertEqual(ScanConfig().base_adc_per_v,.25)
        for profile in ('npn_small','npn_big','pnp_small','pnp_big'):
            self.assertEqual(defaults_for('ac',AcScanConfig,profile)['input_adc_per_v'],9.78)

    def test_ac_uses_buffer_output_for_base_current_without_changing_tx3(self):
        import math
        c=Calibration(ROOT/'data'); f=Frontend(); b=SimulatedBoard(c,f)
        stop=threading.Event()
        def capture(count):
            channels=[]
            # Fixed connector readings: VB=10 mV RMS, collector=0.2 V peak.
            for v,cal in zip((.1,.2/math.sqrt(2)*.206),(c.rx1,c.rx2)):
                channels.append(dict(rms_code=v/(abs(cal['slope_nv_per_code'])/1e9),fault_count=0))
            return dict(simulated=True,channels=channels)
        b.capture_statistics=capture
        def emit(kind,row):
            if kind=='point': stop.set()
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_ac_scan(b,c,f,AcScanConfig(settle_s=0,repeat_count=2),folder,stop,emit=emit)
            self.assertEqual(state['status'],'cancelled',state.get('error'))
            with (path/'points.csv').open(encoding='utf-8-sig') as stream: row=next(csv.DictReader(stream))
            self.assertEqual(state['config']['input_test_resistor_ohm'],100)
            expected_ib=(.042/2-(.1/9.78)*math.sqrt(2))/100
            self.assertAlmostEqual(float(row['input_current_a_peak']),expected_ib)
            self.assertAlmostEqual(float(row['gain']),(.2/100)/expected_ib)
            self.assertAlmostEqual(b.ac_amplitude_vpp,.05)
            self.assertAlmostEqual(state['source_parameters']['effective_source_vpp'],.042)
            self.assertEqual(state['config']['adc_amplitude_multiplier'],1)
            self.assertAlmostEqual(float(row['input_rms_v']),.1/9.78)
            self.assertAlmostEqual(float(row['output_rms_v']),.2/math.sqrt(2))

    def test_user_pin_order_and_current_ranges(self):
        expected={'npn_small':(64,4,2),'npn_big':(64,37,2),
                  'pnp_small':(88,28,26),'pnp_big':(88,61,26)}
        for key,values in expected.items():
            p=Profile(key)
            for mode,value in zip(('input','output','ac'),values):
                self.assertEqual(p.route(mode)['value'],value)
            self.assertAlmostEqual(.02/p.base_ohm('input'),100e-9)
            self.assertAlmostEqual(2/p.base_ohm('input'),10e-6)
            self.assertAlmostEqual(.02/p.base_ohm('output'),.0004 if p.big else .00001)
            self.assertAlmostEqual(2/p.base_ohm('output'),.04 if p.big else .001)

    def test_npn_and_pnp_equations_use_different_sense_topologies(self):
        self.assertEqual(Profile('npn_small').output_nodes(1,3,100),(1,.02))
        uec,ic=Profile('pnp_small').output_nodes(1,3,100,.0001)
        self.assertEqual(uec,1)
        self.assertAlmostEqual(ic,.02)
        self.assertEqual(Profile('pnp_big').output_nodes(1,3,1),(1,2))
        self.assertEqual(Profile('npn_big').output_nodes(1,3,1),(1,2))
        self.assertLess(Profile('pnp_small').output_nodes(4,3,100)[1],0)

    def test_pnp_saved_nodes_and_current_use_emitter_sense(self):
        from zynq_bjt.mmio import Frame
        c=Calibration(ROOT/'data');f=Frontend();b=SimulatedBoard(c,f)
        words=[]
        for voltage,cal in zip((.618,.412),(c.rx1,c.rx2)):
            code=round(cal['zero_code_q16']/65536+voltage/(cal['slope_nv_per_code']/1e9))
            words.append((code,)*1024)
        counter=[0]
        def capture():
            counter[0]+=1
            return Frame(counter[0],tuple(words),(50e6,50e6),counter[0],simulated=True)
        b.capture=capture
        with tempfile.TemporaryDirectory() as folder:
            config=OutputScanConfig(profile='pnp_small',base_control_v=(.02,),tx2_control_stop_v=.01,settle_s=0,frames_per_point=2)
            path,state=run_output_scan(b,c,f,config,folder)
            self.assertEqual(state['status'],'complete',state.get('error'))
            with (path/'output_points.csv').open(encoding='utf-8-sig') as stream:row=next(csv.DictReader(stream))
            self.assertEqual(float(row['vc_v']),0)
            self.assertAlmostEqual(float(row['ve_v']),2,places=3)
            self.assertAlmostEqual(float(row['uce_v']),2,places=3)
            self.assertAlmostEqual(float(row['ie_a']),.01,places=5)
            self.assertAlmostEqual(float(row['ic_a']),float(row['ie_a']))

    def test_power_class_defaults_allow_custom_conversion_coefficients(self):
        c=Calibration(ROOT/'data');f=Frontend()
        OutputScanConfig(profile='npn_big',base_resistance_ohm=60,collector_resistor_ohm=1.2).validate(c,f)
        for value in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                OutputScanConfig(profile='npn_big',base_resistance_ohm=value).validate(c,f)
        OutputScanConfig(**defaults_for('output',OutputScanConfig,'npn_big')).validate(c,f)

    def test_cancelled_output_keeps_completed_csv_and_restores_relays(self):
        c=Calibration(ROOT/'data');f=Frontend();b=SimulatedBoard(c,f);b.gpio_value=0x55
        stop=threading.Event()
        def emit(kind,row):
            if kind=='point':stop.set()
        with tempfile.TemporaryDirectory() as folder:
            d,s=run_output_scan(b,c,f,OutputScanConfig(settle_s=0,frames_per_point=2),folder,stop,emit=emit)
            self.assertEqual(s['status'],'cancelled')
            with (d/'output_points.csv').open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),1)
            self.assertFalse(any(b.enabled));self.assertEqual(b.gpio_value,0x55)

    def test_reference_mode_is_explicit_and_never_marks_a_result_qualified(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Session(ROOT/'data',folder,simulated=True);s.initialize()
            r=s.scan(dict(measurement='input',profile='npn_big',allow_reference=True,
                          config=dict(tx1_stop_v=.04,uce_values_v=(1,),settle_s=0,curve_settle_s=0,frame_gap_s=0)))
            self.assertEqual(r['state']['status'],'complete',r['state'].get('error'))
            self.assertEqual(r['state']['qualification']['status'],'reference_only')
            self.assertFalse(r['state']['parameter_basis']['absolute_measurement_accuracy_verified'])
            s.close()

    def test_pnp_input_and_ac_keep_base_feedback(self):
        from zynq_bjt.profiles import assumptions
        from zynq_bjt.desktop_session import MEASUREMENTS
        for profile in ('pnp_small','pnp_big'):
            for measurement in ('input','ac'):
                with self.subTest(profile=profile,measurement=measurement), tempfile.TemporaryDirectory() as folder:
                    s=Session(ROOT/'data',folder,simulated=True);s.initialize()
                    s.board.gpio(127,0x55)
                    for channel in range(3):s.board.enable(channel,True)
                    try:
                        cfg=defaults_for(measurement,MEASUREMENTS[measurement][0],profile)
                        cfg['settle_s']=0
                        if measurement=='input':cfg.update(tx1_stop_v=.02,uce_values_v=(1,),curve_settle_s=0,frame_gap_s=0)
                        else:cfg.update(repeat_count=2,max_bisection_iterations=0,frequency_segments_hz='10000:110000:50000;200000:1200000:500000')
                        result=s.scan(dict(measurement=measurement,profile=profile,config=cfg,prepare_outputs=True))
                        self.assertEqual(result['state']['status'],'complete',result['state'].get('error'))
                        self.assertFalse(any(s.board.enabled))
                        self.assertEqual(s.board.gpio_value,0x55)
                        basis=assumptions(profile,measurement)['confirmed']
                        self.assertEqual(basis['rx2_node'],'VE')
                        self.assertTrue(basis['rx1_node'].startswith('VB'))
                    finally:
                        s.close()

    def test_pnp_input_measures_ve_and_accounts_for_sixfold_bias_amplifier(self):
        from zynq_bjt.mmio import Frame
        from zynq_bjt.scan import ScanConfig, run_scan
        c=Calibration(ROOT/'data');f=Frontend();b=SimulatedBoard(c,f)
        words=[]
        # VCC is 3 V; VE may differ under load and must not be replaced by VCC.
        for voltage,cal in zip((1.7*.25,2.35*.206),(c.rx1,c.rx2)):
            code=round(cal['zero_code_q16']/65536+voltage/(cal['slope_nv_per_code']/1e9))
            words.append((code,)*1024)
        counter=[0]
        def capture():
            counter[0]+=1
            return Frame(counter[0],tuple(words),(50e6,50e6),counter[0],simulated=True)
        b.capture=capture
        with tempfile.TemporaryDirectory() as folder:
            cfg=ScanConfig(profile='pnp_small',ve_conversion_mode='线性比例',tx1_stop_v=.02,uce_values_v=(3,),settle_s=0,curve_settle_s=0,frame_gap_s=0)
            path,state=run_scan(b,c,f,cfg,folder)
            self.assertEqual(state['status'],'complete',state.get('error'))
            with (path/'points.csv').open(encoding='utf-8-sig') as stream:row=next(csv.DictReader(stream))
            self.assertEqual(float(row['vc_v']),0)
            self.assertAlmostEqual(float(row['ve_v']),2.35,places=3)
            self.assertAlmostEqual(float(row['vb_v']),1.7,places=3)
            self.assertAlmostEqual(float(row['ube_v']),.65,places=3)
            self.assertAlmostEqual(float(row['vcc_v']),3,places=3)
            self.assertAlmostEqual(float(row['tx1_request_v']),.5,places=6)
            self.assertAlmostEqual(float(row['tx1_nominal_v'])*6,3,delta=.004)
            self.assertAlmostEqual(float(row['uce_v']),2.35,places=3)
            self.assertAlmostEqual(float(row['rx2_port_v']),2.35*.206,places=3)
            self.assertEqual(row['emitter_basis'],'ADC_measured_RX2')
            self.assertNotIn('bias_adjustments',state)
            self.assertEqual(state['captured_channels'],(0,1))
            raw=json.loads((path/'frames.jsonl').read_text().splitlines()[0])
            self.assertEqual(len(raw['frame']['words'][1]),1024)

    def test_pnp_input_rejects_clipping_on_either_feedback_channel(self):
        from zynq_bjt.mmio import Frame
        from zynq_bjt.scan import ScanConfig, run_scan
        c=Calibration(ROOT/'data');f=Frontend()
        for clipped_channel in (0,1):
            with self.subTest(channel=clipped_channel),tempfile.TemporaryDirectory() as folder:
                b=SimulatedBoard(c,f);counter=[0]
                def capture():
                    counter[0]+=1
                    words=tuple((0x1ffff if ch==clipped_channel else 32768,)*1024 for ch in (0,1))
                    return Frame(counter[0],words,(50e6,50e6),counter[0],simulated=True)
                b.capture=capture
                cfg=ScanConfig(profile='pnp_small',tx1_stop_v=.02,uce_values_v=(1,),settle_s=0,curve_settle_s=0,frame_gap_s=0,adaptive_settle_v=0)
                path,state=run_scan(b,c,f,cfg,folder)
                self.assertEqual(state['status'],'failed')
                self.assertIn('clipped',state['error'])
                self.assertFalse(any(b.enabled))

    def test_pnp_ac_approximates_collector_current_by_emitter(self):
        import math
        c=Calibration(ROOT/'data');f=Frontend();b=SimulatedBoard(c,f)
        stop=threading.Event()
        def capture(count):
            channels=[]
            for rms,cal in zip((.0209/math.sqrt(2)*9.78,.020/math.sqrt(2)*.206),(c.rx1,c.rx2)):
                channels.append(dict(rms_code=rms/(abs(cal['slope_nv_per_code'])/1e9),fault_count=0))
            return dict(simulated=True,channels=channels)
        b.capture_statistics=capture
        with tempfile.TemporaryDirectory() as folder:
            path,state=run_ac_scan(b,c,f,AcScanConfig(profile='pnp_small',settle_s=0,repeat_count=2),folder,stop,
                                  emit=lambda kind,row:stop.set() if kind=='point' else None)
            self.assertEqual(state['status'],'cancelled',state.get('error'))
            with (path/'points.csv').open(encoding='utf-8-sig') as stream:row=next(csv.DictReader(stream))
            ib=(.021-.0209)/100
            self.assertAlmostEqual(float(row['source_node_v_peak']),.021)
            self.assertAlmostEqual(float(row['input_node_v_peak']),.0209)
            self.assertAlmostEqual(float(row['input_resistor_v_peak']),.0001)
            self.assertAlmostEqual(float(row['output_node_v_peak']),.020)
            self.assertAlmostEqual(float(row['emitter_current_a_peak']),.0002)
            self.assertAlmostEqual(float(row['output_current_a_peak']),.0002)
            self.assertAlmostEqual(float(row['gain']),200.)
            self.assertAlmostEqual(float(row['gain']),.0002/ib)
            self.assertAlmostEqual(float(row['input_resistance_ohm']),20900.)
            self.assertIn('not_measured',row['phase_basis'])
            self.assertIn('approximation',row['current_basis'])

    def test_pnp_ac_rejects_zero_or_negative_amplitude_difference(self):
        import math
        for vb in (.021,.022):
            with self.subTest(vb=vb),tempfile.TemporaryDirectory() as folder:
                c=Calibration(ROOT/'data');f=Frontend();b=SimulatedBoard(c,f)
                def capture(count):
                    channels=[]
                    for rms,cal in zip((vb/math.sqrt(2)*9.78,.020/math.sqrt(2)*.206),(c.rx1,c.rx2)):
                        channels.append(dict(rms_code=rms/(abs(cal['slope_nv_per_code'])/1e9),fault_count=0))
                    return dict(simulated=True,channels=channels)
                b.capture_statistics=capture
                path,state=run_ac_scan(b,c,f,AcScanConfig(profile='pnp_small',settle_s=0,repeat_count=2),folder)
                self.assertEqual(state['status'],'failed')
                self.assertIn('激励减 VB 不为正',state['error'])
                self.assertEqual(state['points'],0)
                self.assertFalse(any(b.enabled))

    def test_ac_fault_retains_statistics_and_completed_points(self):
        c=Calibration(ROOT/'data');f=Frontend();b=SimulatedBoard(c,f);b.gpio_value=0x55
        original=b.capture_statistics
        calls=[0]
        def capture(count):
            stats=original(count);calls[0]+=1
            if calls[0]==3:stats['channels'][0]['fault_count']=1
            return stats
        b.capture_statistics=capture
        with tempfile.TemporaryDirectory() as folder:
            d,s=run_ac_scan(b,c,f,AcScanConfig(settle_s=0,repeat_count=2),folder)
            self.assertEqual(s['status'],'failed')
            self.assertIn('clipped',s['error'])
            raw=[json.loads(v) for v in (d/'statistics.jsonl').read_text().splitlines()]
            self.assertEqual(len(raw),3)
            self.assertEqual(raw[-1]['statistics']['channels'][0]['fault_count'],1)
            with (d/'points.csv').open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),1)
            self.assertFalse(any(b.enabled));self.assertEqual(b.gpio_value,0x55)

    def test_source_feedback_range_rejects_over_two_volts_before_io(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Session(ROOT/'data',folder,simulated=True);s.initialize()
            before=s.board.gpio_value
            with self.assertRaisesRegex(ValueError,'RX1'):
                s.scan(dict(measurement='output',config=dict(tx2_control_stop_v=1.7)))
            self.assertEqual(s.board.gpio_value,before)
            self.assertFalse(any(s.board.enabled));s.close()

    def test_flat_collector_response_is_not_zero_percent_perfect_linearity(self):
        with self.assertRaisesRegex(ValueError,'span'):
            analyze_beta_linearity([dict(tx1_v=v,ic_a=.01) for v in (.1,.2,.3)],drop_initial=0,moving_average_window=1)

if __name__=='__main__':unittest.main()
