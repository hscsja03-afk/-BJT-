"""Scanning keeps its worker ownership while receiving live LCD frames."""
import base64
import io
import json
import queue
import threading
import tempfile
import time
import unittest
import zlib
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from zynq_bjt.desktop_agent import serve
from zynq_bjt.desktop_lcd import SharedTransport
from zynq_bjt.lcd_stream import ScanDisplay, DisplayCancel
from zynq_bjt.lcd_records import make_plot
from zynq_bjt.runtime import Board


def packet(color, stream_id='scan-1'):
    return dict(pixels=base64.b64encode(zlib.compress(bytes([color])*153600)).decode(),
                native=False, stream_id=stream_id)


class StreamTests(unittest.TestCase):
    def test_receive_replaces_only_pending_frame_and_worker_finishes_current(self):
        calls=[]
        class Core:
            def display_update(self,pixels,budget,native=False):
                calls.append((threading.get_ident(), pixels))
                return dict(remaining=1 if pixels is not None else 0)
        display=ScanDisplay(Core(),'scan-1',False,lambda *args:None)
        def pump():
            display.last_pump=-1;display.pump()
        pump()  # finish pre-scan upload
        thread=threading.Thread(target=lambda:display.offer(packet(2)))
        thread.start();thread.join()
        self.assertEqual(len(calls),1)  # receive thread did no MMIO
        pump()  # begin frame 2
        display.offer(packet(5));display.offer(packet(6))
        pump()  # finish frame 2
        pump()  # skip obsolete 5, begin latest 6
        self.assertEqual([p[0] if p else None for _,p in calls],[None,2,None,6])
        self.assertEqual({ident for ident,_ in calls},{threading.get_ident()})
        self.assertFalse(display.offer(packet(7,'old-scan'))['accepted'])
        display.close()
        self.assertFalse(display.offer(packet(7))['accepted'])

    def test_cancel_remains_immediate_and_display_failure_is_nonfatal(self):
        class Core:
            def display_update(self,*args,**kwargs):raise RuntimeError('display unavailable')
        logs=[];display=ScanDisplay(Core(),'scan-1',False,lambda *args:logs.append(args))
        event=threading.Event();cancel=DisplayCancel(event,display)
        self.assertFalse(cancel.wait(0))
        self.assertEqual(len(logs),1);self.assertTrue(display.closed)
        event.set()
        begin=time.monotonic();self.assertTrue(cancel.wait(10))
        self.assertLess(time.monotonic()-begin,.1)

    def test_scan_ascii_status_cannot_replace_graph(self):
        board=Board.__new__(Board);board.scan_lcd_managed=True
        # No lock/core is necessary: managed text never reaches hardware.
        board.display_status(['CURVE 1/4'])

    def test_wire_mailbox_reply_arrives_before_scan_finishes(self):
        inputs=queue.Queue();started=threading.Event();received=threading.Event()
        closed=threading.Event();replies=[]
        class Input:
            def __iter__(self):
                while True:
                    value=inputs.get()
                    if value is None:return
                    yield value
        class Output:
            def write(self,line):
                msg=json.loads(line[len('ZBJT1 '):]);replies.append(msg)
                if msg.get('id')==2:received.set()
            def flush(self):pass
        class Session:
            cancel=threading.Event()
            def queue_scan_lcd(self,request):
                self.offered=request;return dict(stream=True,accepted=True)
            def dispatch(self,op,args,emit):
                started.set()
                self.assert_received=received.wait(2)
                self.cancel.wait(2)
                return dict(status='cancelled')
            def close(self):closed.set()
        session=Session();thread=threading.Thread(target=lambda:serve(session,Input(),Output()))
        thread.start()
        try:
            inputs.put(json.dumps(dict(id=1,op='scan'))+'\n')
            self.assertTrue(started.wait(1))
            inputs.put(json.dumps(dict(id=2,op='lcd_stream',args=packet(6)))+'\n')
            self.assertTrue(received.wait(1))
            self.assertFalse(any(r.get('id')==1 for r in replies))
            inputs.put(json.dumps(dict(op='cancel'))+'\n')
            deadline=time.monotonic()+2
            while not any(r.get('id')==1 for r in replies) and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(session.assert_received)
            self.assertTrue(any(r.get('id')==1 for r in replies))
        finally:
            inputs.put(None);thread.join(3)
        self.assertTrue(closed.is_set());self.assertFalse(thread.is_alive())

    def test_only_mailbox_operation_bypasses_long_command_lock(self):
        started=threading.Event();release=threading.Event();ops=[]
        class Inner:
            def call(self,op,*args,**kwargs):
                ops.append(op)
                if op=='scan':started.set();release.wait(2)
                return dict(stream=True,accepted=True)
        transport=SharedTransport(Inner())
        thread=threading.Thread(target=lambda:transport.call('scan'));thread.start()
        try:
            self.assertTrue(started.wait(1));self.assertIsNone(transport.try_lcd({}))
            self.assertTrue(transport.stream_lcd(packet(6))['accepted'])
            self.assertEqual(ops,['scan','lcd_stream'])
        finally:release.set();thread.join(2)

    def test_live_pnp_axis_and_cancel_label_are_localized(self):
        rows=[dict(curve=0,ube_v=.5,ib_estimated_a=1e-6)]
        plot=make_plot(rows,dict(config=dict(profile='pnp_big'),status='cancelled'),'输入')
        self.assertEqual(plot['xlabel'],'UEB / V')
        self.assertIn('已取消',plot['label']);self.assertIn('1 点',plot['label'])

    def test_session_scan_services_mailbox_during_measurement_and_restores_ownership(self):
        from zynq_bjt.desktop_session import Session
        from zynq_bjt.simulation import SimulatedBoard
        from zynq_bjt.frontend import Calibration,Frontend
        root=Path(__file__).resolve().parents[2]
        calls=[]
        class Core:
            io=SimpleNamespace(read=lambda address:0)
            def display_update(self,pixels,*args,**kwargs):
                calls.append(pixels);return dict(remaining=0)
        with tempfile.TemporaryDirectory() as folder:
            session=Session(root/'data',folder,simulated=True)
            session.board=SimulatedBoard(session.cal,session.front)
            session.board.core=Core()
            session.simulated=False
            session.status=lambda:dict(initialized=True)
            managed=[]
            def emit(kind,value):
                if kind=='point':
                    managed.append(session.board.scan_lcd_managed)
                    session.scan_display.last_pump=-1
                    self.assertTrue(session.queue_scan_lcd(packet(6))['accepted'])
            request=dict(measurement='output',profile='npn_small',fixture_confirmed=True,
                         allow_reference=True,config=dict(base_control_v=(.02,),tx2_control_stop_v=.1,
                         tx2_control_step_v=.1,settle_s=0,frames_per_point=2),
                         lcd_stream=dict(id='scan-1',native=None))
            result=session.scan(request,emit)
            self.assertEqual(result['state']['status'],'complete')
            self.assertTrue(managed and all(managed))
            self.assertTrue(any(pixels is not None for pixels in calls))
            self.assertIsNone(session.scan_display)
            self.assertFalse(session.board.scan_lcd_managed)
            self.assertFalse(session.queue_scan_lcd(packet(6))['accepted'])
            self.assertFalse(any(session.board.output(ch).enabled for ch in range(3)))


if __name__=='__main__':unittest.main()
