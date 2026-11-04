import base64
import threading
import unittest
import zlib
from types import SimpleNamespace

from zynq_bjt.lcd import LcdDemo, image_words, unpack_words
from zynq_bjt.mmio import AddaCore
from zynq_bjt.desktop_session import Session


class NativeLcdTests(unittest.TestCase):
    def core(self,capability=0x48000000):
        class IO:
            def __init__(self):self.writes=[]
            def read(self,address):return capability if address==0x0c else 0
            def write(self,address,value):self.writes.append((address,value))
        core=AddaCore.__new__(AddaCore);core.io=IO();core.lock=threading.RLock()
        return core

    def test_native_render_wire_format_and_touch(self):
        import numpy as np
        native=LcdDemo(native=True);native.has_data=True
        frame=native.render();self.assertEqual(frame.size,(1024,600))
        words=image_words(frame)
        self.assertEqual(words[-1],0xc0000003)
        self.assertEqual(unpack_words(words,native=True).tobytes(),frame.tobytes())
        pixels=np.asarray(frame)
        self.assertTrue((pixels[0::2,0::2]!=pixels[0::2,1::2]).any())
        self.assertEqual(native.touch(50,560),'TX')
        native.render();self.assertEqual(native.touch(900,560),'stop')

    def test_native_delta_last_pixel_and_resolution_transition(self):
        core=self.core();target=bytearray(1024*600);target[-2:]=bytes((9,14))
        result=core.display_update(bytes(target),native=True)
        while result['remaining']:result=core.display_update(native=True)
        words=[v for a,v in core.io.writes if a==0x6c]
        self.assertEqual(unpack_words(words,native=True).tobytes(),bytes(target))
        core.io.writes.clear();target[-1]=6
        result=core.display_update(bytes(target),native=True)
        self.assertEqual(result,dict(writes=1,remaining=0))
        self.assertEqual(core.io.writes[0],(0x6c,0xa0000000|307199|(0x69<<19)))
        with self.assertRaises(ValueError):core.display_update(native=False)
        core.io.writes.clear()
        result=core.display_update(bytes(512*300))
        while result['remaining']:result=core.display_update()
        words=[v for a,v in core.io.writes if a==0x6c]
        self.assertEqual(words[0],0xc0000000)
        self.assertEqual(unpack_words(words).tobytes(),bytes(512*300))

    def test_old_bitstream_rejects_native_before_writes(self):
        core=self.core(0x40000000)
        for action in (lambda:core.display_update(bytes(1024*600),native=True),
                       lambda:core.display_pixels(bytes(1024*600)),
                       lambda:core.display_image(LcdDemo(native=True).render())):
            with self.assertRaises(RuntimeError):action()
        self.assertEqual(core.io.writes,[])

    def test_endpoint_bounded_decompression_and_native_flag(self):
        core=self.core();session=Session.__new__(Session);session.simulated=False
        session.require_board=lambda:SimpleNamespace(core=core)
        encoded=lambda b:base64.b64encode(zlib.compress(b)).decode()
        result=session.lcd(dict(pixels=encoded(bytes(1024*600)),native=True,incremental=True,max_writes=1))
        self.assertEqual(result['remaining'],307199)
        before=len(core.io.writes)
        for pixels,native in ((bytes(1024*600+1),True),(bytes(1024*600),False),(b'bad',True)):
            with self.assertRaises(ValueError):session.lcd(dict(pixels=encoded(pixels),native=native,incremental=True))
        self.assertEqual(len(core.io.writes),before)


if __name__=='__main__':unittest.main()
