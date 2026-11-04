"""Extract the plain U-Boot partition using Zynq-7000 header word offsets."""
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'reference/vendor_pynq/boot/boot.bin'
OUT = ROOT / 'build/work/pynq_jtag_boot'


def main():
    data = SOURCE.read_bytes()
    assert struct.unpack_from('<II', data, 0x20) == (0xAA995566, 0x584C4E58)
    iht, pht = struct.unpack_from('<II', data, 0x98)
    version, count, first = struct.unpack_from('<III', data, iht)
    assert first * 4 == pht and 0 < count < 32
    partitions = []
    matches = []
    for index in range(count):
        header = struct.unpack_from('<16I', data, pht + index * 64)
        assert sum(header) & 0xFFFFFFFF == 0xFFFFFFFF, 'Bad partition header checksum'
        size, offset = header[1] * 4, header[5] * 4
        assert offset + size <= len(data)
        item = dict(index=index, offset=offset, size=size,
                    load=header[3], entry=header[4], attributes=header[6])
        partitions.append(item)
        if header[3] == header[4] == 0x04000000:
            assert header[0] == header[1] == header[2], 'Only plain partitions supported'
            matches.append((item, data[offset:offset + size]))
    assert len(matches) == 1, 'Expected one U-Boot executable partition'
    item, payload = matches[0]
    assert struct.unpack_from('<I', payload)[0] >> 24 == 0xEA, 'Expected ARM entry branch'
    assert b'U-Boot 2020.01' in payload
    OUT.mkdir(parents=True, exist_ok=True)
    destination = OUT / 'u-boot-verified.bin'
    destination.write_bytes(payload)
    evidence = dict(source=str(SOURCE), source_sha256=hashlib.sha256(data).hexdigest(),
                    partitions=partitions, selected=item, output=str(destination),
                    output_sha256=hashlib.sha256(payload).hexdigest(),
                    note='Raw executable partition, not an ELF; data offset and length are in 32-bit words.')
    (OUT / 'extraction.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
