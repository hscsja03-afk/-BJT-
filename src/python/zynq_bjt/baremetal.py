"""PC-side adapter for the OCM firmware. No PYNQ/Linux dependency on the board.

UART 115200 8N1; sequence, length and CRC protect complete command/reply frames.
Commands that time out are never replayed automatically.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import threading
import time
import zlib
from .mmio import Frame, validate_capture_channels
from .runtime import OutputState


def crc_words(words):
    return zlib.crc32(struct.pack('<'+'I'*len(words), *words)) & 0xffffffff


class FirmwareError(RuntimeError):
    def __init__(self, status, payload):
        super().__init__(f'Baremetal status {status}; detail {payload}')
        self.status, self.payload = status, payload


class SerialLink:
    def __init__(self, serial, timeout=8.0):
        self.serial, self.timeout = serial, timeout
        self.sequence = 0
        self.lock = threading.RLock()
        self.desynchronized = False

    def _line(self, deadline):
        result = bytearray()
        while time.monotonic() < deadline:
            chunk = self.serial.read(1)
            if not chunk: continue
            result += chunk
            if len(result) > 200: raise ValueError('Oversize firmware line')
            if chunk == b'\n': return result.decode('ascii').strip().split()
        raise TimeoutError('Firmware response timed out; command was not replayed')

    def command(self, op, *args):
        if len(args) > 4 or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in (op,)+args):
            raise ValueError('Expected up to four unsigned 32-bit arguments')
        with self.lock:
            if self.desynchronized: raise RuntimeError('Serial framing lost; reload/reconnect before further commands')
            self.sequence = (self.sequence + 1) & 0xffffffff or 1
            request = [self.sequence, op, *args, *([0]*(4-len(args)))]
            wire = ('C '+' '.join(map(str,request+[crc_words(request)]))+'\n').encode('ascii')
            try:
                if self.serial.write(wire) != len(wire): raise IOError('Short serial write')
                deadline = time.monotonic()+self.timeout
                header = self._line(deadline)
                if len(header)!=5 or header[0]!='R': raise ValueError('Invalid firmware response header')
                seq, status, count, crc = map(int,header[1:])
                if seq!=self.sequence or not 0 <= count <= 2048 or not 0 <= status <= 0xffffffff:
                    raise ValueError('Firmware response sequence/count/status mismatch')
                payload = []
                while len(payload)<count:
                    line=self._line(deadline)
                    expected=min(16,count-len(payload))
                    if len(line)!=expected+2 or line[0]!='D' or int(line[1])!=len(payload):
                        raise ValueError('Firmware payload length/order mismatch')
                    values=[int(v,16) for v in line[2:]]
                    if any(not 0 <= v <= 0xffffffff for v in values): raise ValueError('Invalid payload word')
                    payload.extend(values)
                if crc_words([seq,status,count]+payload)!=crc: raise ValueError('Firmware CRC mismatch')
            except BaseException:
                self.desynchronized=True
                raise
            if status: raise FirmwareError(status,payload)
            return payload

    def close(self): self.serial.close()


class BaremetalBoard:
    """Same measurement interface as Board; calibration remains on the PC."""
    max_idle_s = 8.0  # Firmware mutes after ten seconds without a valid command.

    def __init__(self, link, identity):
        self.link=link
        self.identity=dict(identity, transport='baremetal_uart', ddr_used=False)
        self.initialized=self.adc_ready=False
        self.sample_rates_hz=None
        info=self.link.command(1)
        if len(info)!=7 or info[:3]!=[1,1,0] or info[3]>0x30000 or info[4]!=50000000:
            raise ValueError('Expected the ADDA OCM firmware, ABI1, DDR disabled, baseline50')
        if info[5]: raise RuntimeError('Firmware reports a UART transport fault')
        if self.identity.get('firmware_build_id') != info[6]: raise ValueError('Running firmware build differs from selected manifest')

    @classmethod
    def open(cls, port, artifact_dir, firmware_dir=None):
        import serial
        artifact_dir=Path(artifact_dir)
        identity={f'{suffix}_sha256':hashlib.sha256((artifact_dir/f'bjt.{suffix}').read_bytes()).hexdigest()
                  for suffix in ('bit','hwh')}
        # Hashes identify the user-selected download pair; no device attestation.
        identity['hash_basis']='local files selected for JTAG download; not read back from FPGA'
        firmware_dir=Path(firmware_dir) if firmware_dir else artifact_dir.parent/'baremetal'
        manifest=json.loads((firmware_dir/'manifest.json').read_text())
        firmware_sha=hashlib.sha256((firmware_dir/'adda.elf').read_bytes()).hexdigest()
        if manifest['images']['adda']['sha256']!=firmware_sha: raise ValueError('Firmware ELF/manifest mismatch')
        identity.update(firmware_sha256=firmware_sha,firmware_build_id=manifest['build_id'])
        stream=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=1)
        stream.dtr=stream.rts=False
        stream.port=port
        stream.open()
        stream.reset_input_buffer()
        link=SerialLink(stream)
        try: return cls(link,identity)
        except BaseException:
            link.close()
            raise

    def initialize(self, *, adc_divider=20, dac_divider=20):
        if (adc_divider,dac_divider)!=(20,20): raise ValueError('Baremetal currently supports baseline50 only')
        if self.initialized: raise RuntimeError('Already initialized')
        try:
            rates=self.link.command(2,adc_divider,dac_divider)
            if len(rates)!=3 or any(not 49000000<=r<=51000000 for r in rates):
                raise ValueError('Unexpected measured clock rates')
        except BaseException:
            # A complete but invalid reply still permits an explicit STOP.
            # Lost framing must wait for the firmware watchdog or a reload.
            if not self.link.desynchronized:
                self.link.command(8)
            raise
        self.sample_rates_hz=tuple(rates[:2])
        self.identity.update(measured_clock_hz=rates,digital_self_test='passed',analog_calibration_qualified=False)
        self.initialized=self.adc_ready=True
        return dict(self.identity)

    def capture(self, channels=(0, 1)):
        validate_capture_channels(channels)
        if not self.adc_ready: raise RuntimeError('Initialize ADC first')
        with self.link.lock:
            payload=self.link.command(3)
            if len(payload)!=2048: raise ValueError('Incomplete ADC frame')
            # The legacy UART firmware returns both RAMs in one response.
            words=tuple(tuple(payload[ch*1024:(ch+1)*1024]) if ch in channels else () for ch in (0,1))
            return Frame(self.link.sequence,words,self.sample_rates_hz,time.time(),
                         captured_channels=tuple(channels))

    def gpio(self, mask=None, value=None):
        if mask is None: mask,value=0,0
        if any(type(v) is not int or not 0<=v<=127 for v in (mask,value)):
            raise ValueError('GPIO mask/value must be seven-bit integers')
        values=self.link.command(7,mask,value)
        if len(values)!=3: raise ValueError('Invalid GPIO response')
        return dict(zip(('output','sense','sequence'),values))

    @staticmethod
    def _output(channel, payload):
        if len(payload)!=2 or payload[1] not in (0,1) or not 0<=payload[0]<=(4095 if channel==0 else 65535):
            raise ValueError('Invalid output state')
        return OutputState(payload[0],bool(payload[1]),
            'device_register_readback' if channel==0 else 'table_commit_ack_not_analog_readback')

    def output(self, channel):
        if type(channel) is not int or channel not in (0,1,2): raise ValueError('Invalid output channel')
        return self._output(channel,self.link.command(6,channel))

    def set_code(self, channel, code):
        if type(channel) is not int or channel not in (0,1,2) or type(code) is not int or not 0<=code<=(4095 if channel==0 else 65535):
            raise ValueError('Invalid output channel/code')
        return self._output(channel,self.link.command(4,channel,code))

    def enable(self, channel, enabled):
        if type(channel) is not int or channel not in (0,1,2) or type(enabled) is not bool:
            raise ValueError('Invalid output enable')
        return self._output(channel,self.link.command(5,channel,int(enabled)))

    def close(self):
        try: self.link.command(8)
        finally:
            self.initialized=self.adc_ready=False
            self.link.close()


def main():
    parser=argparse.ArgumentParser(description='PC control of the OCM baremetal firmware')
    parser.add_argument('--port',required=True)
    parser.add_argument('--artifacts',type=Path,default=Path('build/work/baseline50'))
    parser.add_argument('--capture',type=Path,help='Initialize muted, run ADC digital tests, save one raw frame')
    args=parser.parse_args()
    board=BaremetalBoard.open(args.port,args.artifacts)
    try:
        print(json.dumps(board.identity,indent=2))
        if args.capture:
            from dataclasses import asdict
            board.initialize()
            frame=board.capture()
            args.capture.parent.mkdir(parents=True,exist_ok=True)
            args.capture.write_text(json.dumps({'identity':board.identity,'frame':asdict(frame)},indent=2)+'\n')
            print('Saved raw ADC frame; analog calibration is not yet qualified:',args.capture)
    finally: board.close()


if __name__=='__main__': main()
