import unittest
from zynq_bjt.parameter_view import resize_segments


class LinkedIntervals(unittest.TestCase):
    def test_clips_extends_and_preserves_breakpoints(self):
        spec='.02:.74:.02;.74:2:.04'
        cases=[('.02','1.5','0.02:0.74:0.02;0.74:1.5:0.04'),
               ('.8','1.5','0.8:1.5:0.04'),('.02','.5','0.02:0.5:0.02'),
               ('.02','.74','0.02:0.74:0.02'),('.74','2','0.74:2:0.04'),
               ('0','3','0:0.74:0.02;0.74:3:0.04'),
               ('3','4','3:4:0.04'),('.5','.5','0.5:0.5:0.02')]
        for start,stop,want in cases:
            with self.subTest(start=start,stop=stop):self.assertEqual(resize_segments(spec,start,stop),want)

    def test_invalid_range_or_table_is_not_silently_replaced(self):
        for lo,hi in (('','2'),('nan','2'),('2','1'),('0','inf')):
            with self.assertRaises(ValueError):resize_segments('.02:2:.1',lo,hi)
        for spec in ('.02:2:0','.02:x:.1','.02:1:.1;.5:2:.1'):
            with self.assertRaises(ValueError):resize_segments(spec,.02,1.5)

if __name__=='__main__':unittest.main()
