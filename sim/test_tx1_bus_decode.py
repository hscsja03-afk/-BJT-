"""Synthetic waveform tests of the capture decoder, not physical timing tests."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'board'))
from capture_tx1_bus import decode_i2c


class Wave:
    def __init__(self):
        self.scl, self.sda = [], []
        self.level(1,1)

    def level(self, scl, sda):
        self.scl.extend([3.3*scl]*10)
        self.sda.extend([3.3*sda]*10)

    def start(self):
        self.level(0,1); self.level(1,1); self.level(1,0); self.level(0,0)

    def byte(self, value, ack=True):
        for bit in [(value>>n)&1 for n in range(7,-1,-1)]+[int(not ack)]:
            self.level(0,bit); self.level(1,bit); self.level(0,bit)

    def stop(self):
        self.level(0,0); self.level(1,0); self.level(1,1)

    def decode(self):
        return decode_i2c(self.scl,self.sda,1e-7)


class Tests(unittest.TestCase):
    def test_data_write_requires_exact_bytes_ack_and_stop(self):
        for wrong_byte, nack, stopped in [(False,False,True),(True,False,True),
                                          (False,True,True),(False,False,False)]:
            with self.subTest(wrong_byte=wrong_byte,nack=nack,stopped=stopped):
                w=Wave(); w.start()
                for i,b in enumerate([0x90,8,0x7d,1 if wrong_byte else 0]):
                    w.byte(b,not(nack and i==3))
                if stopped: w.stop()
                r=w.decode()
                self.assertEqual(r['matched_code2000_write'],not wrong_byte and not nack and stopped)
                self.assertEqual(len(r['frames']),1)

    def test_repeated_start_and_final_read_nack(self):
        w=Wave(); w.start(); w.byte(0x90); w.byte(8)
        w.start(); w.byte(0x91); w.byte(0x7d); w.byte(0,False); w.stop()
        r=w.decode()
        self.assertEqual([f['hex'] for f in r['frames']],['90 08','91 7D 00'])
        self.assertEqual(r['frames'][0]['end'],'repeated_start')
        self.assertEqual(r['frames'][1]['ack'],[True,True,False])
        self.assertFalse(r['matched_code2000_write'])

    def test_idle_clock_is_not_a_frame(self):
        r=decode_i2c([3.3]*100,[3.3]*100,1e-6)
        self.assertEqual(r['frames'],[])
        self.assertIsNone(r['scl_high_min_s'])
        self.assertFalse(r['matched_code2000_write'])


if __name__ == '__main__': unittest.main()
