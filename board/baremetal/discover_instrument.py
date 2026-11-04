"""Read-only LXI discovery on one explicitly selected local interface."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import ipaddress
import json
from pathlib import Path
import socket
import struct
import time

ROOT = Path(__file__).resolve().parents[2]


def name_wire(name):
    return b''.join(bytes([len(p)]) + p.encode('ascii') for p in name.split('.')) + b'\0'


def dns_name(data, offset, seen=None):
    seen = set() if seen is None else seen
    parts = []
    end = None
    while True:
        if offset in seen or offset >= len(data):
            raise ValueError('Invalid DNS name')
        seen.add(offset)
        n = data[offset]
        offset += 1
        if n & 0xc0 == 0xc0:
            ptr = ((n & 63) << 8) | data[offset]
            if end is None:
                end = offset + 1
            label, _ = dns_name(data, ptr, seen)
            parts.append(label)
            break
        if not n:
            break
        parts.append(data[offset:offset+n].decode('utf-8', errors='replace'))
        offset += n
    return '.'.join(parts), end if end is not None else offset


def parse_dns(data):
    _, _, nq, na, ns, nx = struct.unpack_from('!6H', data)
    offset = 12
    for _ in range(nq):
        _, offset = dns_name(data, offset)
        offset += 4
    records = []
    for _ in range(na + ns + nx):
        name, offset = dns_name(data, offset)
        kind, cls, ttl, size = struct.unpack_from('!HHIH', data, offset)
        offset += 10
        body = data[offset:offset+size]
        if kind == 1 and size == 4:
            value = socket.inet_ntoa(body)
        elif kind == 12:
            value, _ = dns_name(data, offset)
        elif kind == 33:
            priority, weight, port = struct.unpack_from('!HHH', body)
            host, _ = dns_name(data, offset + 6)
            value = dict(host=host, port=port, priority=priority, weight=weight)
        else:
            value = body.hex()
        records.append(dict(name=name, type=kind, value=value, ttl=ttl))
        offset += size
    return records


def mdns(source):
    result = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('', 5353))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(source))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                     socket.inet_aton('224.0.0.251') + socket.inet_aton(source))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        services = ['_lxi._tcp.local', '_vxi-11._tcp.local', '_scpi-raw._tcp.local',
                    '_http._tcp.local', '_services._dns-sd._udp.local']
        packet = struct.pack('!6H', 0, 0, len(services), 0, 0, 0)
        packet += b''.join(name_wire(n) + struct.pack('!HH', 12, 1) for n in services)
        s.sendto(packet, ('224.0.0.251', 5353))
        end = time.monotonic() + 6
        s.settimeout(.5)
        while time.monotonic() < end:
            try:
                data, peer = s.recvfrom(65535)
            except socket.timeout:
                continue
            if peer[0] == source:
                continue
            try:
                records = parse_dns(data)
            except (ValueError, IndexError, struct.error) as error:
                records = [dict(parse_error=str(error))]
            result.append(dict(peer=peer, records=records, packet_hex=data.hex()))
    return result


def rpc_broadcast(source, broadcast):
    result = []
    xid = 0x424a5431
    packet = struct.pack('!14I', xid, 0, 2, 100000, 2, 3, 0, 0, 0, 0, 0x0607af, 1, 6, 0)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind((source, 0))
        s.settimeout(.5)
        s.sendto(packet, (broadcast, 111))
        end = time.monotonic() + 6
        while time.monotonic() < end:
            try:
                data, peer = s.recvfrom(4096)
            except socket.timeout:
                continue
            if len(data) >= 4 and struct.unpack_from('!I', data)[0] == xid:
                result.append(dict(peer=peer, packet_hex=data.hex()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--subnet', required=True)
    args = parser.parse_args()
    network = ipaddress.IPv4Network(args.subnet)
    if ipaddress.IPv4Address(args.source) not in network:
        raise ValueError('Source must be in selected subnet')
    report = dict(source=args.source, subnet=args.subnet, configuration_changed=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {'mdns': pool.submit(mdns, args.source),
                   'rpc': pool.submit(rpc_broadcast, args.source, str(network.broadcast_address))}
        for name, future in futures.items():
            try:
                report[name] = future.result()
            except Exception as error:
                report[name] = dict(error=repr(error))
    output = ROOT/'build/logs'/('instrument_discovery_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(output=str(output), **report), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
