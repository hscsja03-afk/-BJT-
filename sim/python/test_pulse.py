"""Pulse acquisition and timing regression tests."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from dataclasses import asdict, replace

from zynq_bjt.frontend import Calibration, Frontend
from zynq_bjt.desktop_session import Session
from zynq_bjt.characteristics import OutputScanConfig, BetaScanConfig, run_output_scan
from zynq_bjt.pulse import table, plateau, PlateauRejected
from zynq_bjt.mmio import Frame

ROOT=Path(__file__).resolve().parents[2]


class NoWait:
    def is_set(self):return False
    def wait(self, seconds):return False
    def clear(self):pass
    def set(self):pass


class PulseTests(unittest.TestCase):
    def test_recorded_zero_point_with_spikes_is_not_a_pulse_edge(self):
        frame=Frame(**json.loads((ROOT/'sim/fixtures/pulse_zero_noise.json').read_text()))
        cfg=OutputScanConfig(profile='npn_big',scan_mode='脉冲')
        means,selection=plateau(frame,self.s.cal,cfg,0)
        self.assertGreater(selection['channel_diagnostics'][1]['raw_span_v'],.07)
        self.assertLess(selection['channel_diagnostics'][1]['central_90_span_v'],.02)
        self.assertLess(abs(self.s.cal.port_v(means[0],0)/.206),.02)

    def test_edges_drift_low_and_stuck_high_are_rejected(self):
        cfg=OutputScanConfig(profile='npn_big',scan_mode='脉冲')
        def frame(vs):
            words=[]
            for cal in (self.s.cal.rx1,self.s.cal.rx2):
                words.append(tuple(round(v*.206*1e9/cal['slope_nv_per_code']+cal['zero_code_q16']/65536) for v in vs))
            return Frame(1,tuple(words),(195312.5,)*2,0)
        for values,target in (([0]*1024,1.2),([0]*512+[1.2]*512,1.2),
                              ([1.2+i*.0002 for i in range(1024)],1.2),([1.2]*1024,0)):
            with self.assertRaises(PlateauRejected):plateau(frame(values),self.s.cal,cfg,target)
        plateau(frame([1.2]*1024),self.s.cal,cfg,1.2)

    def test_adjustable_timing_is_validated_and_saved(self):
        samples,plan=table(self.s.cal,.2,125000000,5,30)
        self.assertEqual(samples.count(self.s.cal.dac_code(1,.2)[0]),77)
        self.assertEqual(plan['requested_frequency_hz'],5)
        for freq,duty in ((0,20),(51,20),(10,0),(10,51),(50,5)):
            with self.assertRaises(ValueError):table(self.s.cal,.2,125000000,freq,duty)
        result=self.s.scan(dict(measurement='output',profile='npn_big',method='pulse',allow_reference=True,
            config=dict(base_control_v=[.02],tx2_control_start_v=.1,tx2_control_stop_v=.1,
                        pulse_frequency_hz=5,pulse_duty_percent=30,settle_s=0,frames_per_point=2)))
        self.assertEqual(result['state']['status'],'complete',result['state'].get('error'))
        self.assertEqual(result['state']['source_parameters']['pulse_frequency_hz'],5)
        self.assertEqual(result['state']['pulse_actual']['requested_duty_percent'],30)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=Session(ROOT/'data',self.temp.name,simulated=True)
        self.s.initialize();self.s.cancel=NoWait()
    def tearDown(self):self.s.close();self.temp.cleanup()

    def test_quantized_pulse_levels_and_duty(self):
        samples,plan=table(self.s.cal,.2,125000000)
        self.assertEqual(len(samples),256)
        self.assertEqual(samples.count(self.s.cal.dac_code(1,.2)[0]),51)
        self.assertEqual(samples[-1],self.s.cal.dac_code(1,0)[0])
        self.assertAlmostEqual(plan['frequency_hz'],10,delta=.02)
        for v in (-.1,1.9,float('nan')):
            with self.assertRaises(ValueError):table(self.s.cal,v,125000000)

    def test_output_and_beta_use_pulse_and_cleanup(self):
        for measurement,config in [('output',dict(base_control_v=(.02,.04),tx2_control_stop_v=.2,tx2_control_step_v=.1)),
                                   ('beta',dict(tx1_start_v=.02,tx1_stop_v=.04,tx1_step_v=.01,drop_initial_points=0,moving_average_window=1))]:
            result=self.s.scan(dict(measurement=measurement,profile='npn_big',method='pulse',
                config=dict(config,settle_s=0,frames_per_point=2),allow_reference=True))
            state=result['state'];self.assertEqual(state['status'],'complete',state.get('error'))
            self.assertEqual(state['method'],'pulse');self.assertFalse(any(self.s.board.enabled))
            self.assertEqual(Path(result['directory']).parent.name,'脉冲')
            from zynq_bjt.result_paths import relative_run
            self.assertEqual(relative_run(result['relative_directory']).parts[-2],'脉冲')
            raw=[json.loads(s) for s in (Path(result['directory'])/'frames.jsonl').read_text().splitlines()]
            self.assertTrue(any(r.get('pulse_accepted') is False for r in raw))
            self.assertTrue(any(r.get('pulse_accepted') is True for r in raw))
            self.assertTrue(all(r['frame']['sample_stride']==256 for r in raw if 'frame' in r))
            self.assertEqual(state['config']['collector_resistor_ohm'],1)

    def test_faults_not_retried_as_low_plateaus(self):
        capture=self.s.board.capture
        def faulty(**kwargs):
            f=capture(**kwargs);w=list(f.words);w[0]=tuple(c|0x10000 for c in w[0]);return replace(f,words=tuple(w))
        self.s.board.capture=faulty
        r=self.s.scan(dict(measurement='output',profile='npn_big',method='pulse',
            config=dict(base_control_v=(.02,),tx2_control_start_v=.1,tx2_control_stop_v=.1,settle_s=0),allow_reference=True))
        self.assertEqual(r['state']['status'],'failed');self.assertIn('overrange',r['state']['error'])
        self.assertFalse(any(self.s.board.enabled))

    def test_pnp_power_pulse_uses_emitter_sense_and_separate_folders(self):
        from zynq_bjt.result_paths import relative_run,group
        for measurement,config in [('output',dict(base_control_v=(.02,.04),tx2_control_start_v=.1,tx2_control_stop_v=.2,tx2_control_step_v=.1)),
                                   ('beta',dict(tx1_start_v=.02,tx1_stop_v=.04,tx1_step_v=.01,drop_initial_points=0,moving_average_window=1))]:
            result=self.s.scan(dict(measurement=measurement,profile='pnp_big',method='pulse',allow_reference=True,
                                    config=dict(config,collector_resistor_ohm=.5,settle_s=0,frames_per_point=2)))
            state=result['state'];self.assertEqual(state['status'],'complete',state.get('error'))
            self.assertTrue(state['simulated']);self.assertEqual(state['method'],'pulse')
            self.assertEqual(state['config']['collector_resistor_ohm'],.5)
            self.assertEqual(state['source_parameters']['gpio_value'],61)
            self.assertEqual(state['source_parameters']['pulse_hardware_validation'],'pending')
            self.assertEqual(relative_run(result['relative_directory']).parts[:3],('PNP大功率','输出特性' if measurement=='output' else '线性精度','脉冲'))
            self.assertNotEqual(group('pnp_big',measurement,'step'),group('pnp_big',measurement,'pulse'))
            raw=Path(result['directory'])/('output_points.csv' if measurement=='output' else 'beta_trace.csv')
            with raw.open(encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
            self.assertTrue(rows)
            for row in rows:
                self.assertEqual(float(row['vc_v']),0)
                self.assertAlmostEqual(float(row['uce_v']),float(row['ve_v']))
                self.assertAlmostEqual(float(row['ic_a']),(float(row['vcc_v'])-float(row['ve_v']))/.5)
            self.assertFalse(any(self.s.board.enabled));self.assertEqual(self.s.board.gpio()['output'],0)

    def test_incompatible_modes_rejected_before_output(self):
        for name,profile in [('input','npn_big'),('ac','npn_big'),('input','pnp_big'),('ac','pnp_big'),('output','pnp_small'),('beta','npn_small')]:
            with self.assertRaises(ValueError):self.s.scan(dict(measurement=name,profile=profile,method='pulse'))
            self.assertFalse(any(self.s.board.enabled))
        with self.assertRaises(ValueError):self.s.scan(dict(measurement='output',profile='npn_big',method='pulse',config={'scan_mode':'步进'}))


