"""Retry only transient drift, preserve rejected ADC evidence, bound failures."""
from dataclasses import replace
import csv,json,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.frontend import Calibration,Frontend
from zynq_bjt.mmio import Frame
from zynq_bjt.scan import ScanConfig,run_scan,NodeDriftError,reduce_frames
from zynq_bjt.simulation import SimulatedBoard


class Tests(unittest.TestCase):
    def setUp(self):
        self.cal=Calibration(ROOT/'data');self.front=Frontend()
        self.board=SimulatedBoard(self.cal,self.front);self.board.gpio(127,0x15)
        self.config=ScanConfig(tx1_start_v=.02,tx1_stop_v=.02,uce_values_v=(1,),settle_s=0,
            curve_settle_s=0,discard_frames=0,frames_per_point=2,frame_gap_s=0,adaptive_settle_v=0)
        self.count=0;self.events=[]

    def frame(self,base_port):
        self.count+=1
        words=[]
        for v,p in zip((base_port,.206),(self.cal.rx1,self.cal.rx2)):
            code=round(p['zero_code_q16']/65536+v/(p['slope_nv_per_code']/1e9))
            words.append((code,)*1024)
        return Frame(self.count,tuple(words),(50e6,50e6),self.count,simulated=True)

    def run_case(self,mode,cancel_on_wait=False):
        def capture():
            port=(.25 if self.count%2==0 else .2) if mode=='persistent' or (mode=='transient' and self.count<2) else .15
            frame=self.frame(port)
            if mode=='clipped':frame=replace(frame,words=((65535,)*1024,frame.words[1]))
            return frame
        self.board.capture=capture;cancel=threading.Event()
        def emit(kind,value):
            self.events.append((kind,value))
            if cancel_on_wait and kind=='log':cancel.set()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder,patch('zynq_bjt.scan.NODE_SETTLE_RETRY_DELAYS',(0,0,0,0)):
            path,state=run_scan(self.board,self.cal,self.front,self.config,folder,cancel,emit=emit)
            raw=[json.loads(s) for s in (path/'frames.jsonl').read_text().splitlines()]
            with (path/'points.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        self.assertFalse(any(self.board.enabled));self.assertEqual(self.board.gpio()['output'],0x15)
        return state,raw,rows

    def test_transient_is_reacquired_and_only_stable_frames_form_point(self):
        state,raw,rows=self.run_case('transient')
        self.assertEqual(state['status'],'complete',state.get('error'))
        self.assertEqual(state['points'],1);self.assertEqual(len(state['node_settle_attempts']),1)
        self.assertEqual([r['settle_attempt'] for r in raw],[0,0,1,1])
        self.assertAlmostEqual(float(rows[0]['vb_v']),.6,delta=.001)
        self.assertEqual(rows[0]['frame_sequences'],'3;4');self.assertEqual(rows[0]['settle_retries'],'1')
        self.assertEqual(len([e for e in self.events if e[0]=='point']),1)

    def test_already_stable_does_not_wait_or_capture_extra(self):
        state,raw,rows=self.run_case('stable')
        self.assertEqual(state['status'],'complete');self.assertNotIn('node_settle_attempts',state)
        self.assertEqual(len(raw),2);self.assertEqual(rows[0]['settle_retries'],'0')

    def test_persistent_drift_stops_after_four_retries_with_channel_details(self):
        state,raw,rows=self.run_case('persistent')
        self.assertEqual(state['status'],'failed');self.assertEqual(state['points'],0)
        self.assertEqual(len(raw),10);self.assertEqual(len(state['node_settle_attempts']),5)
        self.assertIn('RX1 的 VB',state['error']);self.assertGreater(state['rejected_node_drift']['base_drift_v'],.05)
        self.assertEqual(rows,[])

    def test_cancellation_during_wait_does_not_take_another_frame(self):
        state,raw,rows=self.run_case('transient',True)
        self.assertEqual(state['status'],'cancelled');self.assertEqual(len(raw),2);self.assertEqual(rows,[])

    def test_clipping_is_immediate_and_never_retried(self):
        state,raw,rows=self.run_case('clipped')
        self.assertEqual(state['status'],'failed');self.assertIn('clipped',state['error'])
        self.assertNotIn('node_settle_attempts',state);self.assertEqual(len(raw),2);self.assertEqual(rows,[])


if __name__=='__main__':unittest.main()
