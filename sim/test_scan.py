from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/python'))
from zynq_bjt import Calibration, Frontend
from zynq_bjt.scan import ScanConfig, run_scan, reduce_frames, point_timing
from zynq_bjt.mmio import Frame
from zynq_bjt.simulation import SimulatedBoard

ROOT = Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    def test_fixture_mapping_uses_each_physical_connector_calibration(self):
        cal=Calibration(ROOT/'data')
        # Physical RX1 carries VB/4=0.15 V; RX2 carries VC*0.206=0.206 V.
        words=[]
        for v,p in zip((.15,.206),(cal.rx1,cal.rx2)):
            code=round(p['zero_code_q16']/65536+v/(p['slope_nv_per_code']/1e9))
            words.append((code,)*1024)
        frames=[Frame(n,tuple(words),(50e6,50e6),n,simulated=True) for n in (1,2)]
        row=reduce_frames(frames,cal,Frontend(),.01)
        self.assertAlmostEqual(row['uce_v'],1.0,places=3)
        self.assertAlmostEqual(row['ube_v'],.6,places=3)
        self.assertAlmostEqual(row['rx1_port_v'],.15,places=3)
        self.assertAlmostEqual(row['rx2_port_v'],.206,places=3)
        for cfg in (ScanConfig(collector_channel=0,base_channel=0),ScanConfig(collector_channel=2)):
            with self.assertRaises(ValueError):cfg.validate(cal,Frontend())

    def setUp(self):
        self.cal = Calibration(ROOT/'data'); self.front = Frontend()
        self.board = SimulatedBoard(self.cal, self.front)
        self.config = ScanConfig(tx1_stop_v=.06, tx1_step_v=.02, uce_values_v=(0, 1), relay_active_level=1,
            settle_s=0, curve_settle_s=0, frame_gap_s=0, frames_per_point=2, adaptive_settle_v=0)
        self.board.gpio(0x1f, 0x15)

    def test_adaptive_pacing_preserves_settling_on_changing_nodes(self):
        config = ScanConfig()
        previous = dict(ube_drift_v=.001, uce_drift_v=.001)
        self.assertEqual(point_timing(config, None, None), (.05, 3, .05, 'settling'))
        self.assertEqual(point_timing(config, previous, .1), (.05, 3, .05, 'settling'))
        self.assertEqual(point_timing(config, previous, .01), (.02, 2, .01, 'balanced'))
        previous['ube_drift_v'] = .006
        self.assertEqual(point_timing(config, previous, .01)[-1], 'settling')
        slower = replace(config, settle_s=.2, frames_per_point=5, frame_gap_s=.1)
        self.assertEqual(point_timing(slower, None, None), (.2, 5, .1, 'settling'))
        self.assertEqual(point_timing(replace(config, adaptive_settle_v=0), None, None)[-1], 'balanced')

    def test_segmented_sweep_keeps_fine_low_current_points_and_endpoint(self):
        values = ScanConfig().validate(self.cal, self.front)
        self.assertEqual(len(values), 25)
        self.assertEqual(values[:9], [.02,.07,.12,.17,.22,.27,.32,.37,.4])
        self.assertEqual(values[-1], 2.0)
        self.assertEqual(len(values), len(set(values)))
        uniform = replace(ScanConfig(), tx1_fine_stop_v=0).validate(self.cal, self.front)
        self.assertEqual(uniform[:3], [.02,.12,.22])
        narrow = replace(ScanConfig(), tx1_stop_v=.06).validate(self.cal, self.front)
        self.assertEqual(narrow, [.02,.06])
        for cfg in (replace(ScanConfig(),tx1_fine_step_v=0),replace(ScanConfig(),tx1_fine_stop_v=float('nan'))):
            with self.assertRaises(ValueError): cfg.validate(self.cal,self.front)

    def test_complete_keeps_raw_provenance_and_restores_gpio_with_all_outputs_off(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state = run_scan(self.board, self.cal, self.front, self.config, directory)
            self.assertEqual(state['status'], 'complete')
            self.assertEqual(state['points'], 6)
            raw = [json.loads(line) for line in (path/'frames.jsonl').read_text().splitlines()]
            self.assertEqual(len(raw), 18)
            self.assertTrue(all(x['frame']['simulated'] for x in raw))
            self.assertIn('not measured current', state['current_basis'])
            self.assertEqual(self.board.gpio()['output'], 0x15)
            self.assertFalse(self.board.output(0).enabled)
            self.assertFalse(self.board.output(1).enabled)
            self.assertFalse(self.board.output(2).enabled)
            self.assertEqual(self.board.display_lines[1], 'INPUT COMPLETE')

    def test_relay_scan_refuses_an_already_running_ac_source(self):
        self.board.enable(2,True)
        before=self.board.gpio_value
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError,'idle'):
                run_scan(self.board,self.cal,self.front,self.config,directory)
            self.assertEqual(self.board.gpio_value,before)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_cancellation_preserves_completed_point_and_cleans_up(self):
        event = threading.Event()
        def emit(kind, row):
            if kind == 'point': event.set()
        with tempfile.TemporaryDirectory() as directory:
            path, state = run_scan(self.board, self.cal, self.front, self.config, directory, event, emit=emit)
            self.assertEqual(state['status'], 'cancelled')
            self.assertEqual(state['points'], 1)
            self.assertTrue((path/'points.csv').exists())
            self.assertFalse(any(self.board.enabled[:2]))
            self.assertEqual(self.board.gpio()['output'], 0x15)

    def test_clipped_raw_frame_is_retained_before_rejection(self):
        capture = self.board.capture
        def clipped():
            frame = capture()
            return replace(frame, words=((65535,)*1024, frame.words[1]))
        self.board.capture = clipped
        with tempfile.TemporaryDirectory() as directory:
            path, state = run_scan(self.board, self.cal, self.front, self.config, directory)
            self.assertEqual(state['status'], 'failed')
            self.assertIn('clipped', state['error'])
            self.assertIn('65535', (path/'frames.jsonl').read_text())
            self.assertEqual(state['points'], 0)
            self.assertFalse(any(self.board.enabled[:2]))

    def test_changed_hardware_qualification_refuses_before_any_output(self):
        self.board.simulated = False
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'qualified'):
                run_scan(self.board, self.cal, self.front, self.config, directory)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertFalse(any(self.board.enabled))

    def test_feedback_removes_fixture_offset_and_records_adjustments(self):
        capture=self.board.capture
        p=self.cal.rx2
        shift=round(.279*.206/(p['slope_nv_per_code']/1e9))
        def offset():
            frame=capture()
            return replace(frame,words=(frame.words[0],tuple(v+shift for v in frame.words[1])))
        self.board.capture=offset
        cfg=replace(self.config,uce_values_v=(.5,),tx1_stop_v=.02)
        with tempfile.TemporaryDirectory() as directory:
            path,state=run_scan(self.board,self.cal,self.front,cfg,directory)
            self.assertEqual(state['status'],'complete',state.get('error'))
            self.assertEqual(state['points'],1)
            self.assertTrue(1<=len(state['bias_adjustments'])<=7)
            self.assertTrue(all(0<=v['tx2_after_v']<=.5/6 for v in state['bias_adjustments']))
            self.assertFalse(any(self.board.enabled))
        # The same positive offset makes 0 V unreachable with a positive-only DAC table.
        cfg=replace(cfg,uce_values_v=(0.,))
        with tempfile.TemporaryDirectory() as directory:
            _,state=run_scan(self.board,self.cal,self.front,cfg,directory)
            self.assertEqual(state['status'],'failed')
            self.assertEqual(state['points'],0)
            self.assertAlmostEqual(state['rejected_point']['uce_v'],.28,places=2)
            self.assertFalse(any(self.board.enabled))

    def test_negative_npn_base_feedback_is_not_a_valid_input_curve(self):
        capture=self.board.capture;p=self.cal.rx1
        code=round(p['zero_code_q16']/65536-.2/(p['slope_nv_per_code']/1e9))
        def negative_base():
            frame=capture()
            return replace(frame,words=((code,)*1024,frame.words[1]))
        self.board.capture=negative_base
        with tempfile.TemporaryDirectory() as directory:
            _,state=run_scan(self.board,self.cal,self.front,self.config,directory)
            self.assertEqual(state['status'],'failed')
            self.assertIn('NPN 基极反馈异常',state['error'])
            self.assertEqual(state['points'],0)
            self.assertFalse(any(self.board.enabled))

    def test_bias_rejection_retains_measured_point_and_mutes_outputs(self):
        capture = self.board.capture
        # A stuck feedback near 0.5 V must not become a valid 0 V curve.
        rx=self.cal.rx2
        code=round(rx['zero_code_q16']/65536 + .5*.206/(rx['slope_nv_per_code']/1e9))
        def stuck():
            frame=capture()
            return replace(frame,words=(frame.words[0],(code,)*1024))
        self.board.capture=stuck
        with tempfile.TemporaryDirectory() as directory:
            path,state=run_scan(self.board,self.cal,self.front,self.config,directory)
            self.assertEqual(state['status'],'failed')
            self.assertEqual(state['points'],0)
            saved=json.loads((path/'run.json').read_text(encoding='utf-8'))
            self.assertAlmostEqual(saved['rejected_point']['uce_v'],.5,places=3)
            self.assertEqual(saved['rejected_point']['uce_target_v'],0)
            self.assertIn('目标 UCE=0.0000 V',saved['error'])
            self.assertIn('RX2 节点反馈=',saved['error'])
            self.assertFalse(any(self.board.enabled))
            self.assertEqual(self.board.gpio()['output'],0x15)

    def test_duplicate_quantized_codes_and_unknown_relay_are_rejected(self):
        for cfg in (replace(self.config, tx1_step_v=.00001), replace(self.config, relay_active_level=None)):
            with self.assertRaises(ValueError): cfg.validate(self.cal, self.front)

    def test_modified_feedback_coefficient_preserves_independent_drive_mapping(self):
        front = Frontend(rx1_per_vc=.25)
        self.board = SimulatedBoard(self.cal, front)
        with tempfile.TemporaryDirectory() as directory:
            _, state = run_scan(self.board, self.cal, front, self.config, directory)
            self.assertEqual(state['status'], 'complete')
            self.assertEqual(state['frontend']['rx1_per_vc'], .25)


if __name__ == '__main__': unittest.main()
