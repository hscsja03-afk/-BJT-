import threading
import unittest
import numpy as np
from zynq_bjt.mmio import AddaCore


class BulkSnapshotTests(unittest.TestCase):
    def core(self,mapped):
        class Device:
            def has_capability(self,name):return mapped and name=='MEMORY_MAPPED'
        class IO:
            device=Device()
            def __init__(self):
                self.array=np.zeros(0x10000//4,dtype=np.uint32);self.reads=[]
                self.array[0x0c//4]=0xa0000003
                self.array[0xc4//4]=0x53435001;self.array[0xcc//4]=4096
                self.array[0x4000//4:0x4000//4+4096]=np.arange(4096)+65536
                self.array[0x8000//4:0x8000//4+4096]=np.arange(4096)+1000
            def read(self,address):self.reads.append(address);return int(self.array[address//4])
            def write(self,address,value):self.array[address//4]=value
        core=AddaCore.__new__(AddaCore);core.io=IO();core.lock=threading.RLock();core.sequence=0
        core.wait=lambda predicate,timeout: self.assertTrue(predicate())
        return core

    def test_bulk_equals_scalar_preserves_rx_order_overrange_and_snapshot(self):
        for channels in ((0,1),(0,),(1,)):
            bulk=self.core(True);scalar=self.core(False)
            a=bulk.capture((50e6,50e6),sample_count=4096,channels=channels)
            b=scalar.capture((50e6,50e6),sample_count=4096,channels=channels)
            self.assertEqual(a.words,b.words)
            self.assertFalse(any(address>=0x4000 for address in bulk.io.reads))
            if 0 in channels:self.assertEqual(a.words[0][0],1000)
            if 1 in channels:self.assertEqual(a.overrange(1),4096)
            bulk.io.array[0x4000//4:]=0
            self.assertEqual(a.words,b.words)


if __name__=='__main__':unittest.main()
