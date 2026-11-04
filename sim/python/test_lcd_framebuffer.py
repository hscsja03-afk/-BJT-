import base64
import unittest
import zlib
from unittest.mock import patch
import numpy as np
from zynq_bjt.lcd import LcdDemo,frame_pixels
from zynq_bjt.lcd_framebuffer import Framebuffer
from zynq_bjt.lcd_stream import decode_pixels


class Buffer(np.ndarray):
    def flush(self):self.flushes+=1
    def freebuffer(self):self.freed=True


class IO:
    def __init__(self):self.status=0;self.writes=[]
    def read(self,address):return self.status
    def write(self,address,value):self.writes.append((address,value))


class FramebufferTests(unittest.TestCase):
    def make(self):
        buffers=[]
        def allocate(shape,dtype):
            b=np.zeros(shape,dtype=dtype).view(Buffer)
            b.physical_address=0x100000+len(buffers)*0x200000
            b.flushes=0;b.freed=False;buffers.append(b)
            return b
        io=IO();return Framebuffer(io,allocate),io,buffers

    def ack(self,f,io):
        io.status=f.buffers[f.pending[0]].physical_address|1
        return f.update()

    def test_swap_queued_latest_and_patch_only_back_buffer(self):
        f,io,b=self.make()
        a=np.full((600,1024),0x1234,dtype='<u2')
        self.assertEqual(f.update(a.tobytes())['remaining'],1)
        np.testing.assert_array_equal(b[0],a)
        self.ack(f,io);before=b[0].copy()
        c=a.copy();c[15,25]=0xffff
        f.update(c.tobytes())
        np.testing.assert_array_equal(b[0],before)
        d=c.copy();d[35,45]=0xabcd
        f.update(d.tobytes())
        self.assertEqual(f.front,0)
        result=self.ack(f,io)
        # Old front is now the back buffer, so only two pixel spans change.
        self.assertEqual(result['writes'],2)
        np.testing.assert_array_equal(b[1],c)
        self.assertEqual(self.ack(f,io)['remaining'],0)
        np.testing.assert_array_equal(b[f.front],d)
        self.assertEqual(f.update(d.tobytes()),dict(writes=0,remaining=0))
        io.status=0;f.close();self.assertTrue(all(x.freed for x in b))

    def test_stop_timeout_never_frees_active_memory(self):
        f,io,b=self.make();io.status=3
        with patch('zynq_bjt.lcd_framebuffer.time.monotonic',side_effect=[0,2]):
            with self.assertRaises(TimeoutError):f.close()
        self.assertFalse(any(x.freed for x in b))
        io.status=0;f.close()

    def test_bad_payload_does_not_write_or_queue(self):
        f,io,b=self.make()
        with self.assertRaises(ValueError):f.update(b'bad')
        self.assertEqual(io.writes,[]);self.assertIsNone(f.queued)
        f.close()

    def test_rgb565_render_and_bounded_decode(self):
        from PIL import Image
        primaries=Image.new('RGB',(3,1));primaries.putdata([(255,0,0),(0,255,0),(0,0,255)])
        self.assertEqual(frame_pixels(primaries),bytes.fromhex('00f8e0071f00'))
        m=LcdDemo(rgb565=True);m.has_data=True
        frame=m.render();pixels=frame_pixels(frame)
        values=np.frombuffer(pixels,dtype='<u2')
        self.assertEqual(frame.size,(1024,600));self.assertGreater(len(np.unique(values)),100)
        request=dict(native=True,pixel_format='rgb565',pixels=base64.b64encode(zlib.compress(pixels)).decode())
        self.assertEqual(decode_pixels(request),(pixels,True))
        request['pixels']=base64.b64encode(zlib.compress(pixels+b'!')).decode()
        with self.assertRaises(ValueError):decode_pixels(request)
        request['pixels']=base64.b64encode(zlib.compress(pixels)).decode();request['pixel_format']='indexed4'
        with self.assertRaises(ValueError):decode_pixels(request)


if __name__=='__main__':unittest.main()
