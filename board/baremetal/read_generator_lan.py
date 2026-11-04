"""Read-only VXI-11 queries using the installed WinPcap interface.

The temporary link-local client exists only while this process runs. Probe for
address conflicts first. Do not change Windows routes, IPs or instrument state.
Only fixed query commands are exposed; no voltage-setting API is provided.
"""
import ctypes as C
from datetime import datetime
import json
from pathlib import Path
import secrets
import socket
import struct
import time

ROOT = Path(__file__).resolve().parents[2]
INTERFACE = b'\\Device\\NPF_{1F4625CF-7726-41B5-A04C-4AAAECCBEB83}'
LOCAL_MAC = bytes.fromhex('c8a362edbdbd')
DEVICE_MAC = bytes.fromhex('0019af0429a1')
DEVICE_IP = '169.254.1.5'
CLIENT_IP = '169.254.100.10'


def checksum(data):
    if len(data) % 2:
        data += b'\0'
    total = sum(struct.unpack('!' + 'H' * (len(data) // 2), data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535


class Header(C.Structure):
    _fields_ = [('sec', C.c_long), ('usec', C.c_long),
                ('caplen', C.c_uint), ('length', C.c_uint)]


class Link:
    def __init__(self):
        self.pcap = C.CDLL('C:/Windows/System32/wpcap.dll')
        specs = {
            'pcap_open_live': ([C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_char_p], C.c_void_p),
            'pcap_setnonblock': ([C.c_void_p, C.c_int, C.c_char_p], C.c_int),
            'pcap_sendpacket': ([C.c_void_p, C.c_char_p, C.c_int], C.c_int),
            'pcap_next_ex': ([C.c_void_p, C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)], C.c_int),
            'pcap_close': ([C.c_void_p], None),
        }
        for name, (args, result) in specs.items():
            f = getattr(self.pcap, name)
            f.argtypes, f.restype = args, result
        err = C.create_string_buffer(256)
        self.handle = self.pcap.pcap_open_live(INTERFACE, 65535, 0, 100, err)
        if not self.handle:
            raise RuntimeError(err.value.decode(errors='replace'))
        if self.pcap.pcap_setnonblock(self.handle, 1, err):
            self.close()
            raise RuntimeError(err.value.decode(errors='replace'))
        self.ip = socket.inet_aton(CLIENT_IP)
        self.peer_ip = socket.inet_aton(DEVICE_IP)
        self.active = False

    def close(self):
        if self.handle:
            self.pcap.pcap_close(self.handle)
            self.handle = None

    def send(self, data):
        if self.pcap.pcap_sendpacket(self.handle, data, len(data)):
            raise RuntimeError('Packet send failed')

    def receive(self):
        hp, dp = C.c_void_p(), C.c_void_p()
        result = self.pcap.pcap_next_ex(self.handle, C.byref(hp), C.byref(dp))
        if result < 0:
            raise RuntimeError('Packet capture failed')
        if not result:
            return None
        data = C.string_at(dp, C.cast(hp, C.POINTER(Header)).contents.caplen)
        if len(data) >= 42 and data[12:14] == b'\x08\x06':
            if (self.active and data[6:12] == DEVICE_MAC and data[20:22] == b'\0\x01'
                    and data[38:42] == self.ip):
                reply = DEVICE_MAC + LOCAL_MAC + b'\x08\x06'
                reply += struct.pack('!HHBBH', 1, 0x0800, 6, 4, 2)
                reply += LOCAL_MAC + self.ip + DEVICE_MAC + data[28:32]
                self.send(reply)
        return data

    def claim_temporary_address(self):
        for _ in range(2):
            packet = b'\xff' * 6 + LOCAL_MAC + b'\x08\x06'
            packet += struct.pack('!HHBBH', 1, 0x0800, 6, 4, 1)
            packet += LOCAL_MAC + b'\0' * 4 + b'\0' * 6 + self.ip
            self.send(packet)
            end = time.monotonic() + 1
            while time.monotonic() < end:
                data = self.receive()
                if not data:
                    time.sleep(.002)
                    continue
                if len(data) >= 42 and data[12:14] == b'\x08\x06' and data[6:12] != LOCAL_MAC:
                    if data[28:32] == self.ip or (data[28:32] == b'\0' * 4 and data[38:42] == self.ip):
                        raise RuntimeError('Temporary client address conflicts with another device')
        self.active = True


class TCP:
    def __init__(self, link, port):
        self.link, self.port = link, port
        self.local_port = 49152 + secrets.randbelow(16384)
        self.tx = secrets.randbits(32)
        self.rx = 0
        self.buffer = bytearray()
        self.peer_ack = self.tx
        self.closed = False
        initial = self.tx
        self.packet(2, initial)
        self.tx = (initial + 1) & 0xffffffff
        end = time.monotonic() + 4
        while time.monotonic() < end:
            segment = self.next_segment()
            if segment is None:
                time.sleep(.002)
                continue
            seq, ack, flags, payload = segment
            if flags & 4:
                raise RuntimeError('TCP connection refused on port ' + str(port))
            if flags & 18 == 18 and ack == self.tx:
                self.rx = (seq + 1) & 0xffffffff
                self.peer_ack = ack
                self.packet(16, self.tx)
                return
        raise TimeoutError('TCP handshake timeout on port ' + str(port))

    def packet(self, flags, seq, payload=b''):
        tcp = struct.pack('!HHIIBBHHH', self.local_port, self.port, seq, self.rx,
                          5 << 4, flags, 16384, 0, 0) + payload
        pseudo = self.link.ip + self.link.peer_ip + struct.pack('!BBH', 0, 6, len(tcp))
        tcp = tcp[:16] + struct.pack('!H', checksum(pseudo + tcp)) + tcp[18:]
        ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(tcp), secrets.randbelow(65536),
                         0x4000, 64, 6, 0, self.link.ip, self.link.peer_ip)
        ip = ip[:10] + struct.pack('!H', checksum(ip)) + ip[12:]
        self.link.send(DEVICE_MAC + LOCAL_MAC + b'\x08\x00' + ip + tcp)

    def next_segment(self):
        data = self.link.receive()
        if not data or len(data) < 54 or data[6:12] != DEVICE_MAC or data[12:14] != b'\x08\x00':
            return None
        ip = data[14:]
        ihl = (ip[0] & 15) * 4
        size = struct.unpack_from('!H', ip, 2)[0]
        if (ip[0] >> 4 != 4 or ihl < 20 or size > len(ip) or ip[9] != 6
                or ip[12:16] != self.link.peer_ip or ip[16:20] != self.link.ip
                or struct.unpack_from('!H', ip, 6)[0] & 0x3fff or checksum(ip[:ihl])):
            return None
        tcp = ip[ihl:size]
        if len(tcp) < 20:
            return None
        source, dest, seq, ack = struct.unpack_from('!HHII', tcp)
        offset = (tcp[12] >> 4) * 4
        if source != self.port or dest != self.local_port or offset < 20 or offset > len(tcp):
            return None
        if checksum(ip[12:20] + struct.pack('!BBH', 0, 6, len(tcp)) + tcp):
            return None
        return seq, ack, tcp[13], tcp[offset:]

    def pump(self):
        segment = self.next_segment()
        if segment is None:
            time.sleep(.002)
            return
        seq, ack, flags, payload = segment
        if flags & 4:
            raise RuntimeError('TCP reset')
        if flags & 16:
            self.peer_ack = ack
        if payload or flags & 1:
            if seq == self.rx:
                self.buffer.extend(payload)
                self.rx = (self.rx + len(payload)) & 0xffffffff
                if flags & 1:
                    self.rx = (self.rx + 1) & 0xffffffff
                    self.closed = True
            self.packet(16, self.tx)

    def send(self, data):
        for index in range(0, len(data), 512):
            payload = data[index:index+512]
            seq = self.tx
            self.tx = (self.tx + len(payload)) & 0xffffffff
            for attempt in range(3):
                self.packet(24, seq, payload)
                end = time.monotonic() + 2
                while time.monotonic() < end and self.peer_ack != self.tx:
                    self.pump()
                if self.peer_ack == self.tx:
                    break
            else:
                raise TimeoutError('TCP acknowledgement timeout')

    def read(self, size):
        end = time.monotonic() + 5
        while len(self.buffer) < size:
            if self.closed or time.monotonic() >= end:
                raise TimeoutError('TCP reply incomplete')
            self.pump()
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def close(self):
        if not self.closed:
            self.packet(17, self.tx)
            self.tx = (self.tx + 1) & 0xffffffff
            end = time.monotonic() + .3
            while time.monotonic() < end:
                self.pump()


def opaque(data):
    return struct.pack('!I', len(data)) + data + b'\0' * ((-len(data)) % 4)


def rpc(tcp, program, version, procedure, parameters):
    xid = secrets.randbits(32)
    call = struct.pack('!10I', xid, 0, 2, program, version, procedure, 0, 0, 0, 0) + parameters
    tcp.send(struct.pack('!I', 0x80000000 | len(call)) + call)
    reply = bytearray()
    while True:
        record = struct.unpack('!I', tcp.read(4))[0]
        size = record & 0x7fffffff
        if len(reply) + size > 1024 * 1024:
            raise ValueError('Oversize RPC reply')
        reply.extend(tcp.read(size))
        if record & 0x80000000:
            break
    if len(reply) < 24 or struct.unpack_from('!3I', reply) != (xid, 1, 0):
        raise ValueError('RPC reply rejected or mismatched')
    verifier_length = struct.unpack_from('!I', reply, 16)[0]
    offset = 20 + ((verifier_length + 3) // 4) * 4
    if offset + 4 > len(reply) or struct.unpack_from('!I', reply, offset)[0]:
        raise ValueError('RPC call not accepted')
    return bytes(reply[offset+4:])


def main():
    report = dict(device_ip=DEVICE_IP, device_mac=DEVICE_MAC.hex(':'),
                  temporary_client_ip=CLIENT_IP, system_network_changed=False,
                  output_settings_changed=False, queries=[], complete=False)
    link = core = None
    lid = None
    try:
        link = Link()
        link.claim_temporary_address()
        mapper = TCP(link, 111)
        try:
            reply = rpc(mapper, 100000, 2, 3, struct.pack('!4I', 0x0607af, 1, 6, 0))
            port = struct.unpack('!I', reply)[0]
        finally:
            mapper.close()
        if not 0 < port < 65536:
            raise RuntimeError('No VXI-11 service')
        report['vxi11_port'] = port
        core = TCP(link, port)
        reply = rpc(core, 0x0607af, 1, 10, struct.pack('!3I', 0x424a5431, 0, 0) + opaque(b'inst0'))
        error, lid, abort_port, maximum = struct.unpack('!4I', reply)
        if error:
            lid = None
            raise RuntimeError('VXI create_link error ' + str(error))
        queries = ['*IDN?']
        for channel in (1, 2):
            queries.extend([f':SOUR{channel}:FUNC?', f':SOUR{channel}:APPL?',
                            f':SOUR{channel}:VOLT?', f':SOUR{channel}:VOLT:OFFS?',
                            f':OUTP{channel}:LOAD?', f':OUTP{channel}?'])
        for query in queries:
            wire = (query + '\n').encode('ascii')
            reply = rpc(core, 0x0607af, 1, 11, struct.pack('!4I', lid, 3000, 0, 8) + opaque(wire))
            error, count = struct.unpack('!2I', reply)
            if error or count != len(wire):
                raise RuntimeError('VXI write query failed ' + str(error))
            answer = bytearray()
            for _ in range(4):
                reply = rpc(core, 0x0607af, 1, 12, struct.pack('!6I', lid, 4096, 3000, 0, 0, 0))
                error, reason, count = struct.unpack_from('!3I', reply)
                if error or count > 4096 or len(reply) < 12 + count:
                    raise RuntimeError('VXI read error ' + str(error))
                answer.extend(reply[12:12+count])
                if reason & 6:
                    break
            else:
                raise RuntimeError('Unterminated instrument reply')
            value = answer.decode('ascii').strip()
            report['queries'].append(dict(query=query, response=value))
            print(query, value, flush=True)
            if query == '*IDN?' and 'DG1032Z,DG1ZA173802542,' not in value:
                raise RuntimeError('Unexpected instrument identity')
        report['complete'] = True
    except Exception as error:
        report['error'] = repr(error)
        print('ERROR', repr(error), flush=True)
    finally:
        if core is not None:
            try:
                if lid is not None:
                    reply = rpc(core, 0x0607af, 1, 23, struct.pack('!I', lid))
                    if struct.unpack('!I', reply)[0]:
                        raise RuntimeError('VXI destroy_link failed')
                core.close()
            except Exception as error:
                report['cleanup_error'] = repr(error)
        if link is not None:
            link.close()
        output = ROOT/'build/logs'/('generator_readonly_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('REPORT', output, 'complete', report['complete'], flush=True)
    if not report['complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
