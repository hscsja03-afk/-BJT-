import threading
import unittest
import csv
import json
import tempfile
from pathlib import Path
from zynq_bjt.lcd import LcdDemo, image_words, unpack_words
from zynq_bjt.mmio import AddaCore
from zynq_bjt.lcd_records import load_latest, make_plot


class LcdTests(unittest.TestCase):
    def test_incremental_time_budget_yields_before_full_batch(self):
        from unittest.mock import patch
        class IO:
            def read(self,address):return 0x40000000
            def write(self,*args):pass
        core=AddaCore.__new__(AddaCore);core.io=IO();core.lock=threading.RLock()
        with patch('zynq_bjt.mmio.time.monotonic',side_effect=[0,.031]):
            result=core.display_update(bytes([3])*153600,8192)
        self.assertEqual(result,dict(writes=128,remaining=76800-128))

    def test_incremental_budget_delta_and_cache_invalidation(self):
        class IO:
            def __init__(self):self.writes=[]
            def read(self,address):return 0x40000000
            def write(self,*args):self.writes.append(args)
        core=AddaCore.__new__(AddaCore);core.io=IO();core.lock=threading.RLock()
        pixels=bytes([3])*(512*300)
        result=core.display_update(pixels,1024)
        self.assertEqual(result,dict(writes=1024,remaining=76800-1024))
        while result['remaining']:
            result=core.display_update(max_writes=1024)
            self.assertLessEqual(result['writes'],1024)
        words=[value for address,value in core.io.writes if address==0x6c]
        self.assertEqual(unpack_words(words).tobytes(),pixels)
        self.assertNotIn(0xc0000000,words)
        core.io.writes.clear()
        self.assertEqual(core.display_update(pixels)['writes'],0)
        changed=bytearray(pixels);changed[8000]=7;changed[8001]=9
        core.io.writes.clear();result=core.display_update(bytes(changed))
        self.assertEqual(result,dict(writes=1,remaining=0))
        self.assertEqual(core.io.writes[0],(0x6c,0x80000000|4000|(0x97<<17)))
        core.display_text(1,['SCAN'])
        self.assertEqual(core.display_update(bytes(changed),1)['remaining'],76799)

    def test_partial_frame_replacement_matches_target_and_rejects_invalid(self):
        class IO:
            def __init__(self):self.writes=[]
            def read(self,address):return 0x40000000
            def write(self,*args):self.writes.append(args)
        core=AddaCore.__new__(AddaCore);core.io=IO();core.lock=threading.RLock()
        core.display_update(bytes([2])*153600,8)
        target=bytes([5])*153600
        result=core.display_update(target,4096)
        while result['remaining']:result=core.display_update(max_writes=4096)
        self.assertEqual(unpack_words([v for a,v in core.io.writes if a==0x6c]).tobytes(),target)
        before=len(core.io.writes)
        for pixels,budget in ((bytes([16])*153600,8),(b'bad',8),(None,100000)):
            with self.assertRaises(ValueError):core.display_update(pixels,budget)
        self.assertEqual(len(core.io.writes),before)

    def test_frequency_and_capture_choices(self):
        model=LcdDemo();model.tx=2
        seen=set()
        for _ in range(8):
            seen.add(model.frequency);model.action('frequency')
        self.assertIn(5000000,seen)
        self.assertIn(3000000,seen)
        model.frequency=5000000;model.action('wave')
        self.assertEqual(model.frequency,1000000)
        for _ in range(8):
            model.action('frequency');self.assertLessEqual(model.frequency,1000000)
        points=set();strides=set()
        for _ in range(5):
            points.add(model.sample_count);model.action('points')
            strides.add(model.sample_stride);model.action('stride')
        self.assertEqual(points,{256,512,1024,2048,4096})
        self.assertEqual(strides,{1,4,16,64,256})

    def test_saved_input_is_profile_filtered_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            for profile in ('npn_small','pnp_big'):
                run=directory/profile;run.mkdir()
                (run/'run.json').write_text(json.dumps(dict(config=dict(profile=profile),measurement='input',status='complete',simulated=False)))
                (run/'points.csv').write_text('curve,ube_v,ib_estimated_a\n0,0.6,0.00001\n0,0.7,0.00002\n')
            before={str(p):p.read_bytes() for p in directory.rglob('*') if p.is_file()}
            result=load_latest(directory,directory,'pnp_big','输入')
            self.assertEqual(result['xlabel'],'UEB / V')
            self.assertEqual(result['curves'][0][0],[(.6,10),(.7,20)])
            self.assertTrue(result['source'].endswith('pnp_big'))
            self.assertEqual(before,{str(p):p.read_bytes() for p in directory.rglob('*') if p.is_file()})

    def test_missing_early_fit_is_not_fabricated(self):
        result=make_plot([dict(curve='0',uce_v='1',ic_a='.001',ib_estimated_a='.00001')],dict(simulated=False),'Early')
        self.assertEqual(result['curves'],[])

    def test_pages_and_wire_format(self):
        model = LcdDemo()
        for page in ('TX', 'RX', 'IO', 'BJT'):
            model.action(page)
            model.action('single')
            image = model.render()
            words = image_words(image)
            self.assertEqual(len(words), 76802)
            self.assertEqual(unpack_words(words).tobytes(), image.tobytes())
            self.assertEqual(words[-1], 0xc0000001)

    def test_touch_stop_and_bounds(self):
        m = LcdDemo()
        m.render()
        self.assertEqual(m.touch(50, 560), 'TX')
        m.render()
        m.touch(800, 130)
        self.assertTrue(m.enabled[0])
        m.action('io6')
        m.action('run')
        m.touch(900, 560)
        self.assertEqual((m.enabled, m.gpio, m.running), ([False]*3, 0, False))
        for _ in range(100): m.action('minus')
        self.assertEqual(m.volts[0], 0)
        self.assertIsNone(m.touch(1024, 600))

    def test_old_bitstream_no_writes(self):
        class IO:
            def __init__(self): self.writes = []
            def read(self, address): return 0
            def write(self, *args): self.writes.append(args)
        core = AddaCore.__new__(AddaCore)
        core.io, core.lock = IO(), threading.RLock()
        with self.assertRaises(RuntimeError): core.display_image(LcdDemo().render())
        self.assertEqual(core.io.writes, [])
        core.io.read = lambda address: 0x40000000
        core.display_image(LcdDemo().render())
        self.assertEqual(core.io.writes[0], (0x68, 1))
        self.assertEqual(core.io.writes[-1], (0x6c, 0xc0000001))
        words=[value for address,value in core.io.writes if address==0x6c]
        core.io.writes.clear()
        core.display_pixels(LcdDemo().render().tobytes())
        self.assertEqual([value for address,value in core.io.writes if address==0x6c],words)
        core.io.writes.clear()
        with self.assertRaises(ValueError):core.display_pixels(bytes([16])*(512*300))
        self.assertEqual(core.io.writes,[])

    def test_modes_polarity_and_hold(self):
        m = LcdDemo()
        m.action('BJT')
        for _ in range(4):
            m.action('mode'); m.action('single')
            self.assertEqual(m.render().size, (512, 300))
        m.action('polarity')
        self.assertTrue(m.pnp)
        self.assertFalse(m.has_data)
        m.action('RX'); m.action('single')
        first = m.render().tobytes()
        m.action('stop')
        self.assertEqual(first, m.render().tobytes())


if __name__ == '__main__': unittest.main()
