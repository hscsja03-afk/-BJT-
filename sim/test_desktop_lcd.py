import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from zynq_bjt.desktop_lcd import SharedTransport, DesktopLcd


class TransportTests(unittest.TestCase):
    def test_lcd_cannot_overlap_scan_and_cancel_is_not_blocked(self):
        entered=threading.Event();release=threading.Event();cancelled=threading.Event()
        class Inner:
            def call(self,op,*args,**kwargs):
                entered.set();release.wait(2);return op
            def cancel(self):cancelled.set()
            def close(self):return 'closed'
        shared=SharedTransport(Inner())
        worker=threading.Thread(target=lambda:shared.call('scan'));worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertIsNone(shared.try_lcd({}))
            shared.cancel();self.assertTrue(cancelled.is_set())
        finally:release.set();worker.join(2)
        self.assertEqual(shared.try_lcd({}),'lcd')

    def test_stale_touch_and_previous_connection_are_discarded(self):
        class Var:
            def get(self):return True
            def set(self,value):pass
        lcd=DesktopLcd.__new__(DesktopLcd)
        transport=object()
        lcd.app=SimpleNamespace(transport=transport,busy=False,queue_reserved=lambda:False)
        lcd.enabled=Var();lcd.status=Var();lcd.generation=3;lcd.buttons=[((0,0,40,40),'power')]
        lcd.drop_touch=False;lcd.pending_action=None;lcd.action=lambda a:self.fail('stale touch executed')
        lcd.exchange_count=0;lcd.remaining=0;lcd.upload_digest=None
        result=dict(value=dict(touch=[10,10]),error=None,transport=transport,generation=2,
                    digest='old',buttons=lcd.buttons,uploaded=False)
        lcd.reply(result)
        result.update(transport=object(),generation=3);lcd.reply(result)

    def test_waveform_patch_keeps_unchanged_touch_buttons_responsive(self):
        class Var:
            def get(self):return True
            def set(self,value):pass
        lcd=DesktopLcd.__new__(DesktopLcd);transport=object();actions=[]
        lcd.app=SimpleNamespace(transport=transport,busy=False,queue_reserved=lambda:False)
        lcd.enabled=Var();lcd.status=Var();lcd.generation=3
        lcd.buttons=[((0,0,40,40),'single')];lcd.drop_touch=False;lcd.exchange_count=0
        lcd.upload_digest=None;lcd.remaining=0;lcd.action=actions.append
        lcd.reply(dict(value=dict(touch=[10,10],remaining=500),error=None,transport=transport,
                       generation=3,digest='new-wave',buttons=lcd.buttons,uploaded=True))
        self.assertEqual(actions,['single'])


class SharedUiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from zynq_bjt.desktop import App
        from zynq_bjt.desktop_transport import LocalTransport
        self.temp=tempfile.TemporaryDirectory()
        self.root=tk.Tk();self.root.withdraw()
        self.app=App(self.root,workspace=self.temp.name)
        self.errors=[];self.app.error=lambda value:self.errors.append(str(value))
        local=LocalTransport(self.app.data,Path(self.temp.name)/'results')
        class FakeBoard:
            simulated=False;alive=True
            def __init__(self):self.calls=[];self.touch=None
            def call(inner,op,args=None,timeout=120):
                inner.calls.append((op,args))
                if op=='lcd':
                    touch,inner.touch=inner.touch,None
                    return dict(touch=touch)
                if op=='lcd_stream':return dict(stream=True,accepted=True)
                value=local.call(op,args,timeout)
                if isinstance(value,dict):value=dict(value,simulated=False)
                return value
            def prepare(inner):local.prepare()
            def cancel(inner):local.cancel()
            def close(inner):inner.alive=False;return local.close()
        self.board=FakeBoard();self.app.transport=SharedTransport(self.board)
        self.app.render_status(self.app.transport.call('initialize'))
        self.app.lcd.connected()

    def wait(self,predicate,seconds=4):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            self.root.update()
            if predicate():return
            time.sleep(.01)
        self.fail('timed out waiting for GUI')

    def tearDown(self):
        self.app.scope.stop();self.app.lcd.close()
        if self.app.transport:self.app.transport.close()
        for job in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',job)
        self.root.destroy();self.temp.cleanup()

    def test_scope_and_lcd_use_the_same_transport_without_stopping_run(self):
        app=self.app
        app.show_page('scope');app.scope.run()
        self.wait(lambda:app.last_frame is not None)
        self.wait(lambda:any(op=='lcd' for op,args in self.board.calls))
        self.assertTrue(app.scope.accepting)
        self.assertIs(app.transport.inner,self.board)
        app.scope.stop();self.wait(lambda:not app.busy)
        app.lcd.action('IO');app.lcd.action('io0')
        self.wait(lambda:not app.busy)
        self.assertEqual(app.last_status['gpio']['output'],1)
        self.wait(lambda:app.lcd.model.gpio==1)
        self.assertEqual(self.errors,[])

    def test_output_requires_existing_confirmation_and_stop_clears_outputs(self):
        app=self.app
        app.show_page('tx');app.lcd.model.tx=2
        app.confirmed.set(False);app.lcd.action('power')
        self.wait(lambda:not app.busy)
        self.assertFalse(any(v['enabled'] for v in app.last_status['outputs']))
        # Only an explicit desktop confirmation can authorize a touch start.
        app.confirmed.set(True);app.lcd.action('power')
        self.wait(lambda:not app.busy)
        self.assertTrue(app.last_status['outputs'][2]['enabled'])
        app.lcd.action('stop');self.wait(lambda:not app.busy)
        self.assertFalse(any(v['enabled'] for v in app.last_status['outputs']))

    def test_lcd_preserves_scope_auto_window_and_raw_units(self):
        app=self.app
        app.show_page('scope');app.scope.sample_count.set('512');app.scope.sample_stride.set('自动窗口')
        app.scope.mode.set('Auto');app.lcd.action('single')
        self.wait(lambda:app.last_frame is not None and not app.busy)
        self.assertEqual(app.scope.sample_stride.get(),'自动窗口')
        app.lcd.sync();self.assertEqual(app.lcd.model.sample_count,512)
        app.scope.units.set('ADC 原始码');app.lcd.sync()
        self.assertEqual(app.lcd.model.rx_units,'ADC 码')
        self.assertGreater(max(y for _,y in app.lcd.model.rx_trace[0]),10000)
        app.last_frame=None;app.lcd.sync();self.assertFalse(app.lcd.model.has_data)

    def test_curve_frames_are_sent_while_scan_is_busy_and_touch_is_paused(self):
        import base64,zlib
        app=self.app;app.show_page('output')
        request={};app.lcd.begin_scan(request)
        self.assertIn('lcd_stream',request)
        app.busy=True;app.active_job='scan'
        try:
            app.rows=[dict(curve=0,uce_v=.2,ic_a=.001,ib_estimated_a=10e-6)]
            self.wait(lambda:any(op=='lcd_stream' for op,args in self.board.calls))
            first=[args for op,args in self.board.calls if op=='lcd_stream'][-1]
            self.assertEqual(first['stream_id'],request['lcd_stream']['id'])
            app.rows.append(dict(curve=0,uce_v=1,ic_a=.002,ib_estimated_a=10e-6))
            self.wait(lambda:len([op for op,args in self.board.calls if op=='lcd_stream'])>=2)
            second=[args for op,args in self.board.calls if op=='lcd_stream'][-1]
            self.assertNotEqual(zlib.decompress(base64.b64decode(first['pixels'])),
                                zlib.decompress(base64.b64decode(second['pixels'])))
            self.assertIn('2 个测点',app.lcd.model.note)
            self.assertTrue(app.lcd.drop_touch)
            self.assertEqual(self.errors,[])
        finally:app.busy=False;app.active_job=None


if __name__=='__main__':unittest.main()
