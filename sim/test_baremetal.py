import struct
import sys
import unittest
import zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/python'))
from zynq_bjt.baremetal import BaremetalBoard, FirmwareError, SerialLink


class Wire:
    def __init__(self, payload, status=0, damage=None):
        self.payload,self.status,self.damage=payload,status,damage
        self.buffer=bytearray();self.writes=[];self.closed=False

    def write(self, value):
        self.writes.append(value)
        fields=value.decode().split()
        words=list(map(int,fields[1:]))
        assert fields[0]=='C' and len(words)==7
        assert (zlib.crc32(struct.pack('<6I',*words[:6]))&0xffffffff)==words[6]
        seq=words[0]+(1 if self.damage=='sequence' else 0)
        payload=list(self.payload)
        response=[seq,self.status,len(payload)]+payload
        crc=zlib.crc32(struct.pack('<'+'I'*len(response),*response))&0xffffffff
        if self.damage=='crc':crc^=1
        text=f'R {seq} {self.status} {len(payload)} {crc}\n'
        for i in range(0,len(payload),16):
            index=i+1 if self.damage=='order' else i
            text+=f'D {index} '+ ' '.join(f'{v:08x}' for v in payload[i:i+16])+'\n'
        if self.damage=='partial':text=text[:-4]
        self.buffer.extend(text.encode())
        return len(value)

    def read(self, size):
        result=bytes(self.buffer[:size]);del self.buffer[:size];return result

    def close(self):self.closed=True


class BaremetalTests(unittest.TestCase):
    def test_frame_transport_preserves_overrange_and_channel_order(self):
        wire=Wire([1,1,0,125664,50000000,0,123]);link=SerialLink(wire)
        board=BaremetalBoard(link,{'firmware_build_id':123})
        wire.payload=[50000001,49999999,50000000]
        board.initialize()
        wire.payload=[0x18001]*1024+[0x2345]*1024
        frame=board.capture()
        self.assertEqual(frame.codes(0),(0x8001,)*1024)
        self.assertEqual(frame.overrange(0),1024)
        self.assertEqual(frame.codes(1),(0x2345,)*1024)
        self.assertFalse(frame.simulated)

    def test_probe_cannot_be_used_as_adda(self):
        with self.assertRaises(ValueError):BaremetalBoard(SerialLink(Wire([1,0,0,117344,50000000,0,123])),{})

    def test_corrupt_crc_order_and_sequence_stop_further_commands(self):
        for damage in ('crc','order','sequence'):
            wire=Wire([123,456],damage=damage);link=SerialLink(wire)
            with self.assertRaises(ValueError):link.command(1)
            with self.assertRaises(RuntimeError):link.command(1)
            self.assertEqual(len(wire.writes),1)

    def test_partial_frame_times_out_without_retry(self):
        wire=Wire([123],damage='partial');link=SerialLink(wire,timeout=.01)
        with self.assertRaises(TimeoutError):link.command(1)
        self.assertEqual(len(wire.writes),1)

    def test_firmware_error_keeps_complete_transport_synchronized(self):
        wire=Wire([],status=7);link=SerialLink(wire)
        with self.assertRaises(FirmwareError) as error:link.command(2,20,20)
        self.assertEqual(error.exception.status,7)
        self.assertFalse(link.desynchronized)
        wire.status=0;wire.payload=[1]
        self.assertEqual(link.command(1),[1])

    def test_invalid_argument_does_not_write(self):
        wire=Wire([]);link=SerialLink(wire)
        for args in ((-1,), (1,-1), (1,2**32), (True,)):
            with self.assertRaises(ValueError):link.command(*args)
        self.assertEqual(wire.writes,[])

    def test_close_releases_port_even_when_stop_fails(self):
        wire=Wire([1,1,0,125664,50000000,0,123]);board=BaremetalBoard(SerialLink(wire),{'firmware_build_id':123})
        wire.status=9;wire.payload=[]
        with self.assertRaises(FirmwareError):board.close()
        self.assertTrue(wire.closed)

    def test_capture_rejects_short_complete_payload(self):
        wire=Wire([1,1,0,125664,50000000,0,123]);board=BaremetalBoard(SerialLink(wire),{'firmware_build_id':123})
        board.adc_ready=True;wire.payload=[0]*1024
        with self.assertRaises(ValueError):board.capture()


if __name__=='__main__':unittest.main()
